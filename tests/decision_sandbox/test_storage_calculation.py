from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import unittest
from unittest.mock import patch

from decision_core.contracts import AmountStatus, RunStatus, canonical
from decision_core.errors import ContractError
from decision_core.presets import storage_quick
from decision_core.storage import normalize_storage
from decision_core.storage_calculation import (RawSolution, SolverReport, calculate_storage, evaluate_schedule,
                                               revalue_fixed_plan, ENERGY_TOL, money_tolerance, milp_problem)
from sandbox_compute.highs_adapter import highs_backend
from tests.decision_sandbox.support import fixture, storage_input

AT = datetime(2026,10,6,tzinfo=timezone.utc)


def request(prices=(100, 600), minutes=60, **changes):
    base = storage_quick(storage_input()).editable_payload()
    start = datetime(2026,10,6,0,tzinfo=timezone(timedelta(hours=8)))
    base.update(interval_minutes=minutes, energy_capacity_mwh="200", charge_power_limit_mw="100",
                discharge_power_limit_mw="100", current_soc_ratio="0.5", terminal_soc_ratio="0.5",
                budget={"mode":"remaining", "remaining_cycles":"1"}, wait_until=None)
    base["prices"] = [{"interval_start":(start+timedelta(minutes=i*minutes)).isoformat(),
                       "interval_end":(start+timedelta(minutes=(i+1)*minutes)).isoformat(),
                       "forecast_price_yuan_per_mwh":str(p)} for i,p in enumerate(prices)]
    base.update(changes)
    return normalize_storage(base)


def solve(r, backend=highs_backend):
    return calculate_storage(r, backend, run_id="synthetic-s2-test", computed_at_utc=AT)


class FixedActionChecks(unittest.TestCase):
    def test_hand_golden_is_replayed_by_new_arithmetic(self):
        g = fixture("hand_goldens_v1.json")["storage_fixed_four_intervals"]
        r = request(g["prices"], 15)
        out = evaluate_schedule(r,g["charge_mw"],g["discharge_mw"])
        self.assertEqual(out.totals.forecast_contribution.value_yuan,D(g["expected_contribution_yuan"]))
        self.assertEqual(out.totals.throughput_mwh,D(g["expected_throughput_mwh"]))
        self.assertEqual([out.interval_rows[0].stored_energy_before_mwh]+[v.stored_energy_after_mwh for v in out.interval_rows],
                         list(map(D,g["expected_energy_boundaries_mwh"])))

    def test_mw_to_mwh_15_30_60(self):
        for minute, expected in ((15,D(25)),(30,D(50)),(60,D(100))):
            r = request((100,600),minute,charge_efficiency="1",discharge_efficiency="1", min_soc_ratio="0",max_soc_ratio="1")
            out = evaluate_schedule(r,(100,0),(0,100))
            self.assertEqual(out.totals.charge_energy_mwh,expected)
            self.assertEqual(out.totals.discharge_energy_mwh,expected)
            self.assertEqual(out.totals.forecast_contribution.value_yuan,(D(500)-60)*expected)

    def test_inventory_cash_not_arbitrage_or_actual_profit(self):
        r = request((500,),current_soc_ratio="0.63", terminal_soc_ratio="0.5")
        ev = evaluate_schedule(r,(0,), ("24.7",))
        self.assertEqual(ev.totals.forecast_contribution.value_yuan,11609)
        self.assertEqual(ev.totals.inventory_delta_mwh,-26)
        self.assertEqual(ev.totals.actual_contribution.status,AmountStatus.NOT_EVALUABLE)
        self.assertEqual(ev.totals.inventory_cost.status,AmountStatus.UNKNOWN)

    def test_invalid_actions_not_repaired(self):
        r = request()
        for c,d in (((10,0),(1,0)), ((101,0),(0,1)), ((-1,0),(0,0)), ((0,0),(100,0)), ((0,),(0,)),
                    (("NaN",0),(0,0)), ((0,0),(0,0))):
            with self.subTest(c=c,d=d),self.assertRaises(ContractError):
                # Last all-zero case has an intentionally different terminal target.
                target = replace(r,terminal_soc_ratio=D("0.6")) if c==d==(0,0) else r
                evaluate_schedule(target,c,d)

    def test_budget_violation(self):
        r = request((100,600),charge_efficiency="1",discharge_efficiency="1",
                    budget={"mode":"remaining","remaining_cycles":"0.1"})
        with self.assertRaises(ContractError):
            evaluate_schedule(r,(50,0),(0,50))

    def test_material_solver_state_error(self):
        r = request((100,600),charge_efficiency="1",discharge_efficiency="1")
        with self.assertRaises(ContractError):
            evaluate_schedule(r,(10,0),(0,10),solver_states=(100,120,100))
        with self.assertRaises(ContractError):
            evaluate_schedule(r,(10,0),(0,10),modes=("0.5",0))

    def test_tiny_bound_roundoff_is_recorded_not_hidden(self):
        r = request((100,600),charge_efficiency="1",discharge_efficiency="1",min_soc_ratio="0",max_soc_ratio="1")
        ev = evaluate_schedule(r,("100.000000001",0),(0,100))
        self.assertEqual(ev.check.maximum_power_cleanup_mw,D("0.000000001"))
        with self.assertRaises(ContractError):
            evaluate_schedule(r,("100.0001",0),(0,100))


