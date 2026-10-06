from datetime import datetime, timezone
from decimal import Decimal as D
import unittest

from decision_core.contracts import (Amount, AmountStatus, ResultMetadata, RunStatus,
                                    StorageOutput, GenerationOutput, StoragePlan, canonical,
                                    GenerationCandidate, GenerationScenarioEvaluation)
from decision_core.errors import ContractError
from decision_core.presets import storage_quick, generation_quick, preset_record
from sandbox_display.zh import (BUSINESS_COLUMNS, field_spec, enum_zh, format_value, project_row,
                               missing_price_description, generation_tail_caption, STRATEGIES)
from tests.decision_sandbox.support import fixture, storage_input, generation_input


class HandGoldens(unittest.TestCase):
    """Independent fixed-action arithmetic; not calling either production engine."""
    def test_four_interval_energy_efficiency_and_cash(self):
        g = fixture("hand_goldens_v1.json")["storage_fixed_four_intervals"]
        dt, e = D(g["interval_minutes"]) / 60, D(g["initial_mwh"])
        charge, discharge, cost, revenue = D(0), D(0), D(0), D(0)
        boundaries = [e]
        for p, c, d in zip(g["prices"], g["charge_mw"], g["discharge_mw"]):
            p, c, d = D(p), D(c) * dt, D(d) * dt
            e += D(g["charge_efficiency"]) * c - d / D(g["discharge_efficiency"])
            charge += c
            discharge += d
            cost += p * c
            revenue += p * d
            boundaries.append(e)
        degradation = D(g["degradation"]) * (charge + discharge)
        self.assertEqual(boundaries, list(map(D, g["expected_energy_boundaries_mwh"])))
        for result, key in ((charge, "charge_mwh"), (discharge, "discharge_mwh"), (charge+discharge, "throughput_mwh"),
                            ((charge+discharge)/(2*D(g["capacity_mwh"])), "cycles"), (cost, "charge_cost_yuan"),
                            (revenue, "revenue_yuan"), (degradation, "degradation_yuan"), (revenue-cost-degradation, "contribution_yuan")):
            self.assertEqual(result, D(g["expected_" + key]))

    def test_delta_t_15_30_60_not_hours(self):
        for minutes, expected in ((15, "25"), (30, "50"), (60, "100")):
            self.assertEqual(D(100) * D(minutes) / 60, D(expected))

    def test_inventory_release_is_not_created_arbitrage(self):
        g = fixture("hand_goldens_v1.json")["storage_inventory_release"]
        delta = D(g["terminal_mwh"]) - D(g["initial_mwh"])
        output = -delta * D(g["discharge_efficiency"])
        contribution = output * (D(g["price"]) - D(g["degradation"]))
        self.assertEqual(delta, D(g["expected_inventory_delta_mwh"]))
        self.assertEqual(output, D(g["expected_grid_discharge_mwh"]))
        self.assertEqual(contribution, D(g["expected_contribution_yuan"]))
        self.assertIsNone(g["full_profit"])

    def test_all_generation_trades_market_mechanism_is_extra_difference(self):
        g = fixture("hand_goldens_v1.json")["generation_mechanism_and_fixed_contract"]
        q, r = D(g["q_base"]), D(g["mechanism_ratio"])
        c0, c1 = D(g["existing_mwh"]), D(g["new_mwh"])
        market = q * D(g["asset_price"])
        old = c0 * (D(g["existing_price"]) - D(g["delivery_price"]))
        new = c1 * (D(g["new_price"]) - D(g["delivery_price"]))
        mechanism = q * r * (D(g["mechanism_price"]) - D(g["reference_price"]))
        parts = [market, old, new, mechanism]
        self.assertEqual(parts, list(map(D, g["expected_base_components_yuan"])))
        self.assertEqual(sum(parts), D(g["expected_base_total_yuan"]))
        self.assertNotEqual(sum(parts), (q-q*r)*D(g["asset_price"])+q*r*D(g["mechanism_price"])+old+new+q*r*D(g["reference_price"]))

    def test_low_production_keeps_contracts_and_changes_mechanism(self):
        g = fixture("hand_goldens_v1.json")["generation_mechanism_and_fixed_contract"]
        q = D(g["q_low"])
        c0, c1 = D(g["existing_mwh"]), D(g["new_mwh"])
        m = q * D(g["mechanism_ratio"])
        self.assertEqual(c0+c1, D(g["expected_total_contract_mwh"]))
        self.assertEqual(m, D(g["expected_low_mechanism_mwh"]))
        for p, expected in ((D(300), "expected_low_total_yuan"), (D(500), "expected_low_high_price_total_yuan")):
            total = q*p+c0*(D(g["existing_price"])-p)+c1*(D(g["new_price"])-p)+m*(D(g["mechanism_price"])-p)
            self.assertEqual(total, D(g[expected]))

    def test_mechanism_cap_and_coverage_base(self):
        g = fixture("hand_goldens_v1.json")["generation_mechanism_and_fixed_contract"]
        q = D(g["q_base"])
        m = q*D(g["mechanism_ratio"])
        self.assertEqual(min(m, D(5000)), D(g["expected_capped_mechanism_mwh"]))
        self.assertEqual(q-m-D(g["existing_mwh"]), D(g["expected_base_remaining_commitment_mwh"]))

    def test_contract_difference_equals_locked_part_once(self):
        q, c, spot, locked = D(100), D(40), D(300), D(380)
        self.assertEqual(q*spot+c*(locked-spot), c*locked+(q-c)*spot)
        self.assertEqual(q*spot+c*(locked-spot), D(33200))


