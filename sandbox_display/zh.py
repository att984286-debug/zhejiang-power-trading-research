"""Context-aware whitelist. Raw dictionaries / unknown enums never auto-display."""
from dataclasses import dataclass
from decimal import Decimal

from decision_core.errors import ContractError, ErrorCode, require
from decision_core.numbers import decimal_text, number


@dataclass(frozen=True)
class FieldSpec:
    label_zh: str
    kind: str = "text"
    unit_zh: str = ""
    help_zh: str = ""
    layer: str = "business"


STRATEGIES = {
    "A_no_operation": "不充不放，作为对照",
    "B_forecast_threshold": "根据预测价，低时充电、高时放电",
    "C_lag_milp": "用最近完整一天的价格作参考，再安排充放电",
    "C_ridge_milp": "用历史规律预测价格，再优化充放电",
    "D_rolling_rt": "运行中多次更新剩余充放计划（研究模拟）",
    "S_static_once_rt": "运行中只更新一次剩余充放计划（研究模拟）",
    "E_oracle_reference": "假如提前知道真实日前价格（仅事后参照，不能执行）",
    "F_rt_oracle_remaining_reference": "假如提前知道后续真实实时价格（仅事后参照，不能执行）",
    "no_contract": "原研究不签合同的对照",
    "fixed": "按原研究固定比例签约",
    "risk_neutral": "优先提高原模型内的预计贡献",
    "risk_averse": "优先降低原模型内的目标缺口",
}
NODES = {
    "RESEARCH_JIANGDONG": "江东热电（主案例价格环境）",
    "RESEARCH_BAIYI": "百益站一号机组（价格环境）",
    "RESEARCH_LANXI": "兰溪厂一号机组（价格环境）",
    "RESEARCH_YUHUAN": "玉环厂一号机组（价格环境）",
}
STATES = {
    "research": "明确假设下的研究情景", "strict": "严格历史信息资格检查",
    "counterfactual_2025": "参考较新规则的2025反事实研究",
    "august_2026": "2026年8月少量样本框架验证",
    "expected_blocked_DATA_ASOF_UNVERIFIED": "无法验证当时是否已经收到数据",
    "unknown": "暂缺依据", "unresolved": "尚未确认", "not_evaluable": "无法评价",
    "not_evaluable_missing_RT": "缺少完整实时价格，无法评价收益",
    "not_applicable": "不适用", "not_modelled": "本版未计算", "not_run": "尚未运行测算",
    "evaluable": "可以评价指定分项", "evaluated": "已评价指定分项",
    "DA_only_not_full_day_evaluation": "只有日前价格，不能评价整天收益",
    "optimal": "已证明本模型下最优", "infeasible": "这些条件无法同时满足",
    "time_limit": "计算限时，尚未证明最优", "solver_error": "求解未完成，请调整条件后再试",
    "input_invalid": "输入条件不合法", "busy": "当前计算繁忙，请稍后再试",
    "charge": "充电", "discharge": "放电", "hold": "等待",
    "not_applicable_assumed": "研究假设不适用机制", "ratio_assumed": "按声明的比例研究机制",
    "not_binding_assumed": "研究假设本次额度不触顶", "known_remaining": "已填写剩余额度",
    "base": "优先正常情况的金额", "robust": "优先这些不利情况中的最低金额",
    "quantity_known_research_only": "数量条件齐全，仍为研究假设",
    "mechanism_quantity_unresolved": "机制数量不明，不能推荐相关覆盖量",
    "research_lag": "使用历史信息作参考的研究情景",
    "proposal_available": "已有剩余时段建议，不代表真实执行",
    "research_assumption": "明确的研究假设，不是实盘事实",
    "research_scenario_parameter": "本研究声明的参数",
    "research_assumed_approved": "研究假定允许调整，不是真实调度授权",
    "assumed_authorized_adjustment": "研究假定允许调整剩余策略",
    "counterfactual_rule_scenario": "较新规则下的反事实研究",
    "dated_research": "按日期选择口径的研究情景",
    "applicable": "原研究判断适用，仍需结合主体和证据范围",
    "terminal_matched": "期初期末电量满足同口径比较",
}