class SolverAndComparison(unittest.TestCase):
    def test_maximization_objective_matches_business_cash_sign(self):
        r=request()
        raw=highs_backend(milp_problem(r,"optimized"))
        self.assertGreater(D(raw.report.objective_yuan),0)
        ev=evaluate_schedule(r,raw.charge_mw,raw.discharge_mw,solver_states=raw.energy_mwh,modes=raw.mode)
        self.assertAlmostEqual(D(raw.report.objective_yuan),ev.totals.forecast_contribution.value_yuan,places=6)

    def test_low_high_arbitrage_and_all_row_sums(self):
        out = solve(request())
        self.assertEqual(out.output.metadata.status,RunStatus.OPTIMAL)
        p=out.computed_plans[0]
        self.assertGreater(p.plan.contribution.value_yuan,0)
        self.assertEqual(sum(r.contribution.value_yuan for r in p.plan.interval_rows),p.plan.contribution.value_yuan)
        self.assertLessEqual(p.evaluation.check.terminal_error_mwh,ENERGY_TOL)
        self.assertTrue(all(not(r.charge_power_mw>0 and r.discharge_power_mw>0) for r in p.plan.interval_rows))
        self.assertEqual(p.solver_report.raw_status,"kOptimal")
        self.assertIsNone(out.output.metadata.full_profit.value_yuan)

    def test_actual_solver_uses_interval_length(self):
        for minute, expected in ((15,D(25)),(30,D(50)),(60,D(100))):
            out=solve(request((100,600),minute,charge_efficiency="1",discharge_efficiency="1",min_soc_ratio="0",max_soc_ratio="1"))
            self.assertAlmostEqual(out.computed_plans[0].evaluation.totals.charge_energy_mwh,expected,places=6)

    def test_efficiency_and_degradation_can_remove_opportunity(self):
        for prices in ((300,310),(300,350)):
            out=solve(request(prices))
            self.assertEqual(out.output.metadata.status,RunStatus.OPTIMAL)
            self.assertEqual(out.computed_plans[0].plan.contribution.value_yuan,0)

    def test_negative_prices_and_mutual_exclusion(self):
        out=solve(request((-300,-20,600)))
        self.assertEqual(out.output.metadata.status,RunStatus.OPTIMAL)
        self.assertGreater(out.computed_plans[0].plan.contribution.value_yuan,0)
        self.assertEqual(out.advice.action_zh,"充电")
        self.assertLess(out.computed_plans[0].evaluation.totals.charge_cost.value_yuan,0)

    def test_zero_remaining_budget_real_zero(self):
        out=solve(request(budget={"mode":"remaining","remaining_cycles":"0"}))
        self.assertEqual(out.output.metadata.status,RunStatus.OPTIMAL)
        self.assertEqual(out.computed_plans[0].plan.contribution.value_yuan,0)
        self.assertEqual(out.advice.action_zh,"等待")

    def test_constant_zero_objective_is_still_verified_not_missing(self):
        out=solve(request((0,0),degradation_cost_yuan_per_mwh_throughput="0"))
        self.assertEqual(out.output.metadata.status,RunStatus.OPTIMAL)
        self.assertEqual(out.computed_plans[0].plan.contribution.value_yuan,0)

    def test_numerical_limits_do_not_silently_become_zero(self):
        for cap,power in (("0.001","0.001"),("100000","10000")):
            out=solve(request((-1000000,1000000),energy_capacity_mwh=cap,
                              charge_power_limit_mw=power,discharge_power_limit_mw=power))
            self.assertEqual(out.output.metadata.status,RunStatus.OPTIMAL)
            self.assertGreater(out.computed_plans[0].plan.contribution.value_yuan,0)

    def test_small_parameter_sweep_has_verified_physics(self):
        for efficiency in ("1","0.95","0.5","0.01"):
            for cap,power in (("1","1"),("200","100")):
                r=request((-300,50,600,400),15,energy_capacity_mwh=cap,
                          charge_power_limit_mw=power,discharge_power_limit_mw=power,
                          charge_efficiency=efficiency,discharge_efficiency=efficiency)
                out=solve(r)
                self.assertEqual(out.output.metadata.status,RunStatus.OPTIMAL)
                ev=out.computed_plans[0].evaluation
                self.assertLessEqual(ev.check.maximum_balance_residual_mwh,ENERGY_TOL)
                self.assertLessEqual(ev.check.terminal_error_mwh,ENERGY_TOL)

    def test_safe_full_charge_counterfactual_is_explained_not_invented_cause(self):
        base=storage_quick(storage_input()).editable_payload()
        base.update(current_soc_ratio="0.63",terminal_soc_ratio="0.5")
        out=solve(normalize_storage(base))
        text=" ".join(out.advice.explanation_zh)
        self.assertIn("110.5%",text)
        self.assertIn("56.84兆瓦",text)
        self.assertIn("不能单独",text)
        self.assertNotIn("56.842105",text)

    def test_changed_state_keeps_used_budget_and_new_remaining_window(self):
        r=storage_quick(storage_input()); original=solve(r)
        new=r.editable_payload()
        new["prices"]=new["prices"][3:]
        new["current_soc_ratio"]="0.75"
        new["budget"]={"mode":"total_minus_used","total_cycles":"1","used_cycles":"0.8"}
        new["wait_until"]=None
        changed=normalize_storage(new); out=solve(changed)
        self.assertEqual(changed.remaining_throughput_mwh,80)
        self.assertNotEqual(out.output.metadata.input_sha256,original.output.metadata.input_sha256)
        self.assertEqual(out.computed_plans[0].plan.status,RunStatus.OPTIMAL)
        self.assertLessEqual(out.computed_plans[0].evaluation.check.total_throughput_mwh,D(80)+ENERGY_TOL)

    def test_zero_remaining_different_target_infeasible(self):
        out=solve(request(budget={"mode":"remaining","remaining_cycles":"0"},terminal_soc_ratio="0.6"))
        self.assertEqual(out.output.metadata.status,RunStatus.INFEASIBLE)
        self.assertFalse(out.advice.available)
        self.assertIsNone(out.computed_plans[0].plan.contribution.value_yuan)

    def test_equal_direct_and_total_minus_used(self):
        r = storage_quick(storage_input())
        payload=r.editable_payload()
        payload["budget"]={"mode":"total_minus_used","total_cycles":"1","used_cycles":"0.4"}
        other=normalize_storage(payload)
        a,b=solve(r),solve(other)
        self.assertEqual(a.output.metadata.input_sha256,b.output.metadata.input_sha256)
        self.assertAlmostEqual(a.computed_plans[0].plan.contribution.value_yuan,b.computed_plans[0].plan.contribution.value_yuan,places=6)

    def test_user_six_intervals_63_to_50(self):
        base=storage_quick(storage_input()).editable_payload()
        base.update(current_soc_ratio="0.63",terminal_soc_ratio="0.5",
                    budget={"mode":"total_minus_used","total_cycles":"1","used_cycles":"0.4"})
        r=normalize_storage(base)
        out=solve(r)
        self.assertEqual(out.output.metadata.status,RunStatus.OPTIMAL)
        self.assertEqual(r.prices[-1].interval_end.hour,23)
        self.assertAlmostEqual(out.computed_plans[0].evaluation.totals.inventory_delta_mwh,D(-26),places=6)
        self.assertIn("库存",str(out.advice.explanation_zh))
        for p in out.computed_plans:
            self.assertEqual(p.plan.status,RunStatus.OPTIMAL)
            self.assertAlmostEqual(p.plan.interval_rows[-1].stored_energy_after_mwh,D(100),places=6)
        self.assertEqual(out.computed_plans[1].plan.interval_rows[0].discharge_power_mw,100)
        for row in out.computed_plans[2].plan.interval_rows:
            if row.interval_start < r.wait_until:
                self.assertEqual(row.charge_power_mw+row.discharge_power_mw,0)
        self.assertTrue(all(c.optimized_minus_plan.value_yuan>=-money_tolerance(out.computed_plans[0].plan.contribution.value_yuan)
                            for c in out.comparisons))

    def test_full_discharge_means_full_not_clipped(self):
        out=solve(request(current_soc_ratio="0.11", terminal_soc_ratio="0.11"))
        full=out.computed_plans[1]
        self.assertEqual(full.plan.status,RunStatus.INFEASIBLE)
        self.assertFalse(full.plan.interval_rows)
        self.assertIsNone(full.plan.contribution.value_yuan)

    def test_wait_time_is_user_chosen_even_at_end(self):
        r=request()
        payload=r.editable_payload()
        payload["wait_until"]=r.prices[-1].interval_end.isoformat()
        out=solve(normalize_storage(payload))
        wait=out.computed_plans[2]
        self.assertEqual(wait.plan.status,RunStatus.OPTIMAL)
        self.assertEqual(wait.plan.contribution.value_yuan,0)
        self.assertTrue(all(v.charge_power_mw==v.discharge_power_mw==0 for v in wait.plan.interval_rows))

    def test_same_conditions_quick_and_advanced(self):
        a=storage_quick(storage_input()); b=normalize_storage(a.editable_payload())
        self.assertEqual(a.input_sha256,b.input_sha256)
        left,right=solve(a),solve(b)
        self.assertEqual(left.output.metadata.status,RunStatus.OPTIMAL)
        self.assertEqual(right.output.metadata.status,RunStatus.OPTIMAL)
        self.assertEqual(left.computed_plans[0].plan.contribution,right.computed_plans[0].plan.contribution)

    def test_near_tie_does_not_invent_unique_best_action(self):
        r=request((400,400),charge_efficiency="1",discharge_efficiency="1",min_soc_ratio="0",max_soc_ratio="1",
                  degradation_cost_yuan_per_mwh_throughput="0",wait_until="2026-10-06T01:00:00+08:00")
        out=solve(r)
        self.assertTrue(all(v.near_tie for v in out.comparisons))
        self.assertIn("差别很小",str(out.advice.explanation_zh))

    def test_96_intervals(self):
        r=request(tuple(100 if i<48 else 600 for i in range(96)),15)
        out=solve(r)
        self.assertEqual(out.output.metadata.status,RunStatus.OPTIMAL)
        self.assertEqual(len(out.computed_plans[0].plan.interval_rows),96)

    def test_fixed_plan_pressure_does_not_reoptimize(self):
        r=storage_quick(storage_input()); out=solve(r); p=out.computed_plans[0]
        before=canonical(p)
        with patch("sandbox_compute.highs_adapter.highs_backend",side_effect=AssertionError("must not solve")):
            stress=revalue_fixed_plan(r,p,["380","420","500","200","200","400"])
        self.assertFalse(stress.reoptimized)
        self.assertEqual(canonical(p),before)
        self.assertEqual([(v.charge_power_mw,v.discharge_power_mw) for v in stress.evaluation.interval_rows],
                         [(v.charge_power_mw,v.discharge_power_mw) for v in p.plan.interval_rows])
        self.assertLess(stress.stressed_contribution.value_yuan,stress.original_contribution.value_yuan)
        self.assertEqual(stress.evaluation.totals.actual_contribution.status,AmountStatus.NOT_EVALUABLE)

    def test_each_interval_has_chinese_decision_log_not_future_actual_price(self):
        out=solve(storage_quick(storage_input()))
        for p in out.computed_plans:
            self.assertEqual(len(p.decision_log),len(p.plan.interval_rows))
            for log,row in zip(p.decision_log,p.plan.interval_rows):
                self.assertEqual(log.interval_start,row.interval_start)
                self.assertIn(log.action_zh,("充电","放电","等待"))
                self.assertIn("预测价",log.reason_zh)
                self.assertNotIn("_",log.reason_zh)
                self.assertNotIn("未来真实",log.reason_zh)

    def test_revaluation_wrong_input_or_missing_price_blocked(self):
        r=request(); p=solve(r).computed_plans[0]
        with self.assertRaises(ContractError): revalue_fixed_plan(request((200,500)),p,(200,300))
        with self.assertRaises(ContractError): revalue_fixed_plan(r,p,(200,None))


