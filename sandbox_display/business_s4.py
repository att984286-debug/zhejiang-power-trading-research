"""New S4 Chinese projections; immutable S1 vocabulary stays unchanged."""
from decimal import Decimal
import re

from .zh import STRATEGIES, NODES, STATES, COMPONENTS, BUSINESS_COLUMNS, field_spec, format_value

STATUS = {**STATES, "charge": "充电", "discharge": "放电", "hold": "等待",
          "fixed": "固定安排", "optimal": "本次比较完成", "unknown_not_zero_not_included": "费用暂缺依据，未计入",
          "stock": "存量新能源研究身份", "incremental": "增量新能源研究身份",
          "wind": "风电", "centrally_dispatched": "研究假设统一调度",
          "scenario": "模型内压力情况", "observed": "已有资料范围",
          "counterfactual_research": "较新规则下的反事实情景",
          "research_reference_not_verified_history": "按参考日研究，非严格历史认证"}
METHODS = {"optimized": "综合安排剩余时段", "full_discharge_now": "现在第一时段满功率放电",
           "wait_until": "留到指定时刻再安排", "no_operation": "不充不放的对照"}
AMOUNTS = {"evaluated": "已评价", "unknown": "暂缺依据", "not_evaluable": "无法评价",
           "not_applicable": "不适用", "not_modelled": "本版未计算"}
SUBJECTS = {"existing_renewable_assumed": "假设为存量新能源", "incremental_renewable_assumed": "假设为增量新能源",
            "unspecified_research": "不认证企业身份的研究情景"}
GEN_COMPONENTS = {"market_energy": "全部上网量按电站价格算的钱",
                  "existing_contract_difference": "已有合同锁价增减的钱",
                  "new_contract_difference": "新增合同锁价增减的钱", "mechanism_difference": "机制政策另补或扣的钱"}


def number_text(value, digits=2):
    if value is None or value == "":
        return "暂缺依据"
    n = Decimal(str(value))
    if not n.is_finite():
        raise ValueError("数值没有可用的中文显示口径")
    return f"{n:,.{digits}f}"


def amount(value):
    if hasattr(value, "status"):
        return number_text(value.value_yuan) if value.status.value == "evaluated" else AMOUNTS[value.status.value]
    return number_text(value)


def percent(value):
    return "暂缺依据" if value is None else number_text(Decimal(str(value))*100) + "%"


def safe_enum(value, vocabulary=STATUS):
    return vocabulary.get(value, "原状态需查看技术证据（未作推断）")


def project(context, rows):
    clean=[]
    for row in rows:
        copy=dict(row)
        # Legacy CSV-shaped public stress object: "" is explicitly unmodelled.
        # Never mutate the frozen object or convert an unknown amount to zero.
        if copy.get("full_profit_yuan")=="":copy["full_profit_yuan"]=None
        shown={}
        for key in BUSINESS_COLUMNS[context]:
            if key not in copy:continue
            spec=field_spec(context,key)
            value=copy[key]
            if value is not None and spec.kind in ("number","money","percent"):
                # Old solver doubles can have tiny non-zero roundoff. This is
                # a read-only display boundary, NOT permission to relax S1 input.
                n=Decimal(str(value))
                if not n.is_finite():raise ValueError("历史数值无法显示")
                text=percent(n) if spec.kind=="percent" else number_text(n) if spec.kind=="money" else format(n,"f")
                shown[spec.label_zh]=text+(" "+spec.unit_zh if spec.unit_zh else "")
            else:
                shown[spec.label_zh]=format_value(context,key,value,status=copy.get("evaluation_status",copy.get("status")))
        clean.append(shown)
    return clean