def enum_zh(value, vocabulary=STATES):
    require(value in vocabulary, "该状态尚无经过核对的中文解释，请查看技术证据。")
    return vocabulary[value]


# Fields are authored once; context overrides below keep money/risk meanings distinct.
FIELDS = {
    "energy_capacity_mwh": FieldSpec("电池能装多少电", "number", "兆瓦时", "额定容量，不是当前可放出的电。"),
    "power_capacity_mw": FieldSpec("最快能充放多快", "number", "兆瓦"),
    "charge_power_limit_mw": FieldSpec("最快能充多快", "number", "兆瓦"),
    "discharge_power_limit_mw": FieldSpec("最快能放多快", "number", "兆瓦"),
    "initial_soc_ratio": FieldSpec("当天开始时电池有多少电", "percent"),
    "current_soc_ratio": FieldSpec("现在电池还剩多少电", "percent"),
    "terminal_soc_ratio": FieldSpec("本次计划结束要剩多少电", "percent"),
    "min_soc_ratio": FieldSpec("最少要留多少电", "percent"),
    "max_soc_ratio": FieldSpec("最多可以充到多少", "percent"),
    "charge_efficiency": FieldSpec("充电效率", "percent", help_zh="充入一兆瓦时，95%效率会存下0.95兆瓦时。"),
    "discharge_efficiency": FieldSpec("放电效率", "percent", help_zh="消耗电池一兆瓦时，95%效率会送出0.95兆瓦时。"),
    "degradation_cost_yuan_per_mwh_throughput": FieldSpec("电池损耗计价", "number", "元/兆瓦时", "按累计充入与放出之和计算模拟成本。"),
    "interval_minutes": FieldSpec("每一步算多长时间", "number", "分钟"),
    "max_equivalent_full_cycles_per_day": FieldSpec("今天总共允许用多少充放额度", "number", "次", "一次额度等于额定容量两倍的累计充入与放出电量，不是电池寿命认证。"),
    "remaining_cycles": FieldSpec("还允许用多少充放额度", "number", "次"),
    "remaining_throughput_mwh": FieldSpec("还允许累计充放多少电", "number", "兆瓦时"),
    "remaining_budget_mwh": FieldSpec("还允许累计充放多少电", "number", "兆瓦时"),
    "used_throughput_mwh": FieldSpec("已经累计充放多少电", "number", "兆瓦时"),
    "current_energy_mwh": FieldSpec("电池现在存了多少电", "number", "兆瓦时"),
    "terminal_energy_mwh": FieldSpec("计划结束要存多少电", "number", "兆瓦时"),
    "stored_energy_before_mwh": FieldSpec("动作前电池电量", "number", "兆瓦时"),
    "stored_energy_after_mwh": FieldSpec("动作后电池电量", "number", "兆瓦时"),
    "soc_before_ratio": FieldSpec("动作前电量比例", "percent"),
    "soc_after_ratio": FieldSpec("动作后电量比例", "percent"),
    "charge_power_mw": FieldSpec("充电速度", "number", "兆瓦"),
    "discharge_power_mw": FieldSpec("放电速度", "number", "兆瓦"),
    "net_injection_mw": FieldSpec("净送出速度（负数表示充电）", "number", "兆瓦"),
    "forecast_price_yuan_per_mwh": FieldSpec("自己判断的未来电价", "number", "元/兆瓦时"),
    "market_date": FieldSpec("数据日期"), "date": FieldSpec("数据日期"),
    "interval_start": FieldSpec("开始时刻"), "interval_end": FieldSpec("结束时刻"),
    "decision_asof": FieldSpec("这次作判断的时刻"), "decided_at": FieldSpec("原研究作判断的时刻"),
    "issued_at": FieldSpec("签发时刻"), "submitted_at": FieldSpec("提交时刻"),
    "timestamp": FieldSpec("动作时刻"), "node_id": FieldSpec("价格环境", "node"),
    "strategy": FieldSpec("选择的交易方法", "strategy"), "action": FieldSpec("这一步做什么", "enum"),
    "status": FieldSpec("当前状态", "enum"), "evaluation_status": FieldSpec("收益能否评价", "enum"),
    "information_mode": FieldSpec("研究类型", "enum"), "pack": FieldSpec("研究类型", "enum"),
    "real_execution_certified": FieldSpec("是否有真实执行认证", "bool"),
    "future_actual_price_used": FieldSpec("是否提前使用了未来真实价格", "bool"),
    "reference_only": FieldSpec("是否仅供事后参照", "bool"), "executable": FieldSpec("是否被标为可执行", "bool"),
    "physical_constraints_passed": FieldSpec("电池限制检查是否通过", "bool"),
    "terminal_comparable": FieldSpec("结束电量是否满足比较要求", "bool"),
    "current_day_observed_intervals": FieldSpec("当日已验证的新行情时段数", "number"),
    "DA_complete": FieldSpec("日前价格是否完整", "bool"), "RT_complete": FieldSpec("实时价格是否完整", "bool"),
    "DA_rows": FieldSpec("日前记录行数（不等于有效价格数）", "number"),
    "RT_rows": FieldSpec("实时记录行数（不等于有效价格数）", "number"),
    "paired": FieldSpec("日前与实时是否完整配对", "bool"),
    "da_amount_yuan": FieldSpec("按事前计划计算的钱", "money", "元", "按日前市场价评价，不表示一定是前一天提交。"),
    "rt_amount_yuan": FieldSpec("实际偏离原计划增减的钱", "money", "元", "按实时市场价算差额。"),
    "degradation_cost_yuan": FieldSpec("模拟电池损耗成本", "money", "元"),
    "simulated_contribution_yuan": FieldSpec("这次已算项目的收支合计", "money", "元"),
    "evaluated_contribution_yuan": FieldSpec("本窗口已算项目的金额合计", "money", "元"),
    "full_profit_yuan": FieldSpec("企业完整利润", "unmodelled", "元"),
    "amount_yuan": FieldSpec("本项金额", "money", "元"),
    "expected_net_mwh": FieldSpec("下个月预计能卖多少电", "number", "兆瓦时"),
    "existing_contract_mwh": FieldSpec("已经承诺卖出多少电", "number", "兆瓦时"),
    "existing_contract_price": FieldSpec("已有合同电能量单价", "number", "元/兆瓦时"),
    "new_contract_price": FieldSpec("新合同电能量单价", "number", "元/兆瓦时"),
    "new_contract_mwh": FieldSpec("准备再签多少电", "number", "兆瓦时"),
    "custom_new_mwh": FieldSpec("另外想试一个新增量（可选）", "number", "兆瓦时"),
    "downside_ratio": FieldSpec("最多可能少发多少", "percent", help_zh="自己给的压力范围，不是发生概率。"),
    "upside_ratio": FieldSpec("多发情景增加多少", "percent"),
    "scenario_month": FieldSpec("研究月份"), "month": FieldSpec("研究月份"),
    "rule_reference_date": FieldSpec("规则参考日期"), "reference_date": FieldSpec("规则参考日期"),
    "total_mwh": FieldSpec("固定承诺电量", "number", "兆瓦时"),
    "coverage": FieldSpec("占剩余可承诺量的比例", "percent"),
    "expected_mechanism_outside_mwh": FieldSpec("预测机制外合格量", "number", "兆瓦时", "权益口径，不从物理市场收入中扣掉这份电。"),
    "remaining_green_quota_mwh": FieldSpec("还可承诺的研究权益额度", "number", "兆瓦时"),
    "estimated_max_environment_shortfall_mwh": FieldSpec("原研究最大权益履约缺额", "number", "兆瓦时"),
    "q_forecast_mwh": FieldSpec("预测将发出的电量", "number", "兆瓦时"),
    "q_declared_mwh": FieldSpec("报给市场的电量", "number", "兆瓦时"),
    "q_awarded_mwh": FieldSpec("研究中假定市场接受的电量", "number", "兆瓦时"),
    "q_executed_mwh": FieldSpec("研究模拟发出来的电量", "number", "兆瓦时"),
    "q_net_mwh": FieldSpec("研究中用于计费的上网量", "number", "兆瓦时", "不是厂内功率自动认证成结算计量。"),
    "q_contract_mwh": FieldSpec("已经承诺的合同电量", "number", "兆瓦时"),
    "feasible": FieldSpec("是否满足本研究条件", "bool"), "chosen": FieldSpec("是否被原研究选中", "bool"),
    "expected_contribution": FieldSpec("原模型加权的已评价贡献", "money", "元"),
    "expected_increment": FieldSpec("相对原无合约基准的预计差额", "money", "元"),
    "budget_shortfall_cvar": FieldSpec("原模型最不利一批情况的平均目标缺口", "money", "元", "不是最大可能亏损；尾部比例由原置信口径决定。"),
    "shortfall_cvar_yuan": FieldSpec("原模型最不利一批情况的平均目标缺口", "money", "元"),
    "cvar_yuan": FieldSpec("原样本最差一批日的平均亏损", "money", "元", "日负贡献截为损失，再按尾部平均。"),
    "max_drawdown_yuan": FieldSpec("原窗口累计贡献的最大回落", "money", "元"),
    "worst_day_yuan": FieldSpec("原窗口最低日贡献", "money", "元"),
    "mean_yuan": FieldSpec("原窗口平均日贡献", "money", "元"),
    "sample_count": FieldSpec("原研究样本数", "number"), "scenario_count": FieldSpec("实际不同的研究情况数", "number"),
    "negative_days": FieldSpec("已评价贡献为负的天数", "number"),
    "missing_count": FieldSpec("未能评价的数量", "number"),
    "small_sample_warning": FieldSpec("是否有短样本警告", "bool"),
    "difference_yuan": FieldSpec("相同已算范围内的金额差额", "money", "元"),
    "additional_rolling_yuan": FieldSpec("多次更新相比只更新一次的金额差额", "money", "元"),
    "switch_to_RT_once_yuan": FieldSpec("只更新一次后增加或减少的钱", "money", "元"),
    "component": FieldSpec("计算科目", "component"), "period": FieldSpec("本项所属时段或账期"),
    "evaluated_subtotal_yuan": FieldSpec("本项已评价金额合计", "money", "元"),
    "complete_component_yuan": FieldSpec("本项完整评价金额", "money", "元"),
    "evaluable": FieldSpec("已评价记录数", "number"), "not_applicable": FieldSpec("不适用记录数", "number"),
    "unresolved": FieldSpec("暂缺依据记录数", "number"), "rows": FieldSpec("记录数", "number"),
}
CONTEXT_OVERRIDES = {
    ("asset", "terminal_soc_ratio"): FieldSpec("当天结束要剩多少电", "percent"),
    ("a_strict", "amount_yuan"): FieldSpec("这条历史资格检查评价的金额", "money", "元"),
    ("b_line", "amount_yuan"): FieldSpec("这个账务科目的金额", "money", "元"),
}
COMPONENTS = {
    "day_ahead": "按事前计划计算的钱", "real_time": "实际偏离计划增减的钱",
    "contract_energy": "合约电能量价格差额", "mechanism": "机制政策另外补或扣的钱",
    "environment": "绿电环境价值", "deviation_recovery": "研究规则下的偏差回收",
    "recovery_refund": "回收返还", "environment_compensation": "环境履约补偿",
    "taxes": "税费", "operating_and_capital_costs": "经营与资本成本", "other_fees": "其他费用",
    "full_profit": "企业完整利润",
}
BUSINESS_COLUMNS = {
    "asset": tuple(k for k in FIELDS if k in {"energy_capacity_mwh", "power_capacity_mw", "initial_soc_ratio", "terminal_soc_ratio", "min_soc_ratio", "max_soc_ratio", "charge_efficiency", "discharge_efficiency", "interval_minutes", "max_equivalent_full_cycles_per_day", "degradation_cost_yuan_per_mwh_throughput"}),
    "a_strict": ("date", "node_id", "pack", "status", "amount_yuan"),
    "a_missing": ("market_date", "node_id", "DA_complete", "RT_complete", "evaluation_status"),
    "a_summary": ("market_date", "strategy", "da_amount_yuan", "rt_amount_yuan", "degradation_cost_yuan", "simulated_contribution_yuan", "evaluation_status", "full_profit_yuan"),
    "a_action": ("interval_start", "interval_end", "action", "charge_power_mw", "discharge_power_mw", "soc_before_ratio", "soc_after_ratio", "remaining_throughput_mwh"),
    "a_event": ("decision_asof", "current_energy_mwh", "used_throughput_mwh", "remaining_budget_mwh", "current_day_observed_intervals", "terminal_energy_mwh"),
    "a_risk": ("sample_count", "mean_yuan", "worst_day_yuan", "negative_days", "cvar_yuan", "small_sample_warning"),
    "b_decision": ("month", "decided_at", "expected_mechanism_outside_mwh", "remaining_green_quota_mwh", "scenario_count", "full_profit_yuan"),
    "b_candidate": ("coverage", "total_mwh", "feasible", "chosen", "estimated_max_environment_shortfall_mwh"),
    "b_score": ("expected_contribution", "expected_increment", "budget_shortfall_cvar", "feasible"),
    "b_input": ("interval_start", "q_forecast_mwh", "q_declared_mwh", "q_awarded_mwh", "q_executed_mwh", "q_net_mwh", "q_contract_mwh"),
    "b_line": ("period", "component", "amount_yuan", "status"),
    "b_coverage": ("component", "evaluated_subtotal_yuan", "complete_component_yuan", "evaluable", "not_applicable", "unresolved"),
    "b_risk": ("sample_count", "shortfall_cvar_yuan"),
    "b_component": ("component", "difference_yuan"),
}
TECHNICAL_FIELDS = (
    "strict_profile_sha256", "source_id", "source_manifest_sha256", "source_object_sha256",
    "source_selector", "run_context_sha256", "forecast_sha256", "proposal_sha256",
    "original_plan_sha256", "original_commitment_sha256", "rule_context_sha256", "research_fallback",
    "solver_status", "solver_mip_gap", "execution_plan_version", "candidate_id", "formula_or_reason",
)


