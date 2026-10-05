"""Explicit publication schema. Unknown output fields are rejected, not displayed."""
from __future__ import annotations
import json
import math
import re
from pathlib import PurePosixPath

VERSION = 1
RELEASE = "public-20261005-v1"
FIELDS = {
    "meta": "schema_version release_id case scope data_domain sample_window rule_reference information_status execution_assumption component_coverage publication_scope full_profit_status original_g6_sha256".split(),
    "evidence": "source_id source_manifest_sha256 source_object_sha256 source_selector evidence_status".split(),
    "asset": "asset_id charge_efficiency discharge_efficiency degradation_cost_yuan_per_mwh_throughput energy_capacity_mwh initial_soc_ratio interval_minutes max_equivalent_full_cycles_per_day max_soc_ratio min_soc_ratio power_capacity_mw terminal_soc_ratio".split(),
    "a_summary": "market_date node_id strategy comparison_group da_amount_yuan rt_amount_yuan degradation_cost_yuan simulated_contribution_yuan evaluation_status reference_only executable real_execution_certified information_mode full_profit_yuan unmodelled_fees_status physical_constraints_passed original_commitment_sha256 original_plan_sha256 rule_context_sha256 evaluated_intervals unevaluable_intervals".split(),
    "a_context": "amount_status data_market_date execution_status information_status price_mapping_status resolved_rule_bundle_sha256 rule_reference_date run_context_sha256 schema_version".split(),
    "a_action": "interval_start interval_end timestamp interval_minutes action charge_power_mw discharge_power_mw net_injection_mw soc_before_ratio soc_after_ratio stored_energy_before_mwh stored_energy_after_mwh remaining_throughput_mwh used_throughput_mwh execution_plan_version execution_price_target future_actual_price_used terminal_comparable".split(),
    "a_explain": "timestamp strategy action charge_power_mw discharge_power_mw soc_before soc_after remaining_throughput_mwh forecast_asof future_actual_price_used prediction_target adopted_forecast_sha256 execution_sha256 rule_context_sha256 why_scope".split(),
    "a_event": "decision_asof current_energy_mwh used_throughput_mwh remaining_budget_mwh original_plan_sha256 original_commitment_sha256 forecast_sha256 proposal_sha256 actual_applied permission_status current_day_observed_intervals execution_interval_index mode status terminal_energy_mwh update_minutes".split(),
    "a_attribution": "RT_oracle_gap_yuan additional_rolling_yuan attribution_scope capture_scope contribution_delta_yuan da_delta_yuan degradation_delta_yuan remaining_adjustment_capture_reference rt_delta_yuan switch_to_RT_once_yuan".split(),
    "a_comparison": "annualized common_count expected_count group pack probe_only ranking_scope reference_only split strategy".split(),
    "a_risk": "alpha cvar_method cvar_yuan effective_tail_days max_drawdown_yuan mean_yuan median_yuan missing_count negative_days observed_negative_fraction p5_yuan risk_basis sample_count small_sample_warning status tail_warning var_method var_yuan worst_day_yuan".split(),
    "a_stress": "market_date node_id strategy stress_case scope comparison_status da_amount_yuan rt_amount_yuan degradation_cost_yuan simulated_contribution_yuan evaluated_intervals evaluation_status full_profit_yuan unevaluable_intervals unmodelled_fees_status".split(),
    "a_strict": "amount_yuan date node_id pack research_fallback status strict_profile_sha256".split(),
    "a_missing": "DA_complete DA_rows RT_complete RT_rows evaluation_status full_profit_yuan market_date node_id paired price_stage rule_profile_supported scope simulated_contribution_yuan status".split(),
    "b_identity": "asset_id capacity_mw province technology vintage vintage_status dispatch_class dispatch_status real_asset_mapping_status".split(),
    "b_rule": "mode reference_date scenario_month source_power_year source_price_year".split(),
    "qualification": "name value status note".split(),
    "b_decision": "asset_id budget_frozen_once budget_yuan decided_at expected_mechanism_outside_mwh full_profit_yuan information_status month reason remaining_green_quota_mwh scenario_count score_precision stage".split(),
    "b_candidate": "candidate_id coverage estimated_max_environment_shortfall_mwh feasible total_mwh chosen".split(),
    "b_score": "budget_shortfall_cvar expected_contribution expected_increment feasible objective".split(),
    "b_input": "interval_minutes interval_start q_forecast_mwh q_declared_mwh q_awarded_mwh q_executed_mwh q_net_mwh q_contract_mwh".split(),
    "b_line": "component period settlement_month amount_yuan raw_amount_yuan status qualification amount_scope formula_or_reason".split(),
    "b_coverage": "component complete_component_yuan evaluable evaluated_subtotal_yuan not_applicable rows unresolved".split(),
    "b_risk": "budget_basis budget_yuan confidence domain effective_sample_count effective_tail_count expected_contribution_yuan frequency sample_count shortfall_cvar_yuan tail_mass tail_support_count warning".split(),
    "b_chron": "frequency gap_policy max_contiguous_increment_drawdown_yuan monthly_fees_allocated_daily".split(),
    "b_chron_row": "date increment_yuan segment_cumulative_yuan segment_id".split(),
    "b_attribution": "difference_yuan ex_post_review_only full_profit_yuan monthly_not_repeated_daily status".split(),
    "b_component": "component difference_yuan".split(),
    "b_compare": "strategy common_mask_contribution_yuan complete_month full_profit_yuan ledger_sha256 status".split(),
    "b_reference": "best_candidate captured_space_ratio contribution_yuan executable not_written_back_to_decisions original_decision_sha256 ratio_reason scope status".split(),
    "b_ref_choice": "strategy candidate_id contribution_yuan ratio ratio_reason".split(),
    "b_unknown": "additional_unobserved_difference_for_tie_yuan formula full_profit_yuan ranking_certification risk_averse_minus_no_contract_known_yuan".split(),
    "b_monitor": "as_of day_remaining_forecast_net_mwh day_remaining_contract_mwh day_remaining_net_minus_contract_mwh day_financial_delivery_shortfall_proxy_mwh automatic_trade".split(),
    "b_submission": "market_date issued_at submitted_at capacity_mw structure_status".split(),
    "b_control": "strategy scope status difference_yuan evaluated_contribution_yuan common_mask_contribution_yuan label value_yuan channel days mean_daily_mae mean_daily_rmse method source_sha256".split(),
    "gf": "id topic assertion evidence_status applicability limits not_automatic_model_parameter".split(),
    "gf_ref": "source_id locator".split(),
}
# Every nested structure has a named schema. No arbitrary dict/list passthrough.
CHILDREN = {
    "storage_index": {"meta":"meta", "asset":"asset", "rows":["a_summary"], "comparisons":["a_comparison_full"], "stress":["a_stress"], "strict":["a_strict"], "missing_rt":["a_missing"], "evidence":["evidence"]},
    "a_comparison_full": {"record":"a_comparison", "risk":"a_risk"},
    "a_day": {"meta":"meta", "context":"a_context", "strategies":["a_strategy"], "evidence":["evidence"]},
    "a_strategy": {"summary":"a_summary", "actions":["a_action"], "original_plan":["a_action"], "events":["a_event"], "proposals":["a_proposal"], "explanations":["a_explain"], "attribution":"a_attribution", "evidence":["evidence"]},
    "a_proposal": {"actions":["a_action"]},
    "generation_index": {"meta":"meta", "groups":["b_group_index"], "rules":["gf_full"], "evidence":["evidence"]},
    "b_group_index": {},
    "gf_full": {"fact":"gf", "refs":["gf_ref"]},
    "b_group": {"meta":"meta", "identity":"b_identity", "rule_selection":"b_rule", "entitlements":["qualification"], "strategies":["b_strategy"], "comparison":["b_compare"], "stress":["b_stress"], "reference":"b_reference", "reference_choices":["b_ref_choice"], "unknown":"b_unknown", "evidence":["evidence"]},
    "b_strategy": {"decision":"b_decision", "candidates":["b_candidate_full"], "inputs":["b_input"], "lines":["b_line"], "coverage":["b_coverage"], "risk":"b_risk", "chronological":"b_chron", "chronological_rows":["b_chron_row"], "attribution":"b_attribution", "attribution_components":["b_component"], "monitor":["b_monitor"], "submissions":["b_submission_full"], "controls":["b_control"], "evidence":["evidence"]},
    "b_candidate_full": {"record":"b_candidate", "risk_score":"b_score", "neutral_score":"b_score"},
    "b_stress": {"rows":["b_compare"], "lines":["b_pressure_lines"]},
    "b_pressure_lines": {"rows":["b_line"]},
    "b_submission_full": {"record":"b_submission", "points":["b_forecast_point"]},
}
FIELDS.update({
    "storage_index": "schema_version case kind".split(),
    "a_day": "schema_version case kind node_id market_date".split(),
    "a_strategy": "strategy".split(), "a_proposal": ["proposal_sha256"],
    "generation_index": "schema_version case kind".split(),
    "b_group_index": "group sample_days complete_month data_domain".split(),
    "b_group": "schema_version case kind group sample_days complete_month private_details_omitted".split(),
    "b_strategy": "strategy sample_days complete_month evaluated_contribution_yuan details_available private_details_omitted".split(),
    "b_candidate_full": ["infeasible_reasons"],
    "b_stress": "case strategy_reselected not_official_stress_parameters".split(),
    "b_pressure_lines": ["strategy"],
    "b_forecast_point": "index forecast_mw declared_mwh".split(),
})
LIST_SCALARS = {("b_candidate_full","infeasible_reasons")}
MANDATORY = {
    "meta": set(FIELDS["meta"]),
    "storage_index": {"schema_version","case","kind","meta","asset","rows","comparisons","stress","strict","missing_rt","evidence"},
    "generation_index": {"schema_version","case","kind","meta","groups","rules","evidence"},
    "a_day": {"schema_version","case","kind","node_id","market_date","meta","context","strategies","evidence"},
    "a_strategy": {"strategy","summary","actions","original_plan","events","proposals","explanations","attribution","evidence"},
    "b_group": {"schema_version","case","kind","group","meta","identity","rule_selection","entitlements","strategies","comparison","stress","reference","reference_choices","unknown","evidence","sample_days","complete_month","private_details_omitted"},
}
SENSITIVE = re.compile(r"(?:/Users/|/home/|/private/var/|/var/folders/|[A-Za-z]:\\|file://|data/private/|MessageTemp/|BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{24,}|(?:access_token|api_key|password|cookie)\s*[=:]\s*[^\s,;}]{8,})",re.I)
FORBIDDEN_KEYS = {"p_da_yuan_per_mwh","p_rt_yuan_per_mwh","p_da_asset","p_rt_asset","p_da_delivery","source_refs","input_refs","inputs_raw","state_facts","power","nwp","source_path","absolute_path","received_cookie"}

