"""Single allowed solver. Lazy SDK loading keeps contracts importable without it."""
from decimal import Decimal
from time import perf_counter

from decision_core.contracts import RunStatus
from decision_core.storage_calculation import RawSolution, SolverReport


def highs_backend(problem):
    started = perf_counter()
    try:
        import pulp
        import highspy
        r = problem.request
        n = len(r.prices)
        f = float
        model = pulp.LpProblem("storage_sandbox", pulp.LpMaximize)
        charge = [pulp.LpVariable(f"c{i}", 0, f(r.charge_power_limit_mw)) for i in range(n)]
        discharge = [pulp.LpVariable(f"d{i}", 0, f(r.discharge_power_limit_mw)) for i in range(n)]
        mode = [pulp.LpVariable(f"z{i}", cat=pulp.LpBinary) for i in range(n)]
        energy = [pulp.LpVariable(f"e{i}", f(r.energy_capacity_mwh*r.min_soc_ratio),
                                  f(r.energy_capacity_mwh*r.max_soc_ratio)) for i in range(n+1)]
        model += energy[0] == f(r.energy_capacity_mwh*r.current_soc_ratio)
        model += energy[-1] == f(r.energy_capacity_mwh*r.terminal_soc_ratio)
        for i in range(n):
            model += charge[i] <= f(r.charge_power_limit_mw)*mode[i]
            model += discharge[i] <= f(r.discharge_power_limit_mw)*(1-mode[i])
            model += energy[i+1] == energy[i] + f(problem.charge_energy_coefficient)*charge[i] - f(problem.discharge_energy_coefficient)*discharge[i]
        model += pulp.lpSum((charge[i]+discharge[i])*f(r.dt_hours) for i in range(n)) <= f(r.remaining_throughput_mwh)
        if problem.force_first_full_discharge:
            model += charge[0] == 0
            model += discharge[0] == f(r.discharge_power_limit_mw)
        for i in problem.idle_indices:
            model += charge[i] == 0
            model += discharge[i] == 0
        model += pulp.lpSum(f(problem.charge_objective[i])*charge[i] + f(problem.discharge_objective[i])*discharge[i] for i in range(n))
        solver = pulp.HiGHS(msg=False, threads=1, timeLimit=5, gapRel=0.0, gapAbs=0.0,
                            primal_feasibility_tolerance=1e-8, mip_feasibility_tolerance=1e-8,
                            random_seed=0, parallel="off", log_to_console=False)
        if not solver.available():
            return RawSolution(SolverReport(RunStatus.SOLVER_ERROR, "solver_unavailable"))
        model.solve(solver)
        for option, expected in (("threads",1),("time_limit",5.0),("mip_rel_gap",0.0),("mip_abs_gap",0.0)):
            status,value = model.solverModel.getOptionValue(option)
            if status != highspy.HighsStatus.kOk or value != expected:
                return RawSolution(SolverReport(RunStatus.SOLVER_ERROR,"solver_option_mismatch"))
        actual = model.solverModel.getModelStatus()
        elapsed = str(perf_counter()-started)
        if actual == highspy.HighsModelStatus.kInfeasible:
            return RawSolution(SolverReport(RunStatus.INFEASIBLE, "kInfeasible", elapsed_seconds=elapsed))
        if actual == highspy.HighsModelStatus.kTimeLimit:
            return RawSolution(SolverReport(RunStatus.TIME_LIMIT, "kTimeLimit", elapsed_seconds=elapsed))
        if (actual != highspy.HighsModelStatus.kOptimal or model.status != pulp.LpStatusOptimal
                or model.sol_status != pulp.LpSolutionOptimal):
            return RawSolution(SolverReport(RunStatus.SOLVER_ERROR, "not_proven_optimal", elapsed_seconds=elapsed))
        info = model.solverModel.getInfo()
        gap = Decimal(str(info.mip_gap))
        # PuLP's HiGHS adapter negates maximum objectives when building the SDK model.
        objective = -model.solverModel.getObjectiveValue()
        report = SolverReport(RunStatus.OPTIMAL, "kOptimal", True, str(objective), str(gap), elapsed)
        return RawSolution(report, tuple(str(v.varValue) for v in charge), tuple(str(v.varValue) for v in discharge),
                           tuple(str(v.varValue) for v in energy), tuple(str(v.varValue) for v in mode))
    except Exception:
        # No stack trace, source path or raw SDK text leaves this adapter; never fallback.
        return RawSolution(SolverReport(RunStatus.SOLVER_ERROR, "adapter_error", elapsed_seconds=str(perf_counter()-started)))
