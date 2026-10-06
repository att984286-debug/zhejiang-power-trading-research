"""Explicit public research presets; no copied historical inputs or answers."""
from .errors import ErrorCode, exact_keys, require
from .numbers import percent, price, decimal_text
from .storage import normalize_storage
from .generation import normalize_generation, PRICE_KEYS

STORAGE_PRESET_ID = "storage-quick-standard-v1"
GENERATION_PRESET_ID = "generation-quick-lockprice-v1"
STORAGE_ASSUMPTIONS_ZH = (
    "标准研究电池：容量200兆瓦时，最大充放速度各100兆瓦。",
    "充放效率各95%，电量安全范围10%至90%。",
    "每兆瓦时累计充入与放出电量计模拟电池损耗30元。",
    "计划结束回到当前电量；只填写剩余额度，不推测已用历史。",
    "价格为用户判断，每行默认1小时，不是真实行情或已成交价格。",
)
GENERATION_ASSUMPTIONS_ZH = (
    "只比较电能量锁价与少发风险；明确假设不适用机制，不计算机制补差。",
    "电站卖电价与合同计费参考价采用同价代理，不研究位置价格差。",
    "已有合同量按填写保留；其单价暂按本次新合同价估计，不同则进入高级。",
    "年度额度假设不触顶；不新增超过声明最少可履约量的承诺。",
    "只组合正常、少发与三档价格；不假定这些情况的发生概率。",
    "绿电环境价值、补偿和其他费用未计算；结果不是完整利润。",
)


def storage_quick(value):
    exact_keys(value, ("current_soc_percent", "remaining_cycles", "prices", "wait_until", "accept_preset"))
    require(value["accept_preset"] is True, "请先确认标准电池和结束电量假设。", ErrorCode.ASSUMPTION_REQUIRED)
    current = percent(value["current_soc_percent"])
    return normalize_storage({
        "energy_capacity_mwh": "200", "charge_power_limit_mw": "100", "discharge_power_limit_mw": "100",
        "current_soc_ratio": current, "min_soc_ratio": "0.1", "max_soc_ratio": "0.9", "terminal_soc_ratio": current,
        "charge_efficiency": "0.95", "discharge_efficiency": "0.95",
        "degradation_cost_yuan_per_mwh_throughput": "30", "interval_minutes": 60,
        "budget": {"mode": "remaining", "remaining_cycles": value["remaining_cycles"]},
        "prices": value["prices"], "wait_until": value["wait_until"],
    })


def generation_quick(value):
    exact_keys(value, ("scenario_month", "rule_reference_date", "expected_net_mwh", "downside_percent",
                       "existing_contract_mwh", "contract_energy_price", "spot_prices", "custom_new_mwh", "accept_preset"))
    require(value["accept_preset"] is True, "请先确认锁价、机制和价格代理假设。", ErrorCode.ASSUMPTION_REQUIRED)
    prices = value["spot_prices"]
    exact_keys(prices, PRICE_KEYS)
    contract = price(value["contract_energy_price"])
    return normalize_generation({
        "scenario_month": value["scenario_month"], "rule_reference_date": value["rule_reference_date"],
        "subject_scenario": "unspecified_research", "expected_net_mwh": value["expected_net_mwh"],
        "downside_ratio": percent(value["downside_percent"]), "upside_ratio": "0",
        "existing_contract_mwh": value["existing_contract_mwh"], "existing_contract_price": contract,
        "new_contract_price": contract, "contract_price_scope": "energy_only",
        "mechanism": {"mode": "not_applicable_assumed", "ratio": None, "cap_mode": "not_binding_assumed",
                      "remaining_cap_mwh": None, "price_yuan_per_mwh": None},
        "asset_prices": prices.copy(), "delivery_prices": prices.copy(), "mechanism_reference_prices": None,
        "price_linkage": "asset_delivery_same_assumed",
        "new_contract_limit": {"mode": "not_binding_assumed", "remaining_mwh": None},
        "enforce_minimum_fulfillment": True, "risk_preference": "robust", "custom_new_mwh": value["custom_new_mwh"],
    })


def preset_record(case):
    require(case in ("storage", "generation"), "未知研究预设。")
    return {
        "id": STORAGE_PRESET_ID if case == "storage" else GENERATION_PRESET_ID,
        "case": case,
        "source": "synthetic_research_preset",
        "assumptions_zh": list(STORAGE_ASSUMPTIONS_ZH if case == "storage" else GENERATION_ASSUMPTIONS_ZH),
        "requires_explicit_acceptance": True,
        "real_execution_certified": False,
        "historical_result": False,
    }