def action_rows(request, computed):
    if computed.evaluation is None:
        return []
    result = []
    for i, (r, c) in enumerate(zip(computed.plan.interval_rows, computed.evaluation.cash_rows)):
        result.append({"时段开始": r.interval_start.isoformat(), "时段结束": r.interval_end.isoformat(),
            "动作": "充电" if r.charge_power_mw > 0 else "放电" if r.discharge_power_mw > 0 else "等待",
            "充电速度（兆瓦）": number_text(r.charge_power_mw), "放电速度（兆瓦）": number_text(r.discharge_power_mw),
            "开始电量比例": percent(r.stored_energy_before_mwh/request.energy_capacity_mwh),
            "结束电量比例": percent(r.stored_energy_after_mwh/request.energy_capacity_mwh),
            "剩余充放额度（兆瓦时）": number_text(r.remaining_throughput_mwh),
            "充电成本（元）": amount(c.charge_cost), "放电收入（元）": amount(c.discharge_revenue),
            "模拟电池损耗（元）": amount(c.degradation_cost), "收支差额（元）": amount(r.contribution)})
    return result


def scenario_name(aliases):
    qs = {"base": "正常发电", "low": "少发", "high": "多发"}
    ps = {"base": "通常价格", "low": "价格下跌", "high": "价格上涨"}
    return "／".join(qs[q]+"、"+ps[p] for q,p in aliases)


def scenario_rows(assessment):
    return [{"联合情况": scenario_name(r.aliases),
        "可卖电量（兆瓦时）": number_text(r.evaluation.net_energy_mwh),
        "合同承诺总量（兆瓦时）": number_text(r.evaluation.total_contract_mwh),
        "机制结算量（兆瓦时）": number_text(r.evaluation.mechanism_energy_mwh),
        "全部电量的市场金额（元）": amount(r.evaluation.market_energy),
        "已有合同价差（元）": amount(r.evaluation.existing_contract_difference),
        "新增合同价差（元）": amount(r.evaluation.new_contract_difference),
        "机制补扣金额（元）": amount(r.evaluation.mechanism_difference),
        "共同已算项目合计（元）": amount(r.evaluation.evaluated_contribution),
        "履约缺额（兆瓦时）": number_text(r.fulfillment_shortfall_mwh),
        "机制额度触顶": "未确认" if r.mechanism_cap_binding is None else "是" if r.mechanism_cap_binding else "否"}
        for r in assessment.scenarios]


def candidates(result):
    return [{"新增方案": "／".join(l.label_zh for l in a.labels),
        "新增合同（兆瓦时）": number_text(a.candidate.new_contract_mwh),
        "占总预测电量": percent(a.new_share_of_total_forecast),
        "可参与本次推荐": "是" if a.candidate.recommendation_eligible else "否",
        "正常情况金额（元）": amount(a.candidate.baseline_amount),
        "联合情况最低金额（元）": amount(a.candidate.minimum_scenario_amount),
        "原因": "；".join(a.reasons_zh + a.selection_notes_zh)} for a in result.assessments]


def storage_snapshot(request):
    return [{"条件": label, "内容": value} for label,value in [
        ("电池容量", number_text(request.energy_capacity_mwh)+" 兆瓦时"),
        ("最大充电／放电速度", number_text(request.charge_power_limit_mw)+"／"+number_text(request.discharge_power_limit_mw)+" 兆瓦"),
        ("当前／计划结束电量比例", percent(request.current_soc_ratio)+"／"+percent(request.terminal_soc_ratio)),
        ("安全边界", percent(request.min_soc_ratio)+"—"+percent(request.max_soc_ratio)),
        ("充电／放电效率", percent(request.charge_efficiency)+"／"+percent(request.discharge_efficiency)),
        ("剩余累计充放额度", number_text(request.remaining_throughput_mwh)+" 兆瓦时"),
        ("额度填写方式", "直接填写剩余量" if request.budget_record.source=="remaining" else "今天总量减已用量"),
        ("剩余充放次数", number_text(request.budget_record.remaining_cycles)),
        ("今天总量／已用次数", "未提供，不作反推" if request.budget_record.total_cycles is None else number_text(request.budget_record.total_cycles)+"／"+number_text(request.budget_record.used_cycles)),
        ("模拟损耗计价", number_text(request.degradation_cost_yuan_per_mwh_throughput)+" 元/兆瓦时"),
        ("每步时长", str(request.interval_minutes)+" 分钟"),
        ("本次窗口", request.prices[0].interval_start.isoformat()+" → "+request.prices[-1].interval_end.isoformat()),
        ("等待对照时刻", "未设置" if request.wait_until is None else request.wait_until.isoformat())]]