class FailureStatusAndProof(unittest.TestCase):
    def test_time_limit_incumbent_not_optimal_or_zero(self):
        def backend(problem):
            return RawSolution(SolverReport(RunStatus.TIME_LIMIT,"kTimeLimit"), (0,0),(0,0),(100,100,100),(0,0))
        out=solve(request(),backend)
        self.assertFalse(out.advice.available)
        self.assertEqual(out.output.metadata.status,RunStatus.TIME_LIMIT)
        self.assertTrue(all(p.plan.contribution.value_yuan is None for p in out.computed_plans))

    def test_false_optimal_wrapper_label_is_rejected(self):
        out=solve(request(),lambda _:RawSolution(SolverReport(RunStatus.OPTIMAL,"kTimeLimit",True,"0","0")))
        self.assertEqual(out.output.metadata.status,RunStatus.SOLVER_ERROR)
        self.assertFalse(out.advice.available)

    def test_nan_missing_variables_and_corrupt_states_rejected(self):
        for c,e,gap in ((("NaN",0),(100,100,100),"0"),((0,0),(100,110,100),"0"),((0,0),(100,100,100),None),
                        ((0,0),(100,100,100),"NaN")):
            def backend(_): return RawSolution(SolverReport(RunStatus.OPTIMAL,"kOptimal",True,"0",gap),c,(0,0),e,(0,0))
            out=solve(request(),backend)
            self.assertEqual(out.output.metadata.status,RunStatus.SOLVER_ERROR)
            self.assertFalse(out.advice.available)

    def test_missing_wait_does_not_choose_peak_for_user(self):
        out=solve(request())
        self.assertEqual(out.computed_plans[2].plan.status,RunStatus.UNRESOLVED)
        self.assertIsNone(out.computed_plans[2].plan.contribution.value_yuan)

    def test_tampered_budget_request_rejected(self):
        r=replace(request(),remaining_throughput_mwh=D(999))
        with self.assertRaises(ContractError): solve(r)


if __name__ == "__main__":
    unittest.main()
