"""Monthly generation input contract. No forecast, ranking or revenue engine."""
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, localcontext
import re

from .contracts import fingerprint, primitive
from .errors import ErrorCode, exact_keys, require
from .numbers import MAX_MONTH_ENERGY_MWH, number, price, ratio

INPUT_FIELDS = (
    "scenario_month", "rule_reference_date", "subject_scenario", "expected_net_mwh",
    "downside_ratio", "upside_ratio", "existing_contract_mwh", "existing_contract_price",
    "new_contract_price", "contract_price_scope", "mechanism", "asset_prices",
    "delivery_prices", "mechanism_reference_prices", "price_linkage",
    "new_contract_limit", "enforce_minimum_fulfillment", "risk_preference", "custom_new_mwh",
)
PRICE_KEYS = ("low", "base", "high")


def energy(value):
    return number(value, minimum=Decimal(0), maximum=MAX_MONTH_ENERGY_MWH)


def price_path(value):
    exact_keys(value, PRICE_KEYS)
    return tuple(price(value[k]) for k in PRICE_KEYS)


@dataclass(frozen=True)
class Mechanism:
    mode: str
    ratio: Decimal | None
    cap_mode: str
    remaining_cap_mwh: Decimal | None
    price_yuan_per_mwh: Decimal | None

    @property
    def quantity_known(self):
        return self.mode == "not_applicable_assumed" or (
            self.mode == "ratio_assumed" and self.cap_mode != "unknown")


def normalize_mechanism(value):
    exact_keys(value, ("mode", "ratio", "cap_mode", "remaining_cap_mwh", "price_yuan_per_mwh"))
    mode, cap_mode = value["mode"], value["cap_mode"]
    require(mode in ("not_applicable_assumed", "ratio_assumed", "unknown"), "机制适用状态必须明确。")
    require(cap_mode in ("known_remaining", "not_binding_assumed", "unknown"), "机制额度必须有明确状态。")
    if mode == "ratio_assumed":
        r = ratio(value["ratio"])
    else:
        require(value["ratio"] is None, "机制未知或假设不适用时，不能同时指定比例。")
        r = None
    if cap_mode == "known_remaining":
        cap = energy(value["remaining_cap_mwh"])
    else:
        require(value["remaining_cap_mwh"] is None, "未确认额度不能自动填写数值。")
        cap = None
    p = None if value["price_yuan_per_mwh"] is None else price(value["price_yuan_per_mwh"])
    if mode == "not_applicable_assumed":
        require(p is None and cap_mode == "not_binding_assumed", "假设不计算机制补差时，不要同时填写机制金额条件。")
    if mode == "unknown":
        require(p is None, "机制未知时不能把一个假设价当作已知适用价格。")
    return Mechanism(mode, r, cap_mode, cap, p)


@dataclass(frozen=True)
class GenerationScenario:
    quantity_label: str
    price_label: str
    net_mwh: Decimal
    asset_price: Decimal
    delivery_price: Decimal
    mechanism_reference_price: Decimal | None
    aliases: tuple[tuple[str, str], ...] = ()

    def business_key(self):
        return (self.net_mwh, self.asset_price, self.delivery_price, self.mechanism_reference_price)