def generation_snapshot(request):
    return [{"条件": label, "内容": value} for label,value in [
        ("研究月份／规则参考日", request.scenario_month+"／"+request.rule_reference_date.isoformat()),
        ("主体情景", SUBJECTS[request.subject_scenario]),
        ("预计可卖电量", number_text(request.expected_net_mwh)+" 兆瓦时"),
        ("少发／多发范围", percent(request.downside_ratio)+"／"+percent(request.upside_ratio)),
        ("已有合同量／价", number_text(request.existing_contract_mwh)+" 兆瓦时／"+number_text(request.existing_contract_price)+" 元/兆瓦时"),
        ("新合同电能量单价", number_text(request.new_contract_price)+" 元/兆瓦时"),
        ("机制处理", safe_enum(request.mechanism.mode)),
        ("机制比例／剩余额度", "不适用（研究假设）" if request.mechanism.mode=="not_applicable_assumed" else percent(request.mechanism.ratio)+"／"+(number_text(request.mechanism.remaining_cap_mwh)+" 兆瓦时" if request.mechanism.cap_mode == "known_remaining" else safe_enum(request.mechanism.cap_mode))),
        ("机制研究价", "不适用" if request.mechanism.mode=="not_applicable_assumed" else number_text(request.mechanism.price_yuan_per_mwh)+" 元/兆瓦时"),
        ("参考价格关系", {"asset_delivery_same_assumed":"电站与合同参考价同价代理", "all_same_assumed":"三类价格同价代理", "separate_assumed":"三类价格分开设置"}[request.price_linkage]),
        ("新增额度状态", safe_enum(request.new_contract_limit_mode)),
        ("明确新增额度", "未填数值（不是零）" if request.new_contract_limit_mwh is None else number_text(request.new_contract_limit_mwh)+" 兆瓦时"),
        ("自定义新增候选", "未设置" if request.custom_new_mwh is None else number_text(request.custom_new_mwh)+" 兆瓦时"),
        ("少发履约限制", "开启（研究约束）" if request.enforce_minimum_fulfillment else "关闭（只作条件排名）"),
        ("选择偏好", safe_enum(request.risk_preference)),
        ("真实资格与完整利润", "未认证／未计算")]]


def price_snapshot(request):
    if hasattr(request,"prices"):
        return [{"时段开始":r.interval_start.isoformat(),"时段结束":r.interval_end.isoformat(),
            "预测价格（元/兆瓦时）":format(r.forecast_price_yuan_per_mwh,"f")} for r in request.prices]
    return [{"价格档":["较低","通常","较高"][i],
        "电站卖电参考价（元/兆瓦时）":format(request.asset_prices[i],"f"),
        "合同计费参考价（元/兆瓦时）":format(request.delivery_prices[i],"f"),
        "机制结算参考价（元/兆瓦时）":"不适用" if request.mechanism.mode=="not_applicable_assumed" else "暂缺依据" if request.mechanism_reference_prices is None else format(request.mechanism_reference_prices[i],"f")} for i in range(3)]


def diagnostic_rows(result):
    return [{"联合情况":scenario_name(r.aliases),"可卖电量（兆瓦时）":number_text(r.evaluation.net_energy_mwh),
        "原合同（兆瓦时）":number_text(r.evaluation.total_contract_mwh),
        "机制量（兆瓦时）":number_text(r.evaluation.mechanism_energy_mwh),
        "市场金额（元）":amount(r.evaluation.market_energy),
        "原合同价差（元）":amount(r.evaluation.existing_contract_difference),
        "已算分项金额（元）":amount(r.evaluation.evaluated_contribution),
        "机制金额（元）":amount(r.evaluation.mechanism_difference)} for r in result.diagnostic_rows]


def language_defects(strings):
    """App-controlled business copy only; units and ISO times are permitted."""
    bad = []
    pattern = re.compile(r"[a-zA-Z]+_[a-zA-Z0-9_]+|\b(?:SHA256|CVaR|Ridge|Oracle|SOC|strict|research|unknown|DA|RT|CASE)\b|[a-f0-9]{64}")
    for text in strings:
        if pattern.search(str(text)):
            bad.append(str(text))
    return bad
