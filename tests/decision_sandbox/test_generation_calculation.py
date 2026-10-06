from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from decision_core.contracts import AmountStatus, RunStatus, canonical, primitive
from decision_core.errors import ContractError
from decision_core.generation import normalize_generation
from decision_core.generation_calculation import (calculate_generation, ENGINE_VERSION,
                                                 RANK_TOLERANCE_YUAN)
from decision_core.presets import generation_quick
from sandbox_compute.generation_runner import run_generation
from tests.decision_sandbox.support import ROOT, generation_input

D = Decimal


class GenerationCalculationTests(unittest.TestCase):
    def request(self, **changes):
        value = generation_quick(generation_input()).editable_payload()
        value.update(changes)
        return normalize_generation(value)

    def advanced(self, **changes):
        return self.request(mechanism={"mode":"ratio_assumed","ratio":"0.4",
            "cap_mode":"not_binding_assumed","remaining_cap_mwh":None,"price_yuan_per_mwh":"400"},
            mechanism_reference_prices={"low":"200","base":"300","high":"500"},
            price_linkage="all_same_assumed",existing_contract_price="360",custom_new_mwh="4000",**changes)

    def compute(self, request=None):
        return calculate_generation(request or self.request(),run_id="test-s3",computed_at_utc=datetime(2026,10,6,tzinfo=timezone.utc))

    def custom(self, result):
        return next(a for a in result.assessments if any(l.kind == "custom" for l in a.labels))

    def role(self, assessment, role):
        return next(r for r in assessment.scenarios if role in r.aliases)

    def test_original_hand_golden_exact_components(self):
        a = self.custom(self.compute(self.advanced()))
        row = self.role(a,("base","base")).evaluation
        gold = json.loads((ROOT/"sandbox_specs/hand_goldens_v1.json").read_text())["generation_mechanism_and_fixed_contract"]
        values = [row.market_energy,row.existing_contract_difference,row.new_contract_difference,row.mechanism_difference]
        self.assertEqual([v.value_yuan for v in values],list(map(D,gold["expected_base_components_yuan"])))
        self.assertEqual(row.evaluated_contribution.value_yuan,D(gold["expected_base_total_yuan"]))

    def test_original_golden_low_generation_and_high_price(self):
        a = self.custom(self.compute(self.advanced()))
        self.assertEqual(self.role(a,("low","base")).evaluation.evaluated_contribution.value_yuan,D("5880000"))
        self.assertEqual(self.role(a,("low","high")).evaluation.evaluated_contribution.value_yuan,D("6600000"))

    def test_mechanism_does_not_remove_market_energy(self):
        row = self.compute(self.advanced()).assessments[0].scenarios[0].evaluation
        self.assertEqual(row.net_energy_mwh,20000)
        self.assertEqual(row.market_energy.value_yuan,6000000)
        self.assertEqual(row.mechanism_energy_mwh,8000)
        self.assertEqual(row.mechanism_difference.value_yuan,800000)

    def test_declared_contract_quantity_is_fixed_all_scenarios(self):
        for a in self.compute(self.advanced()).assessments:
            self.assertEqual({r.evaluation.total_contract_mwh for r in a.scenarios},
                             {D(2000)+a.candidate.new_contract_mwh})

    def test_contract_difference_not_full_contract_income_twice(self):
        a = self.custom(self.compute(self.request(existing_contract_mwh="0",custom_new_mwh="4000")))
        for r in a.scenarios:
            e = r.evaluation
            p = self.request().asset_prices[("low","base","high").index(r.aliases[0][1])]
            self.assertEqual(e.evaluated_contribution.value_yuan,4000*D(380)+(e.net_energy_mwh-4000)*p)

    def test_existing_nonzero_retained_in_no_new_baseline(self):
        a = self.compute().assessments[0]
        self.assertEqual(a.candidate.new_contract_mwh,0)
        self.assertTrue(all(r.evaluation.total_contract_mwh == 2000 for r in a.scenarios))
        self.assertNotEqual(a.candidate.baseline_amount.value_yuan,6000000)

    def test_existing_and_new_prices_remain_different(self):
        row = self.custom(self.compute(self.advanced())).scenarios[0].evaluation
        self.assertEqual(row.existing_contract_difference.value_yuan,120000)
        self.assertEqual(row.new_contract_difference.value_yuan,320000)

    def test_no_existing_contract_can_have_unknown_price(self):
        a = self.compute(self.request(existing_contract_mwh="0",existing_contract_price=None)).assessments[0]
        self.assertEqual(a.scenarios[0].evaluation.existing_contract_difference.value_yuan,0)
        self.assertEqual(a.scenarios[0].evaluation.existing_contract_difference.status,AmountStatus.EVALUATED)

    def test_quick_advanced_complete_business_equivalence(self):
        quick = generation_quick(generation_input())
        advanced = normalize_generation(quick.editable_payload())
        self.assertEqual(self.compute(quick),self.compute(advanced))

    def test_default_five_choices_and_actual_mwh(self):
        out = self.compute()
        self.assertEqual([a.candidate.new_contract_mwh for a in out.assessments],[0,4500,9000,13500,18000])
        self.assertEqual(out.quantity_basis.new_available_mwh,18000)
        self.assertEqual(out.assessments[-1].new_share_of_total_forecast,D("0.9"))

    def test_mechanism_changes_candidate_basis_not_physical_market(self):
        out = self.compute(self.advanced())
        self.assertEqual(out.quantity_basis.new_available_mwh,10000)
        self.assertEqual([a.candidate.new_contract_mwh for a in out.assessments[:5]],[0,2500,5000,7500,10000])

    def test_mechanism_cap_changes_quantity_and_cash(self):
        value = self.advanced().editable_payload()
        value["mechanism"].update(cap_mode="known_remaining",remaining_cap_mwh="5000")
        out = self.compute(normalize_generation(value))
        self.assertEqual(out.quantity_basis.base_mechanism_mwh,5000)
        self.assertEqual(out.quantity_basis.new_available_mwh,13000)
        self.assertEqual(out.assessments[0].scenarios[0].evaluation.mechanism_difference.value_yuan,500000)
        self.assertTrue(out.assessments[0].scenarios[0].mechanism_cap_binding)

    def test_cap_zero_is_known_zero_not_missing_price(self):
        value = self.advanced().editable_payload()
        value["mechanism"].update(cap_mode="known_remaining",remaining_cap_mwh="0",price_yuan_per_mwh=None)
        value["mechanism_reference_prices"] = None
        value["price_linkage"] = "asset_delivery_same_assumed"
        out = self.compute(normalize_generation(value))
        self.assertIn("mechanism_difference",out.output.metadata.evaluated_components)
        self.assertTrue(all(r.evaluation.mechanism_difference.value_yuan == 0 for r in out.assessments[0].scenarios))

    def test_negative_mechanism_difference_kept(self):
        a = self.compute(self.advanced()).assessments[0]
        self.assertEqual(self.role(a,("base","high")).evaluation.mechanism_difference.value_yuan,-800000)

    def test_unknown_mechanism_quantity_blocks_candidates_but_keeps_market(self):
        request = self.request(mechanism={"mode":"unknown","ratio":None,"cap_mode":"unknown",
                              "remaining_cap_mwh":None,"price_yuan_per_mwh":None})
        out = self.compute(request)
        self.assertFalse(out.advice.available)
        self.assertEqual(out.output.metadata.status,RunStatus.UNRESOLVED)
        self.assertFalse(out.assessments)
        self.assertIsNone(out.quantity_basis.new_available_mwh)
        self.assertEqual(out.diagnostic_rows[0].evaluation.market_energy.value_yuan,6000000)
        self.assertIsNone(out.diagnostic_rows[0].evaluation.mechanism_difference.value_yuan)
        self.assertEqual(out.diagnostic_rows[0].evaluation.total_contract_mwh,2000)

    def test_unknown_mechanism_cap_not_unlimited(self):
        value = self.advanced().editable_payload()
        value["mechanism"].update(cap_mode="unknown")
        out = self.compute(normalize_generation(value))
        self.assertFalse(out.output.candidates)
        self.assertIsNone(out.quantity_basis.base_mechanism_mwh)

    def test_unknown_mechanism_price_excluded_from_common_ranking_not_zero(self):
        value = self.advanced().editable_payload()
        value["mechanism"]["price_yuan_per_mwh"] = None
        out = self.compute(normalize_generation(value))
        self.assertTrue(out.advice.available)
        for a in out.assessments:
            self.assertNotIn("mechanism_difference",a.candidate.evaluated_components)
            self.assertEqual(a.scenarios[0].evaluation.mechanism_difference.status,AmountStatus.UNKNOWN)
            self.assertIsNone(a.scenarios[0].evaluation.mechanism_difference.value_yuan)
            self.assertIn("MECHANISM_MONEY_UNKNOWN",a.candidate.reason_codes)

    def test_unknown_mechanism_reference_not_asset_price_fallback(self):
        value = self.advanced().editable_payload()
        value["price_linkage"] = "asset_delivery_same_assumed"
        value["mechanism_reference_prices"] = None
        out = self.compute(normalize_generation(value))
        self.assertNotIn("mechanism_difference",out.output.metadata.evaluated_components)
        self.assertIsNone(out.assessments[0].scenarios[0].evaluation.mechanism_difference.value_yuan)

    def test_common_components_same_for_every_candidate_and_row(self):
        for request in (self.request(),self.advanced()):
            out = self.compute(request)
            for a in out.assessments:
                self.assertEqual(a.candidate.evaluated_components,out.output.metadata.evaluated_components)
                for row in a.scenarios:
                    e = row.evaluation
                    total = sum(getattr(e,key).value_yuan for key in a.candidate.evaluated_components)
                    self.assertEqual(e.evaluated_contribution.value_yuan,total)

    def test_zero_low_generation_not_relabelled_unknown_mechanism(self):
        value = self.advanced().editable_payload()
        value["downside_ratio"] = "1"
        value["mechanism"]["price_yuan_per_mwh"] = None
        out = self.compute(normalize_generation(value))
        row = self.role(out.assessments[0],("low","base")).evaluation
        self.assertEqual(row.mechanism_difference.status,AmountStatus.EVALUATED)
        self.assertEqual(row.mechanism_difference.value_yuan,0)
        self.assertNotIn("mechanism_difference",out.assessments[0].candidate.evaluated_components)

    def test_not_applicable_has_null_amount_not_zero(self):
        e = self.compute().assessments[0].scenarios[0].evaluation
        self.assertEqual(e.mechanism_energy_mwh,0)
        self.assertEqual(e.mechanism_difference.status,AmountStatus.NOT_APPLICABLE)
        self.assertIsNone(e.mechanism_difference.value_yuan)

    def test_default_fulfillment_rejects_high_coverage_but_retains_cash(self):
        a = self.compute().assessments[4]
        self.assertFalse(a.candidate.recommendation_eligible)
        self.assertIn("MINIMUM_FULFILLMENT_EXCEEDED",a.candidate.reason_codes)
        self.assertEqual(self.role(a,("low","high")).fulfillment_shortfall_mwh,4000)
        self.assertEqual(a.candidate.minimum_scenario_amount.status,AmountStatus.EVALUATED)

    def test_100_percent_is_not_itself_policy_illegal(self):
        a = self.compute(self.request(downside_ratio="0")).assessments[4]
        self.assertTrue(a.candidate.recommendation_eligible)
        self.assertEqual(a.candidate.new_contract_mwh,18000)

    def test_disabling_fulfillment_returns_conditional_ranking(self):
        out = self.compute(self.request(enforce_minimum_fulfillment=False))
        self.assertTrue(out.assessments[4].candidate.recommendation_eligible)
        self.assertIn("SHORTFALL_CONDITIONAL",out.assessments[4].candidate.reason_codes)
        self.assertFalse(out.ranking_certifies_real_contract_eligibility)
        self.assertIsNone(out.assessments[4].scenarios[0].compensation.value_yuan)

    def test_existing_overcommitment_preserved_and_not_hidden(self):
        out = self.compute(self.request(existing_contract_mwh="30000"))
        self.assertEqual(out.quantity_basis.raw_remaining_commitment_mwh,-10000)
        self.assertEqual(out.quantity_basis.existing_overcommitment_mwh,10000)
        self.assertEqual(len(out.assessments),1)
        self.assertEqual(len(out.assessments[0].labels),5)
        self.assertEqual(out.assessments[0].scenarios[0].evaluation.total_contract_mwh,30000)
        self.assertFalse(out.advice.available)

    def test_existing_only_overcommitment_can_be_compared_when_constraint_off(self):
        out = self.compute(self.request(existing_contract_mwh="30000",enforce_minimum_fulfillment=False))
        self.assertTrue(out.advice.available)
        self.assertEqual(out.advice.new_contract_mwh,0)
        self.assertIn("EXISTING_OVERCOMMITMENT",out.assessments[0].candidate.reason_codes)

    def test_unknown_new_quota_blocks_recommendation_not_cash(self):
        out = self.compute(self.request(new_contract_limit={"mode":"unknown","remaining_mwh":None}))
        self.assertFalse(out.advice.available)
        self.assertTrue(all(a.candidate.baseline_amount.status == AmountStatus.EVALUATED for a in out.assessments))
        self.assertTrue(all("NEW_LIMIT_UNKNOWN" in a.candidate.reason_codes for a in out.assessments))

    def test_known_new_quota_does_not_clip_candidate(self):
        out = self.compute(self.request(new_contract_limit={"mode":"known_remaining","remaining_mwh":"5000"}))
        self.assertEqual(out.assessments[2].candidate.new_contract_mwh,9000)
        self.assertFalse(out.assessments[2].candidate.recommendation_eligible)
        self.assertTrue(out.assessments[1].candidate.recommendation_eligible)

    def test_zero_new_quota_still_allows_no_add(self):
        out = self.compute(self.request(new_contract_limit={"mode":"known_remaining","remaining_mwh":"0"}))
        self.assertEqual(out.advice.new_contract_mwh,0)
        self.assertTrue(out.assessments[0].candidate.recommendation_eligible)

    def test_custom_candidate_exceeds_basis_retained_not_clipped(self):
        a = self.custom(self.compute(self.request(custom_new_mwh="30000")))
        self.assertEqual(a.candidate.new_contract_mwh,30000)
        self.assertIsNone(a.candidate.coverage_ratio)
        self.assertFalse(a.candidate.recommendation_eligible)
        self.assertIn("NEW_EXCEEDS_BASE_REMAINDER",a.candidate.reason_codes)

    def test_custom_equal_existing_candidate_merges_labels(self):
        out = self.compute(self.request(custom_new_mwh="9000"))
        self.assertEqual(len(out.assessments),5)
        self.assertEqual({l.kind for l in out.assessments[2].labels},{"coverage","custom"})

    def test_full_mechanism_no_base_new_volume_still_has_five_aliases(self):
        value = self.advanced().editable_payload()
        value["mechanism"]["ratio"] = "1"
        value.update(existing_contract_mwh="0",custom_new_mwh=None)
        out = self.compute(normalize_generation(value))
        self.assertEqual(len(out.assessments),1)
        self.assertEqual(len(out.assessments[0].labels),5)
        self.assertEqual(out.quantity_basis.new_available_mwh,0)

    def test_six_and_nine_unique_scenarios(self):
        self.assertEqual(self.compute().unique_scenario_count,6)
        self.assertEqual(self.compute(self.request(upside_ratio="0.2")).unique_scenario_count,9)

    def test_duplicate_scenarios_and_card_aliases_are_kept(self):
        prices = {"low":"300","base":"300","high":"300"}
        out = self.compute(self.request(downside_ratio="0",asset_prices=prices,delivery_prices=prices))
        self.assertEqual(out.unique_scenario_count,1)
        for a in out.assessments:
            self.assertEqual({i for _,i,_ in a.cards},{0})
            self.assertEqual(len(a.cards),5)

    def test_low_generation_high_price_joint_min_not_single_factor_cards(self):
        prices = {"low":"200","base":"300","high":"1000"}
        out = self.compute(self.request(asset_prices=prices,delivery_prices=prices,enforce_minimum_fulfillment=False))
        a = out.assessments[4]
        self.assertEqual(a.candidate.minimum_scenario_amount.value_yuan,3600000)
        self.assertLess(a.candidate.minimum_scenario_amount.value_yuan,min(v.value_yuan for _,_,v in a.cards[:4]))
        self.assertIn(("low","high"),a.scenarios[a.worst_scenario_indices[0]].aliases)

    def test_neutral_robust_can_choose_different_with_real_tradeoff(self):
        prices = {"low":"200","base":"500","high":"700"}
        out = self.compute(self.request(asset_prices=prices,delivery_prices=prices))
        self.assertEqual(out.baseline_selection.candidate_index,0)
        self.assertEqual(out.robust_selection.candidate_index,3)
        self.assertEqual(out.advice.new_contract_mwh,13500)
        self.assertIn("正常情景金额差-1620000元", "".join(out.advice.explanation_zh))
        self.assertIn("最低情景金额差2430000元", "".join(out.advice.explanation_zh))

    def test_same_selection_genuine_zero_tradeoff(self):
        out = self.compute()
        self.assertEqual(out.baseline_selection.candidate_index,out.robust_selection.candidate_index)
        self.assertIn("取舍差额确实为0","".join(out.advice.explanation_zh))

    def test_every_nonselected_candidate_has_numeric_or_constraint_reason(self):
        out = self.compute()
        self.assertEqual(len(out.assessments[0].selection_notes_zh),2)
        self.assertIn("少2430000元",out.assessments[0].selection_notes_zh[1])
        self.assertIn("未纳入选择",out.assessments[4].selection_notes_zh[1])
        self.assertIn("选中",out.assessments[3].selection_notes_zh[1])

    def test_base_preference_uses_base_selection_not_robust(self):
        prices = {"low":"200","base":"500","high":"700"}
        out = self.compute(self.request(asset_prices=prices,delivery_prices=prices,risk_preference="base"))
        self.assertEqual(out.advice.new_contract_mwh,0)

    def test_equal_prices_contract_ties_choose_fewer_new(self):
        prices = {"low":"380","base":"380","high":"380"}
        out = self.compute(self.request(asset_prices=prices,delivery_prices=prices))
        self.assertEqual(out.advice.new_contract_mwh,0)
        self.assertGreater(len(out.robust_selection.near_tie_indices),1)
        self.assertEqual(RANK_TOLERANCE_YUAN,D("0.01"))

    def test_all_negative_scenario_cash_is_not_zeroed(self):
        prices = {"low":"-300","base":"-200","high":"-100"}
        out = self.compute(self.request(asset_prices=prices,delivery_prices=prices,new_contract_price="-150",
                                       existing_contract_price="-150"))
        self.assertTrue(any(a.candidate.baseline_amount.value_yuan < 0 for a in out.assessments))

    def test_separate_prices_basis_and_risk_not_forced_same(self):
        request = self.request(price_linkage="separate_assumed",delivery_prices={"low":"250","base":"350","high":"550"})
        row = self.compute(request).assessments[0].scenarios[0]
        self.assertEqual(row.asset_delivery_basis_yuan.value_yuan,-1000000)
        self.assertEqual(row.evaluation.existing_contract_difference.value_yuan,60000)
        self.assertIsNone(row.price_sensitivity_mwh)

    def test_all_linked_sensitivity_includes_mechanism(self):
        row = self.custom(self.compute(self.advanced())).scenarios[0]
        self.assertEqual(row.market_quantity_residual_mwh,14000)
        self.assertEqual(row.available_nonmechanism_mwh,12000)
        self.assertEqual(row.price_sensitivity_mwh,6000)

    def test_unknown_mechanism_sensitivity_is_only_evaluated_scope(self):
        value = self.advanced().editable_payload()
        value["mechanism"]["price_yuan_per_mwh"] = None
        row = self.custom(self.compute(normalize_generation(value))).scenarios[0]
        self.assertEqual(row.price_sensitivity_mwh,14000)
        self.assertIn("不含未知机制",row.sensitivity_scope_zh)

    def test_mechanism_reference_not_linked_no_unified_sensitivity(self):
        request = self.advanced().editable_payload()
        request["price_linkage"] = "asset_delivery_same_assumed"
        row = self.compute(normalize_generation(request)).assessments[0].scenarios[0]
        self.assertIsNone(row.price_sensitivity_mwh)

    def test_unmodelled_costs_environment_profit_stay_null(self):
        out = self.compute()
        self.assertEqual(out.output.metadata.full_profit.status,AmountStatus.NOT_MODELLED)
        self.assertIsNone(out.output.metadata.full_profit.value_yuan)
        self.assertIsNone(out.environment_value.value_yuan)
        self.assertIsNone(out.compensation.value_yuan)

    def test_dates_identity_and_research_flags_survive(self):
        out = self.compute(self.request(scenario_month="2025-09",subject_scenario="incremental_renewable_assumed"))
        self.assertEqual(out.rule_relation,"counterfactual_research")
        self.assertEqual(out.rule_reference_date,"2026-10-01")
        self.assertEqual(out.scenario_month,"2025-09")
        self.assertEqual(out.subject_scenario,"incremental_renewable_assumed")
        self.assertFalse(out.historical_result)
        self.assertFalse(out.actual_execution_confirmed)

    def test_chinese_explanations_no_internal_fields_and_accurate_scope(self):
        out = self.compute()
        prose = "".join(out.advice.explanation_zh)
        for name in ("amount_yuan","sha256","robust","maximin","CVaR","q_awarded"):
            self.assertNotIn(name,prose)
        self.assertIn("不是最大可能亏损",prose)
        self.assertIn("已有2000MWh",prose)
        self.assertIn("不是企业完整利润",prose)
        self.assertTrue(all(a.reasons_zh for a in out.assessments))

    def test_input_hash_version_utc_serialization(self):
        r = self.request()
        out = run_generation(r)
        self.assertEqual(out.output.metadata.input_sha256,r.input_sha256)
        self.assertEqual(out.engine_version,ENGINE_VERSION)
        self.assertEqual(out.output.metadata.core_version,"0.1.0-contracts")
        self.assertEqual(out.output.metadata.computed_at_utc.utcoffset().total_seconds(),0)
        self.assertNotIn("/Users",canonical(out))
        self.assertEqual(json.loads(canonical(out))["output"]["metadata"]["full_profit"]["value_yuan"],None)

    def test_reject_tampered_scenarios(self):
        r = self.request()
        bad = replace(r,scenarios=(replace(r.scenarios[0],net_mwh=D("1")),)+r.scenarios[1:])
        with self.assertRaises(ContractError):
            self.compute(bad)

    def test_money_addition_exact_even_decimal_inputs(self):
        out = self.compute(self.request(expected_net_mwh="12345.123456789123456789",downside_ratio="0.123456789123456789",
            new_contract_price="380.123456789123456789",existing_contract_price="350.123456789123456789"))
        for a in out.assessments:
            for row in a.scenarios:
                e = row.evaluation
                self.assertEqual(e.evaluated_contribution.value_yuan,sum(getattr(e,c).value_yuan for c in a.candidate.evaluated_components))

    def test_capacity_limits_and_full_generation_loss(self):
        out = self.compute(self.request(expected_net_mwh="100000000",existing_contract_mwh="0",downside_ratio="1"))
        self.assertTrue(out.assessments[0].candidate.recommendation_eligible)
        self.assertTrue(all(not a.candidate.recommendation_eligible for a in out.assessments[1:]))

    def test_very_small_finite_energy_preserves_zero_vs_unknown(self):
        out = self.compute(self.request(expected_net_mwh="0.000000000000000001",existing_contract_mwh="0",downside_ratio="0"))
        self.assertTrue(out.advice.available)
        self.assertEqual(out.output.candidates[0].baseline_amount.status,AmountStatus.EVALUATED)

    def test_two_parallel_requests_no_shared_results(self):
        a,b = self.request(),self.request(expected_net_mwh="30000")
        with ThreadPoolExecutor(max_workers=2) as pool:
            first,second = list(pool.map(run_generation,(a,b)))
        self.assertNotEqual(first.output.metadata.run_id,second.output.metadata.run_id)
        self.assertEqual(first.output.metadata.input_sha256,a.input_sha256)
        self.assertEqual(second.output.metadata.input_sha256,b.input_sha256)
        self.assertNotEqual(first.advice.new_contract_mwh,second.advice.new_contract_mwh)

    def test_clean_actual_generation_compute_without_sdk_private_io_or_network(self):
        with tempfile.TemporaryDirectory(prefix="sandbox-s3-clean-") as folder:
            clean = Path(folder)
            (clean/"decision_core").mkdir()
            for p in (ROOT/"decision_core").glob("*.py"):
                shutil.copyfile(p,clean/"decision_core"/p.name)
            (clean/"sandbox_compute").mkdir()
            for name in ("__init__.py","generation_runner.py"):
                shutil.copyfile(ROOT/"sandbox_compute"/name,clean/"sandbox_compute"/name)
            code = r'''
import sys,os,pathlib,json,uuid,dataclasses,decimal,datetime,enum,hashlib,re,socket
from unittest.mock import patch
root,value=sys.argv[1],json.loads(sys.argv[2])
sys.path[:]=[root]+[p for p in sys.path if p and "site-packages" not in p]
def deny(*a,**kw): raise AssertionError("private/network/environment access forbidden")
def audit(event,args):
    if event.startswith("socket."): deny()
    if event == "open" and (not isinstance(args[0],str) or not args[0].startswith(root+os.sep) or not args[0].endswith((".py",".pyc"))): deny()
sys.addaudithook(audit)
with patch("builtins.open",deny),patch("pathlib.Path.open",deny),patch("os.getenv",deny),patch.object(os,"environ",{}):
    from decision_core.presets import generation_quick
    from sandbox_compute.generation_runner import run_generation
    result=run_generation(generation_quick(value))
    assert result.advice.available and len(result.assessments)==5
    assert not any(m in sys.modules for m in ("pulp","highspy","numpy","pandas","src","presentation"))
    print("clean-generation-compute-pass")
'''
            run = subprocess.run([sys.executable,"-I","-B","-c",code,str(clean),json.dumps(generation_input())],
                                 cwd=clean,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn("clean-generation-compute-pass",run.stdout)


if __name__ == "__main__":
    unittest.main()