@dataclass(frozen=True)
class GenerationRequest:
    scenario_month: str
    rule_reference_date: date
    subject_scenario: str
    expected_net_mwh: Decimal
    downside_ratio: Decimal
    upside_ratio: Decimal
    existing_contract_mwh: Decimal
    existing_contract_price: Decimal | None
    new_contract_price: Decimal
    contract_price_scope: str
    mechanism: Mechanism
    asset_prices: tuple[Decimal, ...]
    delivery_prices: tuple[Decimal, ...]
    mechanism_reference_prices: tuple[Decimal, ...] | None
    price_linkage: str
    new_contract_limit_mode: str
    new_contract_limit_mwh: Decimal | None
    enforce_minimum_fulfillment: bool
    risk_preference: str
    custom_new_mwh: Decimal | None
    scenarios: tuple[GenerationScenario, ...]

    @property
    def input_sha256(self):
        return fingerprint(primitive(self))

    @property
    def eligibility_state(self):
        return "quantity_known_research_only" if self.mechanism.quantity_known else "mechanism_quantity_unresolved"

    @property
    def rule_relation(self):
        first = date.fromisoformat(self.scenario_month + "-01")
        return "counterfactual_research" if self.rule_reference_date > first else "research_reference_not_verified_history"

    def editable_payload(self):
        value = primitive(self)
        value["rule_reference_date"] = self.rule_reference_date.isoformat()
        value.pop("scenarios")
        value["mechanism"] = {
            "mode": self.mechanism.mode, "ratio": None if self.mechanism.ratio is None else str(self.mechanism.ratio),
            "cap_mode": self.mechanism.cap_mode, "remaining_cap_mwh": None if self.mechanism.remaining_cap_mwh is None else str(self.mechanism.remaining_cap_mwh),
            "price_yuan_per_mwh": None if self.mechanism.price_yuan_per_mwh is None else str(self.mechanism.price_yuan_per_mwh),
        }
        for key in ("asset_prices", "delivery_prices", "mechanism_reference_prices"):
            values = getattr(self, key)
            value[key] = None if values is None else dict(zip(PRICE_KEYS, map(str, values)))
        value["new_contract_limit"] = {"mode": value.pop("new_contract_limit_mode"), "remaining_mwh": value.pop("new_contract_limit_mwh")}
        return value

    @classmethod
    def from_mapping(cls, value):
        exact_keys(value, INPUT_FIELDS)
        month = value["scenario_month"]
        require(isinstance(month, str) and re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", month), "研究月份应为明确的年月。")
        ref = value["rule_reference_date"]
        require(isinstance(ref, str) and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", ref), "规则参考日期格式不正确。")
        try:
            ref = date.fromisoformat(ref)
        except ValueError:
            require(False, "规则参考日期不存在。")
        subject = value["subject_scenario"]
        require(subject in ("existing_renewable_assumed", "incremental_renewable_assumed", "unspecified_research"),
                "请明确主体研究身份；本工具不自动认证企业资格。")
        q = energy(value["expected_net_mwh"])
        require(q > 0, "预计可卖电量必须大于零。")
        down, up = ratio(value["downside_ratio"]), ratio(value["upside_ratio"])
        require(q * (1 + up) <= MAX_MONTH_ENERGY_MWH, "压力情景电量超出本工具范围。", ErrorCode.ENGINEERING_LIMIT)
        existing = energy(value["existing_contract_mwh"])
        existing_p = None if value["existing_contract_price"] is None else price(value["existing_contract_price"])
        require(existing == 0 or existing_p is not None, "已有合同不为零，必须说明它的电能量单价。")
        new_p = price(value["new_contract_price"])
        require(value["contract_price_scope"] == "energy_only", "请填写电能量部分单价；含环境价值的总价不能直接代入。")
        mechanism = normalize_mechanism(value["mechanism"])
        assets = price_path(value["asset_prices"])
        require(assets[0] <= assets[1] <= assets[2], "较低、通常、较高价格的顺序不正确。")
        linkage = value["price_linkage"]
        require(linkage in ("asset_delivery_same_assumed", "all_same_assumed", "separate_assumed"), "请明确三类参考价的关系。")
        deliveries = price_path(value["delivery_prices"])
        refs = None if value["mechanism_reference_prices"] is None else price_path(value["mechanism_reference_prices"])
        if linkage in ("asset_delivery_same_assumed", "all_same_assumed"):
            require(assets == deliveries, "同价代理被选中，但资产价与合同参考价不一致。")
        if linkage == "all_same_assumed":
            require(refs == assets, "三类同价代理需要填写完全一致的参考价格。")
        limit = value["new_contract_limit"]
        exact_keys(limit, ("mode", "remaining_mwh"))
        require(limit["mode"] in ("known_remaining", "not_binding_assumed", "unknown"), "新增额度状态必须明确。")
        quota = energy(limit["remaining_mwh"]) if limit["mode"] == "known_remaining" else None
        require(quota is not None or limit["remaining_mwh"] is None, "额度未确认不能填入一个默认值。")
        safe, risk = value["enforce_minimum_fulfillment"], value["risk_preference"]
        require(type(safe) is bool and risk in ("base", "robust"), "履约约束或取舍偏好不正确。")
        custom = None if value["custom_new_mwh"] is None else energy(value["custom_new_mwh"])
        quantities = [("base", q), ("low", q * (1 - down))]
        if up > 0:
            quantities.append(("high", q * (1 + up)))
        rows, seen = [], {}
        for q_label, amount in quantities:
            for i in (1, 0, 2):
                p_label = PRICE_KEYS[i]
                role = (q_label, p_label)
                row = GenerationScenario(q_label, p_label, amount, assets[i], deliveries[i],
                                         None if refs is None else refs[i], (role,))
                key = row.business_key()
                if key not in seen:
                    seen[key] = len(rows)
                    rows.append(row)
                else:
                    index = seen[key]
                    rows[index] = replace(rows[index], aliases=rows[index].aliases + (role,))
        return cls(month, ref, subject, q, down, up, existing, existing_p, new_p, "energy_only", mechanism,
                   assets, deliveries, refs, linkage, limit["mode"], quota, safe, risk, custom, tuple(rows))


def normalize_generation(value):
    """Common quick / advanced boundary; no hidden mode or scenario probabilities."""
    with localcontext() as ctx:
        ctx.prec = 50
        return GenerationRequest.from_mapping(value)
