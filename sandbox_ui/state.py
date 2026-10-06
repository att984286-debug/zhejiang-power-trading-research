"""Ephemeral per-session mode drafts and input-bound results, no global cache."""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal

from decision_core.presets import storage_quick, generation_quick
from decision_core.storage import normalize_storage
from decision_core.generation import normalize_generation


def quick_payload(case, payload):
    """Restore visible quick assumptions; preserve shared user quantities/prices."""
    p = deepcopy(payload)
    if case == "storage":
        record = p["budget"]
        remaining = record.get("remaining_cycles")
        if remaining is None:
            remaining = str(Decimal(str(record["total_cycles"]))-Decimal(str(record["used_cycles"])))
        return storage_quick({"current_soc_percent": str(Decimal(str(p["current_soc_ratio"]))*100),
            "remaining_cycles": remaining, "prices": p["prices"], "wait_until": p["wait_until"],
            "accept_preset": True}).editable_payload()
    return generation_quick({"scenario_month": p["scenario_month"], "rule_reference_date": p["rule_reference_date"],
        "expected_net_mwh": p["expected_net_mwh"], "downside_percent": str(Decimal(str(p["downside_ratio"]))*100),
        "existing_contract_mwh": p["existing_contract_mwh"], "contract_energy_price": p["new_contract_price"],
        "spot_prices": p["asset_prices"], "custom_new_mwh": p["custom_new_mwh"], "accept_preset": True}).editable_payload()


def quick_differences(case, payload):
    try:
        new = quick_payload(case,payload)
    except (ValueError, TypeError):
        return ["当前时间表或数值不符合快速预设，请先修正或继续高级测算。"]
    fields = {"storage": {"energy_capacity_mwh":"电池容量", "charge_power_limit_mw":"充电速度",
        "discharge_power_limit_mw":"放电速度", "terminal_soc_ratio":"结束电量目标", "min_soc_ratio":"最低电量",
        "max_soc_ratio":"最高电量", "charge_efficiency":"充电效率", "discharge_efficiency":"放电效率",
        "degradation_cost_yuan_per_mwh_throughput":"损耗计价", "interval_minutes":"时间间隔", "budget":"额度输入方式"},
        "generation": {"subject_scenario":"主体假设", "upside_ratio":"多发范围", "existing_contract_price":"原合同单价",
        "mechanism":"机制假设", "delivery_prices":"合同参考价", "mechanism_reference_prices":"机制参考价",
        "price_linkage":"价格关系", "new_contract_limit":"新增额度假设", "enforce_minimum_fulfillment":"少发履约限制",
        "risk_preference":"选择偏好"}}
    norm = normalize_storage if case == "storage" else normalize_generation
    try:
        before,after = norm(payload).editable_payload(),norm(new).editable_payload()
        differences=[label for key,label in fields[case].items() if before[key] != after[key]]
        if case=="storage" and payload["budget"]["mode"] != new["budget"]["mode"]:
            differences.append("额度输入方式（保留原高级草稿的总量及已用记录）")
        return differences
    except (ValueError,TypeError):
        return ["高级条件尚未校验，不能无提示切换预设。"]


@dataclass(frozen=True)
class Submitted:
    request: object
    result: object
    mode: str
    preset_id: str | None
    raw_input: dict | None = None

    def matches(self, request):
        # Physical hashes intentionally omit provenance. Snapshots do not.
        return request is not None and self.request == request
