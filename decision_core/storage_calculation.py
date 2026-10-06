"""Pure storage arithmetic, checks, comparisons and explanations; no solver/IO imports.

The trusted adapter supplies MILP values; this module independently replays them.
S1 contracts remain immutable. This implementation has its own explicit version.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext, ROUND_HALF_EVEN

from .contracts import (Amount, AmountStatus, StorageStep, StoragePlan, StorageOutput,
                        ResultMetadata, RunStatus, fingerprint)
from .errors import require, ContractError
from .numbers import number, decimal_text, MAX_ABS_AMOUNT
from .storage import StorageRequest, normalize_storage

ENGINE_VERSION = "storage-sandbox-engine-v1"
ENERGY_TOL = Decimal("0.000001")
POWER_CLEANUP_TOL = Decimal("0.00000001")
OUTPUT_QUANTUM = Decimal("0.000000000001")
METHODS = ("optimized", "full_discharge_now", "wait_until")
METHOD_ZH = {"optimized": "综合安排剩余时段", "full_discharge_now": "现在第一时段满功率放电",
             "wait_until": "留到指定时刻再安排"}
ZERO = Decimal(0)


def precise(value):
    return value.quantize(OUTPUT_QUANTUM, rounding=ROUND_HALF_EVEN)


def business_text(value):
    """Short business prose; typed output retains 12-place reproducible precision."""
    rounded=value.quantize(Decimal("0.01"),rounding=ROUND_HALF_EVEN)
    if value != 0 and rounded == 0:
        return "小于0.01" if value>0 else "介于负0.01和零之间"
    return decimal_text(rounded)


def money(value):
    return Amount(AmountStatus.EVALUATED, precise(value))


def money_tolerance(*values):
    """Tool numerical tolerance, not an economic materiality/market rule."""
    return max(Decimal("0.01"), max((abs(v) for v in values), default=ZERO)*Decimal("1e-10"))


def solver_number(raw, *, minimum=None, maximum=None):
    """SDK double values can have exponent below the user-input precision limit.

    This does not relax request validation. Finite/bounded values are replayed
    before output quantization; tiny power cleanup remains explicitly recorded.
    """
    require(not isinstance(raw,bool) and isinstance(raw,(str,int,float,Decimal)), "求解数值类型不正确。")
    text=str(raw)
    require(len(text)<=64, "求解数值表示过长。")
    try:
        value=Decimal(text)
    except ArithmeticError:
        require(False,"求解数值无法解析。")
    require(value.is_finite() and len(value.as_tuple().digits)<=32
            and -324<=value.as_tuple().exponent<=18,"求解数值缺失或超出安全精度范围。")
    require(minimum is None or value>=minimum,"求解数值低于允许范围。")
    require(maximum is None or value<=maximum,"求解数值超过允许范围。")
    return value


def validated_request(request):
    require(isinstance(request, StorageRequest), "请先完成电池条件校验。")
    clean = normalize_storage(request.editable_payload())
    require(clean.input_sha256 == request.input_sha256, "电池请求与已校验条件不一致。")
    return request


@dataclass(frozen=True)
class MilpProblem:
    request: StorageRequest
    method: str
    charge_objective: tuple[Decimal, ...]
    discharge_objective: tuple[Decimal, ...]
    charge_energy_coefficient: Decimal
    discharge_energy_coefficient: Decimal
    idle_indices: tuple[int, ...]
    force_first_full_discharge: bool


def milp_problem(request, method):
    require(method in METHODS, "未登记的对照方法。")
    dt, cost = request.dt_hours, request.degradation_cost_yuan_per_mwh_throughput
    return MilpProblem(request, method,
                       tuple(-(r.forecast_price_yuan_per_mwh+cost)*dt for r in request.prices),
                       tuple((r.forecast_price_yuan_per_mwh-cost)*dt for r in request.prices),
                       request.charge_efficiency*dt, dt/request.discharge_efficiency,
                       tuple(i for i,r in enumerate(request.prices) if method == "wait_until"
                             and r.interval_start < request.wait_until),
                       method == "full_discharge_now")


@dataclass(frozen=True)
class SolverReport:
    status: RunStatus
    raw_status: str
    proven_optimal: bool = False
    objective_yuan: str | None = None
    gap: str | None = None
    elapsed_seconds: str | None = None
    solver: str = "HiGHS"
    threads: int = 1
    time_limit_seconds: int = 5


@dataclass(frozen=True)
class RawSolution:
    report: SolverReport
    charge_mw: tuple = ()
    discharge_mw: tuple = ()
    energy_mwh: tuple = ()
    mode: tuple = ()


@dataclass(frozen=True)
class PhysicalCheck:
    maximum_balance_residual_mwh: Decimal
    maximum_solver_state_difference_mwh: Decimal
    terminal_error_mwh: Decimal
    total_throughput_mwh: Decimal
    remaining_throughput_mwh: Decimal
    maximum_power_cleanup_mw: Decimal
    energy_tolerance_mwh: Decimal = ENERGY_TOL


@dataclass(frozen=True)
class CashRow:
    charge_energy_mwh: Decimal
    discharge_energy_mwh: Decimal
    charge_cost: Amount
    discharge_revenue: Amount
    degradation_cost: Amount


@dataclass(frozen=True)
class CashTotals:
    charge_energy_mwh: Decimal
    discharge_energy_mwh: Decimal
    throughput_mwh: Decimal
    equivalent_cycles: Decimal
    charge_cost: Amount
    discharge_revenue: Amount
    degradation_cost: Amount
    forecast_contribution: Amount
    actual_contribution: Amount
    initial_energy_mwh: Decimal
    terminal_energy_mwh: Decimal
    inventory_delta_mwh: Decimal
    inventory_cost: Amount


@dataclass(frozen=True)
class ScheduleEvaluation:
    interval_rows: tuple[StorageStep, ...]
    cash_rows: tuple[CashRow, ...]
    totals: CashTotals
    check: PhysicalCheck


def _power(raw, limit):
    value = solver_number(raw, minimum=-POWER_CLEANUP_TOL, maximum=limit+POWER_CLEANUP_TOL)
    clean = min(limit, max(ZERO, value))
    if clean <= POWER_CLEANUP_TOL:
        clean = ZERO
    return clean, abs(value-clean)


def evaluate_schedule(request, charge_mw, discharge_mw, *, method="fixed", solver_states=None, modes=None):
    """Replay fixed actions, with hard physical checks. Never repair material errors."""
    request = validated_request(request)
    with localcontext() as context:
        context.prec = 50
        n = len(request.prices)
        require(len(charge_mw) == len(discharge_mw) == n, "动作时段数量与价格表不一致。")
        require(solver_states is None or len(solver_states) == n+1, "求解电量状态不完整。")
        require(modes is None or len(modes) == n, "充放互斥状态不完整。")
        e0 = request.energy_capacity_mwh*request.current_soc_ratio
        target = request.energy_capacity_mwh*request.terminal_soc_ratio
        low, high = (request.energy_capacity_mwh*r for r in (request.min_soc_ratio, request.max_soc_ratio))
        energy, throughput, cleanup, residual, state_diff = e0, ZERO, ZERO, ZERO, ZERO
        rows, cash_rows = [], []
        states = None if solver_states is None else tuple(solver_number(v,minimum=-ENERGY_TOL,maximum=request.energy_capacity_mwh+ENERGY_TOL) for v in solver_states)
        if states is not None:
            require(abs(states[0]-e0) <= ENERGY_TOL, "求解期初电量与输入不一致。")
        for i, interval in enumerate(request.prices):
            c, dc = _power(charge_mw[i], request.charge_power_limit_mw)
            d, dd = _power(discharge_mw[i], request.discharge_power_limit_mw)
            cleanup = max(cleanup, dc, dd)
            require(not (c > 0 and d > 0), "同一时段不能同时充电和放电。")
            if modes is not None:
                mode = solver_number(modes[i],minimum=-POWER_CLEANUP_TOL,maximum=1+POWER_CLEANUP_TOL)
                require(min(abs(mode), abs(mode-1)) <= POWER_CLEANUP_TOL, "充放互斥变量不是有效整数。")
                require((c == 0 or abs(mode-1) <= POWER_CLEANUP_TOL)
                        and (d == 0 or abs(mode) <= POWER_CLEANUP_TOL), "动作与充放互斥状态不一致。")
            if method == "full_discharge_now" and i == 0:
                require(c == 0 and abs(d-request.discharge_power_limit_mw) <= POWER_CLEANUP_TOL,
                        "现在满放的第一整个时段没有真正满功率。")
            if method == "wait_until" and interval.interval_start < request.wait_until:
                require(c == d == 0, "等待前缀出现了充放动作。")
            cq, dq = c*request.dt_hours, d*request.dt_hours
            after = energy + request.charge_efficiency*cq - dq/request.discharge_efficiency
            require(low-ENERGY_TOL <= after <= high+ENERGY_TOL, "复算电量超过安全边界。")
            throughput += cq+dq
            require(throughput <= request.remaining_throughput_mwh+ENERGY_TOL, "累计充放电量超过剩余额度。")
            if states is not None:
                residual = max(residual, abs(states[i+1]-states[i]-request.charge_efficiency*cq+dq/request.discharge_efficiency))
                state_diff = max(state_diff, abs(states[i+1]-after))
                require(residual <= ENERGY_TOL and state_diff <= ENERGY_TOL, "求解状态与独立电量复算不一致。")
            p = interval.forecast_price_yuan_per_mwh
            cost, revenue = money(p*cq), money(p*dq)
            loss = money(request.degradation_cost_yuan_per_mwh_throughput*(cq+dq))
            contribution = Amount(AmountStatus.EVALUATED, revenue.value_yuan-cost.value_yuan-loss.value_yuan)
            # S1 rows require nonnegative state/budget; only sub-tolerance roundoff is normalized.
            rows.append(StorageStep(interval.interval_start, interval.interval_end, precise(c), precise(d),
                                    precise(max(ZERO, energy)), precise(max(ZERO, after)),
                                    precise(max(ZERO, request.remaining_throughput_mwh-throughput)), contribution))
            cash_rows.append(CashRow(precise(cq), precise(dq), cost, revenue, loss))
            energy = after
        terminal_error = abs(energy-target)
        require(terminal_error <= ENERGY_TOL, "计划结束电量未达到目标。")
        total_charge = sum((r.charge_energy_mwh for r in cash_rows), ZERO)
        total_discharge = sum((r.discharge_energy_mwh for r in cash_rows), ZERO)
        total_cost = sum((r.charge_cost.value_yuan for r in cash_rows), ZERO)
        total_revenue = sum((r.discharge_revenue.value_yuan for r in cash_rows), ZERO)
        total_loss = sum((r.degradation_cost.value_yuan for r in cash_rows), ZERO)
        total_contribution = sum((r.contribution.value_yuan for r in rows), ZERO)
        require(total_contribution == total_revenue-total_cost-total_loss, "逐行收支加总不一致。")
        totals = CashTotals(total_charge, total_discharge, total_charge+total_discharge,
                            precise((total_charge+total_discharge)/(2*request.energy_capacity_mwh)),
                            money(total_cost), money(total_revenue), money(total_loss), money(total_contribution),
                            Amount(AmountStatus.NOT_EVALUABLE, None), precise(e0), precise(energy),
                            precise(energy-e0), Amount(AmountStatus.UNKNOWN, None))
        check = PhysicalCheck(precise(residual), precise(state_diff), precise(terminal_error), precise(throughput),
                              precise(request.remaining_throughput_mwh-throughput), precise(cleanup))
        return ScheduleEvaluation(tuple(rows), tuple(cash_rows), totals, check)


@dataclass(frozen=True)
class ComputedPlan:
    plan: StoragePlan
    input_sha256: str
    diagnostic_zh: str
    reason_code: str
    solver_report: SolverReport | None = None
    evaluation: ScheduleEvaluation | None = None
    decision_log: tuple = ()


def unavailable_plan(method, status, message, code, input_hash, report=None):
    return ComputedPlan(StoragePlan(method, status, Amount(AmountStatus.NOT_EVALUABLE, None), False, False),
                        input_hash, message, code, report)


def compute_plan(request, method, backend):
    if method == "wait_until" and request.wait_until is None:
        return unavailable_plan(method, RunStatus.UNRESOLVED, "还没有选择留到哪个时刻；此对照未计算。",
                                "WAIT_TIME_UNSPECIFIED", request.input_sha256)
    raw = backend(milp_problem(request, method))
    require(isinstance(raw, RawSolution) and isinstance(raw.report, SolverReport), "求解器返回结构不正确。")
    report = raw.report
    if report.status != RunStatus.OPTIMAL or not report.proven_optimal or report.raw_status != "kOptimal":
        status = report.status if report.status != RunStatus.OPTIMAL else RunStatus.SOLVER_ERROR
        message = {
            RunStatus.INFEASIBLE: "在同样电量目标和剩余额度下，这个办法无法满足所有限制。",
            RunStatus.TIME_LIMIT: "计算达到时间限制，未证明最优；本次不给建议或零收益。",
        }.get(status, "计算未得到经过验证的结果，请检查条件或稍后重试。")
        return unavailable_plan(method, status, message, "SOLVE_NOT_PROVEN", request.input_sha256, report)
    try:
        require(report.solver == "HiGHS" and report.threads == 1 and report.time_limit_seconds == 5,
                "求解器设置与本工具验收范围不一致。")
        require(report.objective_yuan is not None and report.gap is not None, "缺少最优性核验信息。")
        require(number(report.gap, minimum=ZERO) <= Decimal("1e-9"), "求解器尚有未接受的最优间隙。")
        ev = evaluate_schedule(request, raw.charge_mw, raw.discharge_mw, method=method,
                               solver_states=raw.energy_mwh, modes=raw.mode)
        objective = solver_number(report.objective_yuan,minimum=-MAX_ABS_AMOUNT,maximum=MAX_ABS_AMOUNT)
        require(abs(objective-ev.totals.forecast_contribution.value_yuan)
                <= money_tolerance(objective, ev.totals.forecast_contribution.value_yuan), "求解目标与逐行收支复算不一致。")
    except (ContractError, ArithmeticError):
        return unavailable_plan(method, RunStatus.SOLVER_ERROR, "求解结果没有通过独立复算，不能作为建议。",
                                "PHYSICAL_OR_OBJECTIVE_CHECK_FAILED", request.input_sha256, report)
    plan = StoragePlan(method, RunStatus.OPTIMAL, ev.totals.forecast_contribution, True, True, ev.interval_rows)
    return ComputedPlan(plan, request.input_sha256, "在本次预测与约束下，已通过最优性和独立电量复核。",
                        "CHECKED_OPTIMAL", report, ev, decision_log(request, method, ev))


@dataclass(frozen=True)
class IntervalDecision:
    interval_index: int
    interval_start: datetime
    action_zh: str
    power_mw: Decimal
    soc_before_ratio: Decimal
    soc_after_ratio: Decimal
    forecast_price_yuan_per_mwh: Decimal
    remaining_throughput_mwh: Decimal
    reason_zh: str
    technical_reason_codes: tuple[str, ...]


def decision_log(request, method, evaluation):
    log = []
    fmt = business_text
    for i,row in enumerate(evaluation.interval_rows):
        c,d = row.charge_power_mw, row.discharge_power_mw
        action, power = ("充电",c) if c>0 else (("放电",d) if d>0 else ("等待",ZERO))
        before = precise(row.stored_energy_before_mwh/request.energy_capacity_mwh)
        after = precise(row.stored_energy_after_mwh/request.energy_capacity_mwh)
        p = request.prices[i].forecast_price_yuan_per_mwh
        reason = f"本时段预测价{fmt(p)}元/兆瓦时，电量由{fmt(before*100)}%到{fmt(after*100)}%，结束后还允许累计充放{fmt(row.remaining_throughput_mwh)}兆瓦时。"
        codes = ["PLAN_ACTION_"+({"充电":"CHARGE","放电":"DISCHARGE","等待":"WAIT"}[action])]
        if method == "wait_until" and row.interval_start < request.wait_until:
            reason += f"用户指定{request.wait_until:%H:%M}前不充不放，这个对照遵守等待限制。"
            codes.append("USER_WAIT_PREFIX")
        elif method == "full_discharge_now" and i == 0:
            reason += "这是对照方案强制的第一整段满功率放电，不是综合方案的推荐。"
            codes.append("FORCED_FULL_DISCHARGE")
        else:
            reason += f"这是同时考虑后续价格、效率、模拟损耗、剩余额度和{request.prices[-1].interval_end:%H:%M}结束留电量的整条计划安排。"
            future = request.prices[i+1:]
            if future:
                peak = max(future,key=lambda r:r.forecast_price_yuan_per_mwh)
                reason += f"后续预测最高价在{peak.interval_start:%H:%M}，为{fmt(peak.forecast_price_yuan_per_mwh)}元/兆瓦时；这不单独证明动作的唯一原因。"
            limit = request.charge_power_limit_mw if c>0 else request.discharge_power_limit_mw
            if 0<power<limit-POWER_CLEANUP_TOL:
                reason += "本段未满功率；限制状态与整段机会取舍需要一起看。"
                codes.append("PARTIAL_POWER_OBSERVED")
        log.append(IntervalDecision(i,row.interval_start,action,power,before,after,p,
                                    row.remaining_throughput_mwh,reason,tuple(codes)))
    return tuple(log)


@dataclass(frozen=True)
class Comparison:
    method: str
    status: RunStatus
    optimized_minus_plan: Amount
    near_tie: bool


@dataclass(frozen=True)
class ActionAdvice:
    available: bool
    action_zh: str
    power_mw: Decimal | None
    explanation_zh: tuple[str, ...]
    technical_reason_codes: tuple[str, ...]


def explain(request, computed, comparisons):
    best = computed[0]
    if best.plan.status != RunStatus.OPTIMAL:
        return ActionAdvice(False, "暂不能给出动作建议", None, (best.diagnostic_zh,), (best.reason_code,))
    row = best.plan.interval_rows[0]
    if row.charge_power_mw > 0:
        action, power, code = "充电", row.charge_power_mw, "FIRST_ACTION_CHARGE"
    elif row.discharge_power_mw > 0:
        action, power, code = "放电", row.discharge_power_mw, "FIRST_ACTION_DISCHARGE"
    else:
        action, power, code = "等待", ZERO, "FIRST_ACTION_WAIT"
    fmt = business_text
    future = request.prices[1:]
    lines = [f"按你给出的电价和电池条件，当前安排是{action}，速度{fmt(power)}兆瓦；这是整个剩余计划的结果，不只看当前价格。",
             f"现在电量为{fmt(request.current_soc_ratio*100)}%，计划到{request.prices[-1].interval_end:%H:%M}要留{fmt(request.terminal_soc_ratio*100)}%；还允许累计充放{fmt(request.remaining_throughput_mwh)}兆瓦时。",
             f"充电效率{fmt(request.charge_efficiency*100)}%、放电效率{fmt(request.discharge_efficiency*100)}%，每兆瓦时累计充放计模拟损耗{fmt(request.degradation_cost_yuan_per_mwh_throughput)}元；这些都会影响价差是否值得做。"]
    if future:
        peak = max(future, key=lambda r: r.forecast_price_yuan_per_mwh)
        lines.append(f"当前预测价为{fmt(request.prices[0].forecast_price_yuan_per_mwh)}元/兆瓦时；后续预测最高价在{peak.interval_start:%H:%M}，为{fmt(peak.forecast_price_yuan_per_mwh)}元/兆瓦时。价格高低本身不能单独证明动作原因。")
    for item in comparisons:
        label = METHOD_ZH[item.method]
        if item.optimized_minus_plan.status == AmountStatus.EVALUATED:
            delta = item.optimized_minus_plan.value_yuan
            lines.append(f"相对“{label}”，综合计划按同样结束电量预计多{fmt(delta)}元。"
                         if not item.near_tie else f"与“{label}”的金额差别很小，可能存在同样合理的不同动作，不应宣称唯一最佳办法。")
        else:
            lines.append(f"“{label}”未取得可比较结果：{next(p.diagnostic_zh for p in computed if p.plan.method == item.method)}")
    observed = []
    after = row.stored_energy_after_mwh
    low, high = (request.energy_capacity_mwh*r for r in (request.min_soc_ratio, request.max_soc_ratio))
    if abs(after-low) <= ENERGY_TOL:
        observed.append("第一时段结束已接近最低留电量")
    if abs(after-high) <= ENERGY_TOL:
        observed.append("第一时段结束已接近最高可存电量")
    if row.remaining_throughput_mwh <= ENERGY_TOL:
        observed.append("第一时段已用完剩余充放额度")
    if power > 0:
        limit = request.charge_power_limit_mw if action == "充电" else request.discharge_power_limit_mw
        if power < limit-POWER_CLEANUP_TOL:
            lines.append("当前没有满功率运行；需要同时照顾后续机会、结束留电量和充放额度，不能仅凭一项限制断言唯一原因。")
            before=row.stored_energy_before_mwh
            forced_after = (before+request.charge_efficiency*limit*request.dt_hours if action=="充电"
                            else before-limit*request.dt_hours/request.discharge_efficiency)
            if forced_after>high+ENERGY_TOL or forced_after<low-ENERGY_TOL:
                lines.append(f"单看当前这一时段，若全速{action}{fmt(limit)}兆瓦，结束电量会到{fmt(forced_after/request.energy_capacity_mwh*100)}%，越过你设定的安全边界；所以本段不能这样满功率运行。")
    if observed:
        lines.append("复算观察到："+"；".join(observed)+"。这是限制状态，不是单独因果证明。")
    delta = best.evaluation.totals.inventory_delta_mwh
    if abs(delta) > ENERGY_TOL:
        lines.append(f"计划库存变化{fmt(delta)}兆瓦时；现金差额包含库存释放或补充的影响，不等于新创造的套利利润，期初库存成本未知。")
    lines.append("这是本次情景测算，不属于历史冻结研究结果；没有实际成交、执行或实际电价，不能作为企业最终利润或自动交易指令。")
    return ActionAdvice(True, action, power, tuple(lines), (code, "WHOLE_HORIZON_CONSTRAINED_OPTIMUM"))


@dataclass(frozen=True)
class StorageCalculation:
    output: StorageOutput
    computed_plans: tuple[ComputedPlan, ...]
    comparisons: tuple[Comparison, ...]
    advice: ActionAdvice
    engine_version: str = ENGINE_VERSION
    price_source: str = "user_supplied_scenario"
    historical_result: bool = False
    actual_execution_confirmed: bool = False


def calculate_storage(request, backend, *, run_id, computed_at_utc):
    request = validated_request(request)
    with localcontext() as context:
        context.prec = 50
        computed = tuple(compute_plan(request, method, backend) for method in METHODS)
        best = computed[0]
        comparisons = []
        for candidate in computed[1:]:
            if best.plan.status == candidate.plan.status == RunStatus.OPTIMAL:
                a, b = best.plan.contribution.value_yuan, candidate.plan.contribution.value_yuan
                tolerance = money_tolerance(a,b)
                require(a+ tolerance >= b, "综合计划不应劣于可行对照，结果比较未通过。")
                delta = a-b
                comparisons.append(Comparison(candidate.plan.method, candidate.plan.status, money(delta), abs(delta) <= tolerance))
            else:
                comparisons.append(Comparison(candidate.plan.method, candidate.plan.status, Amount(AmountStatus.NOT_EVALUABLE, None), False))
        status = best.plan.status
        metadata = ResultMetadata("storage", request.input_sha256, status, run_id, computed_at_utc,
                                  ("forecast_energy_cash", "simulated_degradation") if status == RunStatus.OPTIMAL else (),
                                  ("actual_contribution", "inventory_cost", "fees", "full_profit"))
        output = StorageOutput(metadata, tuple(c.plan for c in computed))
        return StorageCalculation(output, computed, tuple(comparisons), explain(request, computed, comparisons))


@dataclass(frozen=True)
class StressValuation:
    method: str
    original_input_sha256: str
    stress_input_sha256: str
    actions_sha256: str
    original_contribution: Amount
    stressed_contribution: Amount
    difference: Amount
    evaluation: ScheduleEvaluation
    reoptimized: bool = False
    price_source: str = "user_supplied_stress_scenario"
    label_zh: str = "原动作不变，仅按新价格重新估算收支；不是按新预测重新优化，也不是实际收益。"


def revalue_fixed_plan(request, computed_plan, stress_prices):
    request = validated_request(request)
    require(computed_plan.input_sha256 == request.input_sha256 and computed_plan.plan.status == RunStatus.OPTIMAL,
            "只能重估本次经过验证的原计划。")
    require(isinstance(stress_prices, (list, tuple)) and len(stress_prices) == len(request.prices), "压力价格必须完整覆盖原时段。")
    payload = request.editable_payload()
    payload["prices"] = [{**row, "forecast_price_yuan_per_mwh": p} for row,p in zip(payload["prices"], stress_prices)]
    stress = normalize_storage(payload)
    rows = computed_plan.plan.interval_rows
    evaluated = evaluate_schedule(stress, tuple(r.charge_power_mw for r in rows), tuple(r.discharge_power_mw for r in rows),
                                  method=computed_plan.plan.method)
    with localcontext() as context:
        context.prec = 50
        before, after = computed_plan.plan.contribution, evaluated.totals.forecast_contribution
        return StressValuation(computed_plan.plan.method, request.input_sha256, stress.input_sha256,
                               fingerprint([(r.interval_start,r.interval_end,r.charge_power_mw,r.discharge_power_mw) for r in rows]),
                               before, after, money(after.value_yuan-before.value_yuan), evaluated)