class MoneyAndOutputContracts(unittest.TestCase):
    def test_real_zero_evaluated(self):
        a = Amount(AmountStatus.EVALUATED, "0")
        self.assertEqual(a.value_yuan, 0)
        self.assertIn('"value_yuan":"0"', canonical(a))

    def test_unknown_not_applicable_and_not_evaluable_distinct(self):
        for status in (AmountStatus.UNKNOWN, AmountStatus.NOT_APPLICABLE, AmountStatus.NOT_EVALUABLE, AmountStatus.NOT_MODELLED):
            self.assertIsNone(Amount(status, None).value_yuan)
            with self.assertRaises(ContractError):
                Amount(status, "0")
        with self.assertRaises(ContractError):
            Amount(AmountStatus.EVALUATED, None)

    def test_s1_has_no_fake_calculated_outputs(self):
        a, b = storage_quick(storage_input()), generation_quick(generation_input())
        for case, request, output_type in (("storage", a, StorageOutput), ("generation", b, GenerationOutput)):
            meta = ResultMetadata(case, request.input_sha256, RunStatus.NOT_RUN, "s1-contract-example", None)
            output = output_type(meta)
            self.assertEqual(output.metadata.status, RunStatus.NOT_RUN)
            self.assertIsNone(output.metadata.full_profit.value_yuan)
            with self.assertRaises(ContractError):
                ResultMetadata(case, request.input_sha256, RunStatus.NOT_RUN, "fake-computed", datetime.now(timezone.utc))

    def test_failed_plan_cannot_have_zero_success_money(self):
        with self.assertRaises(ContractError):
            StoragePlan("optimized", RunStatus.INFEASIBLE, Amount(AmountStatus.EVALUATED, 0), False, False)
        with self.assertRaises(ContractError):
            StoragePlan("optimized", RunStatus.OPTIMAL, Amount(AmountStatus.EVALUATED, 1), False, True)

    def test_unsafe_run_identifier_rejected(self):
        a = storage_quick(storage_input())
        with self.assertRaises(ContractError):
            ResultMetadata("storage", a.input_sha256, RunStatus.NOT_RUN, "/some/local/path", None)

    def test_model_and_schema_versions_cannot_be_swapped(self):
        a = storage_quick(storage_input())
        meta = ResultMetadata("storage", a.input_sha256, RunStatus.NOT_RUN, "s1-example", None)
        self.assertEqual(meta.model_version, "storage-throughput-v1")
        with self.assertRaises(ContractError):
            ResultMetadata("storage", a.input_sha256, RunStatus.NOT_RUN, "s1-example", None, model_version="generation-month-aggregate-v1")

    def test_arbitrary_output_dict_rejected(self):
        with self.assertRaises(ContractError):
            StoragePlan("optimized", RunStatus.NOT_RUN, Amount(AmountStatus.NOT_EVALUABLE, None), False, False,
                        ({"unexpected_private_field": "value"},))

    def test_contract_quantity_cannot_change_in_output_scenarios(self):
        unknown = Amount(AmountStatus.NOT_EVALUABLE, None)
        a = GenerationScenarioEvaluation(0, D(100), D(40), D(50), unknown, unknown, unknown, unknown, unknown)
        b = GenerationScenarioEvaluation(1, D(80), D(32), D(40), unknown, unknown, unknown, unknown, unknown)
        with self.assertRaises(ContractError):
            GenerationCandidate(D(40), D("0.5"), False, (), unknown, unknown, scenario_rows=(a,b))

    def test_metadata_and_outputs_are_typed_not_arbitrary_payloads(self):
        a = storage_quick(storage_input())
        meta = ResultMetadata("storage", a.input_sha256, RunStatus.NOT_RUN, "s1-example", None)
        with self.assertRaises(ContractError):
            GenerationOutput(meta)
        with self.assertRaises(ContractError):
            StorageOutput(meta, plans=[])