def field_spec(context, key):
    require(key in FIELDS, "这个字段还没有经核对的中文口径，不能直接放进主表。")
    return CONTEXT_OVERRIDES.get((context, key), FIELDS[key])


def format_value(context, key, value, *, status=None):
    spec = field_spec(context, key)
    if spec.kind == "unmodelled":
        require(value is None, "完整利润不应出现一个已计算金额。")
        return "本版未计算"
    if value is None:
        if context == "a_strict" and key == "amount_yuan":
            return "这条资格检查未评价金额"
        return STATES.get(status, "暂缺依据") if status in ("not_evaluable", "not_applicable", "not_modelled", "unknown") else "暂缺依据"
    if spec.kind == "bool":
        require(type(value) is bool, "真假状态不符合字段口径。")
        return "是" if value else "否"
    if spec.kind in ("enum", "strategy", "node", "component"):
        return enum_zh(value, {"enum": STATES, "strategy": STRATEGIES, "node": NODES, "component": COMPONENTS}[spec.kind])
    if spec.kind in ("number", "money", "percent"):
        v = number(value)
        text = decimal_text(v * 100) + "%" if spec.kind == "percent" else (f"{v:,.2f}" if spec.kind == "money" else format(v, "f"))
        return text + (" " + spec.unit_zh if spec.unit_zh else "")
    require(isinstance(value, str) and len(value) <= 160, "业务文字格式不正确。")
    return value


def project_row(context, row):
    require(context in BUSINESS_COLUMNS and isinstance(row, dict), "主表必须使用明确的业务列清单。")
    result = {}
    for key in BUSINESS_COLUMNS[context]:
        if key in row:
            result[field_spec(context, key).label_zh] = format_value(context, key, row[key], status=row.get("evaluation_status", row.get("status")))
    return result


def missing_price_description(row):
    require(type(row.get("DA_complete")) is bool and type(row.get("RT_complete")) is bool, "价格完整性状态尚未确认。")
    da = "日前价格：完整" if row["DA_complete"] else "日前价格：不完整"
    rt = "实时价格：完整" if row["RT_complete"] else "实时价格：缺失或不完整"
    conclusion = "价格配对资格仍需核对" if row["DA_complete"] and row["RT_complete"] else "当天无法评价收益；无法评价不等于收益为零"
    return (da, rt, conclusion)


def generation_tail_caption(confidence):
    v = number(confidence, minimum=Decimal("0.001"), maximum=Decimal("0.999"))
    tail = decimal_text((1-v)*100)
    return f"原模型最不利{tail}%研究情景中，平均比事先目标少多少钱；不是最大可能亏损。"