class PublicDataError(ValueError):
    """Short diagnostics contain no source payload, credential or local path."""

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)

def scalar(value):
    if value is not None and not isinstance(value,(str,bool,int,float)):
        raise PublicDataError("公开字段不是许可标量")
    if isinstance(value,float) and not math.isfinite(value):raise PublicDataError("非有限数值")
    if isinstance(value,str) and (len(value)>8000 or SENSITIVE.search(value)):
        raise PublicDataError("公开文本安全检查未通过")

def validate(value,kind):
    if kind not in FIELDS and kind not in CHILDREN:raise PublicDataError("未登记的公开类型")
    if not isinstance(value,dict):raise PublicDataError("公开对象结构不匹配")
    fields=set(FIELDS.get(kind,[]));children=CHILDREN.get(kind,{})
    if set(value)-fields-set(children):raise PublicDataError("未知字段禁止公开")
    if not MANDATORY.get(kind,set()).issubset(value):raise PublicDataError("公开必填字段缺失")
    for key,item in value.items():
        if key in FORBIDDEN_KEYS or SENSITIVE.search(key):raise PublicDataError("禁止的公开字段")
        if key in children:
            child=children[key]
            if isinstance(child,list):
                if not isinstance(item,list) or len(item)>20000:raise PublicDataError("公开列表越界")
                for row in item:validate(row,child[0])
            else:validate(item,child)
        elif (kind,key) in LIST_SCALARS:
            if not isinstance(item,list) or len(item)>40:raise PublicDataError("公开原因列表无效")
            for row in item:scalar(row)
        else:scalar(item)
    if kind=="meta":
        if value["schema_version"]!=VERSION or value["release_id"]!=RELEASE:
            raise PublicDataError("公开版本不匹配")
        if value["full_profit_status"]!="not_modelled":raise PublicDataError("完整利润边界改变")
    if kind=="b_group" and value.get("group")!="synthetic_2026-08":
        if value.get("private_details_omitted") is not True:raise PublicDataError("私有分支范围标记缺失")
        for strategy in value.get("strategies",[]):
            if strategy.get("details_available") or any(strategy.get(k) for k in ("inputs","monitor","submissions")):
                raise PublicDataError("私有分时输入禁止公开")
            if any(r.get("period")!=strategy["decision"]["month"] for r in strategy.get("lines",[])):
                raise PublicDataError("私有分时账务禁止公开")
        if any(case.get("lines") for case in value.get("stress",[])):
            raise PublicDataError("私有压力明细禁止公开")

def relative_name(name):
    if not isinstance(name,str) or "\\" in name:raise PublicDataError("工件路径格式无效")
    p=PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts:raise PublicDataError("工件路径越界")
    return p