class ChineseVocabulary(unittest.TestCase):
    def test_major_table_columns_all_have_chinese(self):
        for context, columns in BUSINESS_COLUMNS.items():
            for key in columns:
                spec = field_spec(context, key)
                self.assertTrue(any('\u4e00' <= c <= '\u9fff' for c in spec.label_zh))
                self.assertNotIn("_", spec.label_zh)

    def test_eight_storage_strategies_keep_actual_meaning(self):
        self.assertEqual(len([k for k in STRATEGIES if k[1:2] == "_"]), 8)
        self.assertIn("最近完整一天", STRATEGIES["C_lag_milp"])
        self.assertIn("不能执行", STRATEGIES["E_oracle_reference"])

    def test_private_internal_fields_not_default(self):
        row = {"date": "2025-09-02", "node_id": "RESEARCH_JIANGDONG", "pack": "counterfactual_2025",
               "status": "expected_blocked_DATA_ASOF_UNVERIFIED", "amount_yuan": None, "strict_profile_sha256": "hidden"}
        shown = project_row("a_strict", row)
        self.assertNotIn("hidden", str(shown))
        self.assertNotIn("sha256", str(shown))
        self.assertIn("无法验证", str(shown))

    def test_rows_48_does_not_mean_complete(self):
        lines = missing_price_description({"DA_complete": True, "DA_rows": 48, "RT_complete": False, "RT_rows": 48})
        self.assertIn("缺失", lines[1])
        self.assertIn("不等于", lines[2])

    def test_unknown_money_not_zero_real_zero_is_zero(self):
        self.assertEqual(format_value("a_summary", "simulated_contribution_yuan", None, status="not_evaluable"), "无法评价")
        self.assertEqual(format_value("a_summary", "simulated_contribution_yuan", "0"), "0.00 元")
        self.assertEqual(format_value("a_summary", "simulated_contribution_yuan", "-100"), "-100.00 元")

    def test_scientific_tail_label(self):
        text = generation_tail_caption("0.95")
        self.assertIn("5%", text)
        self.assertIn("平均", text)
        self.assertIn("不是最大", text)
        self.assertNotEqual(field_spec("a_risk", "cvar_yuan").label_zh, field_spec("b_score", "budget_shortfall_cvar").label_zh)

    def test_terminal_context_different(self):
        self.assertIn("当天", field_spec("asset", "terminal_soc_ratio").label_zh)
        self.assertIn("本次", field_spec("sandbox", "terminal_soc_ratio").label_zh)

    def test_unknown_enum_and_unmapped_field_not_raw_fallback(self):
        for fn in (lambda: enum_zh("random_status"), lambda: field_spec("a_summary", "new_field")):
            with self.assertRaises(ContractError):
                fn()

    def test_strict_check_does_not_invalidate_research_money(self):
        self.assertEqual(format_value("a_strict", "amount_yuan", None), "这条资格检查未评价金额")
        self.assertEqual(format_value("a_summary", "simulated_contribution_yuan", "123"), "123.00 元")

    def test_current_research_statuses_in_chinese(self):
        self.assertIn("研究", enum_zh("research_lag"))
        self.assertIn("不是真实", enum_zh("research_assumed_approved"))

    def test_preset_is_not_precomputed_answer(self):
        for case in ("storage", "generation"):
            r = preset_record(case)
            self.assertFalse(r["historical_result"])
            self.assertFalse(r["real_execution_certified"])
            self.assertTrue(r["requires_explicit_acceptance"])
