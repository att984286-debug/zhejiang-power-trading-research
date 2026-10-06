"""Pure monthly aggregate scenario research, not official settlement or forecasting.

Immutable S1 contracts; no storage runtime, IO, SDK, policy or private-data imports.
"""
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from .contracts import (Amount, AmountStatus, GenerationCandidate, GenerationOutput,
                        GenerationScenarioEvaluation, ResultMetadata, RunStatus)
from .errors import require
from .generation import GenerationRequest, normalize_generation
from .numbers import decimal_text

ENGINE_VERSION = "generation-sandbox-engine-v1"
ZERO = Decimal(0)
MONEY_QUANTUM = Decimal("1e-12")
QUANTITY_QUANTUM = Decimal("1e-18")
RANK_TOLERANCE_YUAN = Decimal("0.01")
COMPONENTS = ("market_energy", "existing_contract_difference", "new_contract_difference")
FRACTIONS = (ZERO, Decimal("0.25"), Decimal("0.5"), Decimal("0.75"), Decimal(1))
BOUNDARY_ZH = "本次情景测算，不属于历史冻结研究结果；已评价金额不是企业完整利润，也不认证合同或机制资格。"


def quantity(value):
    return value.quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_EVEN)


def money(value):
    return Amount(AmountStatus.EVALUATED, value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN))


def text(value):
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    if value and not rounded:
        return "小于0.01" if value > 0 else "介于负0.01和零之间"
    return decimal_text(rounded)


def validated_request(request):
    require(isinstance(request, GenerationRequest), "请先校验发电量、合同和价格条件。")
    clean = normalize_generation(request.editable_payload())
    require(clean == request and clean.input_sha256 == request.input_sha256,
            "发电请求与已校验条件不一致，不能使用手改的联合情况。")
    return request


def mechanism_quantity(request, q):
    m = request.mechanism
    if not m.quantity_known:
        return None
    if m.mode == "not_applicable_assumed":
        return ZERO
    value = quantity(m.ratio*q)
    if m.cap_mode == "known_remaining":
        value = min(value, m.remaining_cap_mwh)
    return quantity(value)


def mechanism_amount(request, m, reference):
    if request.mechanism.mode == "not_applicable_assumed":
        return Amount(AmountStatus.NOT_APPLICABLE, None)
    if m is None:
        return Amount(AmountStatus.UNKNOWN, None)
    if m == 0:
        return money(ZERO)  # Proven zero quantity; not a missing-price fallback.
    if request.mechanism.price_yuan_per_mwh is None or reference is None:
        return Amount(AmountStatus.UNKNOWN, None)
    return money(m*(request.mechanism.price_yuan_per_mwh-reference))


def common_components(request):
    if request.mechanism.mode == "not_applicable_assumed":
        return COMPONENTS
    complete = all(mechanism_amount(request, mechanism_quantity(request, quantity(s.net_mwh)),
                                    s.mechanism_reference_price).status == AmountStatus.EVALUATED
                   for s in request.scenarios)
    return COMPONENTS + (("mechanism_difference",) if complete else ())


@dataclass(frozen=True)
class ScenarioDetail:
    evaluation: GenerationScenarioEvaluation
    aliases: tuple[tuple[str, str], ...]
    available_nonmechanism_mwh: Decimal | None
    fulfillment_shortfall_mwh: Decimal | None
    market_quantity_residual_mwh: Decimal
    price_sensitivity_mwh: Decimal | None
    sensitivity_scope_zh: str
    asset_delivery_basis_yuan: Amount
    mechanism_cap_binding: bool | None
    environment_value: Amount = Amount(AmountStatus.NOT_MODELLED, None)
    compensation: Amount = Amount(AmountStatus.NOT_MODELLED, None)


def evaluate_scenario(request, scenario_index, new_mwh, components):
    s = request.scenarios[scenario_index]
    q, new = quantity(s.net_mwh), quantity(new_mwh)
    existing = quantity(request.existing_contract_mwh)
    total = existing+new
    m = mechanism_quantity(request,q)
    market = money(q*s.asset_price)
    old_diff = money(ZERO if existing == 0 else existing*(request.existing_contract_price-s.delivery_price))
    new_diff = money(new*(request.new_contract_price-s.delivery_price))
    mechanism = mechanism_amount(request,m,s.mechanism_reference_price)
    values = dict(zip(COMPONENTS+("mechanism_difference",),(market,old_diff,new_diff,mechanism)))
    require(all(values[c].status == AmountStatus.EVALUATED for c in components),
            "共同评价范围含未知科目，不能相加或排名。")
    contribution = money(sum((values[c].value_yuan for c in components), ZERO))
    available = None if m is None else q-m
    shortfall = None if available is None else max(ZERO,total-available)
    residual = q-total
    if request.price_linkage == "separate_assumed":
        sensitivity, scope = None,"三类价格独立变化，不用一个电量数字代替全部价格风险。"
    elif "mechanism_difference" not in components:
        sensitivity, scope = residual,"仅已评价的市场与合同分项，同价变化1元/MWh的金额敏感度；不含未知机制。"
    elif request.price_linkage == "all_same_assumed":
        sensitivity, scope = residual-m,"三类价格同步变化且机制已评价时，已评价金额对同一价格的敏感度。"
    else:
        sensitivity, scope = None,"机制参考价格未声明随资产和交付价格同步，不给统一价格敏感度。"
    cap_binding = None
    if m is not None:
        cap_binding = (request.mechanism.mode == "ratio_assumed"
                       and request.mechanism.cap_mode == "known_remaining"
                       and quantity(request.mechanism.ratio*q) >= request.mechanism.remaining_cap_mwh)
    row = GenerationScenarioEvaluation(scenario_index,q,m,total,market,old_diff,new_diff,mechanism,contribution)
    return ScenarioDetail(row,s.aliases,available,shortfall,residual,sensitivity,scope,
                          money(q*(s.asset_price-s.delivery_price)),cap_binding)


@dataclass(frozen=True)
class CandidateLabel:
    kind: str
    fraction: Decimal | None
    label_zh: str


@dataclass(frozen=True)
class QuantityBasis:
    base_net_mwh: Decimal
    base_mechanism_mwh: Decimal | None
    base_nonmechanism_mwh: Decimal | None
    existing_contract_mwh: Decimal
    raw_remaining_commitment_mwh: Decimal | None
    new_available_mwh: Decimal | None
    existing_overcommitment_mwh: Decimal | None
    minimum_nonmechanism_mwh: Decimal | None


def quantity_basis(request):
    q, existing = quantity(request.expected_net_mwh),quantity(request.existing_contract_mwh)
    m = mechanism_quantity(request,q)
    if m is None:
        return QuantityBasis(q,None,None,existing,None,None,None,None)
    available = q-m
    remaining = available-existing
    # Preserve raw negative remainder and explicit excess; never quietly clip it away.
    excess = -remaining if remaining < 0 else ZERO
    new_available = ZERO if remaining < 0 else remaining
    minimum = min(quantity(s.net_mwh)-mechanism_quantity(request,quantity(s.net_mwh)) for s in request.scenarios)
    return QuantityBasis(q,m,available,existing,remaining,new_available,excess,minimum)


@dataclass(frozen=True)
class CandidateAssessment:
    candidate: GenerationCandidate
    labels: tuple[CandidateLabel, ...]
    new_share_of_total_forecast: Decimal
    scenarios: tuple[ScenarioDetail, ...]
    baseline_scenario_index: int
    worst_scenario_indices: tuple[int, ...]
    cards: tuple[tuple[str, int, Amount], ...]
    baseline_vs_no_add_yuan: Amount
    minimum_vs_no_add_yuan: Amount
    per_scenario_vs_no_add_yuan: tuple[Amount, ...]
    reasons_zh: tuple[str, ...]
    selection_notes_zh: tuple[str, ...] = ()


REASON_ZH = {
    "NEW_EXCEEDS_BASE_REMAINDER":"新增承诺超过基准剩余可承诺量；不裁剪，保留试算但不推荐。",
    "NEW_LIMIT_UNKNOWN":"新增合同额度未确认，不能把未知额度当作无限额度。",
    "NEW_EXCEEDS_LIMIT":"新增承诺超过你填写的剩余合同额度。",
    "MINIMUM_FULFILLMENT_EXCEEDED":"在声明的少发范围内，合同承诺超过可履约量；默认研究约束排除此候选。",
    "EXISTING_OVERCOMMITMENT":"已有合同已超过基准可承诺量；原合同不会因此消失。",
    "SHORTFALL_CONDITIONAL":"部分联合情况下有履约缺额，补偿未评价；此处只能作有限分项的条件排名。",
    "MECHANISM_MONEY_UNKNOWN":"机制差价未完全评价；全部候选只比较同一已知科目集合。",
}


def proposed_candidates(request, basis):
    proposals, seen = [],{}
    choices = [(quantity(a*basis.new_available_mwh),CandidateLabel("coverage",a,
                "不新增合约" if a == 0 else f"新增剩余可承诺量的{text(a*100)}%")) for a in FRACTIONS]
    if request.custom_new_mwh is not None:
        choices.append((quantity(request.custom_new_mwh),CandidateLabel("custom",None,"手填新增量")))
    for q,label in choices:
        if q not in seen:
            seen[q] = len(proposals)
            proposals.append((q,[label]))
        else:
            proposals[seen[q]][1].append(label)
    return tuple((q,tuple(labels)) for q,labels in proposals)


def role_index(request, role):
    return next(i for i,s in enumerate(request.scenarios) if role in s.aliases)


def evaluate_candidate(request, basis, new, labels, components, zero_rows):
    rows = tuple(evaluate_scenario(request,i,new,components) for i in range(len(request.scenarios)))
    failures, warnings = [],[]
    if new > basis.new_available_mwh:
        failures.append("NEW_EXCEEDS_BASE_REMAINDER")
    if request.new_contract_limit_mode == "unknown":
        failures.append("NEW_LIMIT_UNKNOWN")
    elif request.new_contract_limit_mode == "known_remaining" and new > request.new_contract_limit_mwh:
        failures.append("NEW_EXCEEDS_LIMIT")
    if request.enforce_minimum_fulfillment and basis.existing_contract_mwh+new > basis.minimum_nonmechanism_mwh:
        failures.append("MINIMUM_FULFILLMENT_EXCEEDED")
    if basis.existing_overcommitment_mwh > 0:
        warnings.append("EXISTING_OVERCOMMITMENT")
    if any(r.fulfillment_shortfall_mwh > 0 for r in rows):
        warnings.append("SHORTFALL_CONDITIONAL")
    if request.mechanism.mode != "not_applicable_assumed" and "mechanism_difference" not in components:
        warnings.append("MECHANISM_MONEY_UNKNOWN")
    base_i = role_index(request,("base","base"))
    amounts = tuple(r.evaluation.evaluated_contribution for r in rows)
    base = amounts[base_i]
    minimum = min(a.value_yuan for a in amounts)
    worst = tuple(i for i,a in enumerate(amounts) if a.value_yuan == minimum)
    ratio = None if basis.new_available_mwh == 0 or new > basis.new_available_mwh else quantity(new/basis.new_available_mwh)
    codes = tuple(failures+warnings)
    candidate = GenerationCandidate(new,ratio,not failures,components,base,money(minimum),codes,
                                    tuple(r.evaluation for r in rows))
    zero_amounts = tuple(r.evaluation.evaluated_contribution.value_yuan for r in zero_rows)
    cards = []
    for key,role in (("正常情况",("base","base")),("少发但价格通常",("low","base")),
                     ("发电正常但价格下跌",("base","low")),("发电正常但价格上涨",("base","high"))):
        i = role_index(request,role)
        cards.append((key,i,amounts[i]))
    cards.append(("全部联合情况下的最低测算金额",worst[0],money(minimum)))
    return CandidateAssessment(candidate,labels,quantity(new/basis.base_net_mwh),rows,base_i,worst,tuple(cards),
        money(base.value_yuan-zero_amounts[base_i]),money(minimum-min(zero_amounts)),
        tuple(money(a.value_yuan-b) for a,b in zip(amounts,zero_amounts)),
        tuple(REASON_ZH[c] for c in codes) or ("在本次声明条件下可参与研究比较，不代表真实交易资格已验证。",))


@dataclass(frozen=True)
class Selection:
    preference: str
    candidate_index: int | None
    objective: Amount
    near_tie_indices: tuple[int, ...]
    reason_zh: str


def select(assessments, preference):
    values = [(i,a.candidate.baseline_amount.value_yuan if preference == "base"
               else a.candidate.minimum_scenario_amount.value_yuan)
              for i,a in enumerate(assessments) if a.candidate.recommendation_eligible]
    if not values:
        return Selection(preference,None,Amount(AmountStatus.NOT_EVALUABLE,None),(),
                         "没有满足共同研究约束的候选，不会自动放宽限制或忽略未知条件。")
    top = max(v for _,v in values)
    ties = tuple(i for i,v in values if top-v <= RANK_TOLERANCE_YUAN)
    index = min(ties,key=lambda i:(assessments[i].candidate.new_contract_mwh,i))
    score = next(v for i,v in values if i == index)
    reason = "优先正常情景金额，不是假定真实发生概率。" if preference == "base" else "优先这些联合情况中的最低金额，不保证真实最坏情况已被覆盖。"
    if len(ties) > 1:
        reason += "金额相差不超过0.01元，按较少新增承诺和稳定顺序选择，不宣称唯一最优覆盖率。"
    return Selection(preference,index,money(score),ties,reason)


def selection_notes(assessments, base, robust):
    """Explain selected and non-selected candidates, not only feasibility."""
    result = []
    for i,a in enumerate(assessments):
        notes = []
        for chosen in (base,robust):
            label = "正常金额优先" if chosen.preference == "base" else "最低联合金额优先"
            if not a.candidate.recommendation_eligible:
                notes.append(label+"：未纳入选择，原因见本候选的约束说明；测算结果仍保留。")
            elif chosen.candidate_index is None:
                notes.append(label+"：尚无可选择结果，不自动忽略条件。")
            elif i == chosen.candidate_index:
                notes.append(label+"：在本次可比较集合和0.01元并列口径下选中。")
            elif i in chosen.near_tie_indices:
                notes.append(label+"：金额相差不超过0.01元，按较少新增承诺和稳定顺序未选此档。")
            else:
                value = a.candidate.baseline_amount if chosen.preference == "base" else a.candidate.minimum_scenario_amount
                gap = chosen.objective.value_yuan-value.value_yuan
                notes.append(label+f"：该指标比选中方案少{text(gap)}元，所以未选此档；不是现实结果保证。")
        result.append(replace(a,selection_notes_zh=tuple(notes)))
    return tuple(result)


@dataclass(frozen=True)
class GenerationAdvice:
    available: bool
    selected_index: int | None
    new_contract_mwh: Decimal | None
    headline_zh: str
    explanation_zh: tuple[str, ...]
    technical_reason_codes: tuple[str, ...]


def assumptions(request):
    lines = ["预计电量是用户给定的净上网研究值；未绑定真实风场、厂内功率或正式计量。",
             "少发/多发是手填压力范围，不是统计置信区间；所有合同在压力下保持不变。",
             "研究月份与规则参考日分开记录，不认证真实历史可执行资格。"]
    if request.mechanism.mode == "not_applicable_assumed":
        lines.append("本情景明确假设机制不适用，不计算机制补差；不表示真实浙江风场没有资格。")
    elif request.mechanism.mode == "ratio_assumed":
        lines.append(f"机制量按研究比例{text(request.mechanism.ratio*100)}%计算，不是独立于市场交易的物理电量桶。")
    else:
        lines.append("机制资格或数量未知，不能按全发电量自动生成覆盖推荐。")
    if request.mechanism.mode == "ratio_assumed":
        lines.append("机制额度在本范围明确假设不触顶。" if request.mechanism.cap_mode == "not_binding_assumed"
                     else ("机制剩余额度未知。" if request.mechanism.cap_mode == "unknown"
                           else f"机制剩余额度为{text(request.mechanism.remaining_cap_mwh)}MWh。"))
    lines.append("资产与交付价格采用同价代理；机制参考价没有被自动设为相同。" if request.price_linkage == "asset_delivery_same_assumed"
                 else ("三类价格明确采用同步同价代理。" if request.price_linkage == "all_same_assumed" else "资产、交付与机制参考价单独填写，不抹平基差。"))
    lines.append("不新增超过声明最少可履约量的承诺，是本工具研究约束，不是浙江政策限制。"
                 if request.enforce_minimum_fulfillment else "已关闭少发安全约束；有缺额的排序只能看已评价分项，不能直接签约。")
    lines.append("环境价值、履约补偿、其他费用、正式逐时结算和完整利润未计算。")
    return tuple(lines)


def explain(request, basis, assessments, base, robust):
    chosen = base if request.risk_preference == "base" else robust
    if chosen.candidate_index is None:
        reasons = tuple(dict.fromkeys(reason for a in assessments for reason in a.reasons_zh))
        return GenerationAdvice(False,None,None,"暂不能给出新增合约方向",(chosen.reason_zh,*reasons,BOUNDARY_ZH),
                                ("NO_ELIGIBLE_RESEARCH_CANDIDATE",))
    a = assessments[chosen.candidate_index]
    c = a.candidate
    lines = [f"本次选择新增{text(c.new_contract_mwh)}MWh，占总预测量{text(a.new_share_of_total_forecast*100)}%；已有{text(basis.existing_contract_mwh)}MWh另行保留。",
             f"覆盖率的基数是扣除研究机制量和已有承诺后的{text(basis.new_available_mwh)}MWh，不是所有发电量。",
             f"相对不新增合约，正常情况金额差为{text(a.baseline_vs_no_add_yuan.value_yuan)}元；全部联合情况的最低金额差为{text(a.minimum_vs_no_add_yuan.value_yuan)}元。",
             f"本方案在全部联合情况中的最低测算金额为{text(c.minimum_scenario_amount.value_yuan)}元；它不是最大可能亏损。",
             chosen.reason_zh]
    lo_i,hi_i = role_index(request,("base","low")),role_index(request,("base","high"))
    lines.append(f"相对不新增，在正常发电且现货下跌时金额差为{text(a.per_scenario_vs_no_add_yuan[lo_i].value_yuan)}元；上涨时为{text(a.per_scenario_vs_no_add_yuan[hi_i].value_yuan)}元。这体现锁价的保护和机会成本。")
    if base.candidate_index is not None and robust.candidate_index is not None:
        b,r = assessments[base.candidate_index].candidate,assessments[robust.candidate_index].candidate
        lines.append(f"稳健选择相对中性选择：最低情景金额差{text(r.minimum_scenario_amount.value_yuan-b.minimum_scenario_amount.value_yuan)}元，正常情景金额差{text(r.baseline_amount.value_yuan-b.baseline_amount.value_yuan)}元。")
        if base.candidate_index == robust.candidate_index:
            lines.append("两种偏好在本次条件下选择相同，取舍差额确实为0，没有额外稳定性收益。")
    lines.extend(a.reasons_zh)
    lines.append(BOUNDARY_ZH)
    return GenerationAdvice(True,chosen.candidate_index,c.new_contract_mwh,"按这些研究条件，选择新增合约量",tuple(lines),
                            ("FINITE_SCENARIO_RANKING",)+c.reason_codes)


@dataclass(frozen=True)
class GenerationCalculation:
    output: GenerationOutput
    quantity_basis: QuantityBasis
    assessments: tuple[CandidateAssessment, ...]
    baseline_selection: Selection
    robust_selection: Selection
    advice: GenerationAdvice
    assumptions_zh: tuple[str, ...]
    diagnostic_rows: tuple[ScenarioDetail, ...]
    scenario_month: str
    rule_reference_date: str
    subject_scenario: str
    rule_relation: str
    unique_scenario_count: int
    engine_version: str = ENGINE_VERSION
    historical_result: bool = False
    actual_execution_confirmed: bool = False
    ranking_certifies_real_contract_eligibility: bool = False
    environment_value: Amount = Amount(AmountStatus.NOT_MODELLED, None)
    compensation: Amount = Amount(AmountStatus.NOT_MODELLED, None)


def calculate_generation(request, *, run_id, computed_at_utc):
    request = validated_request(request)
    with localcontext() as ctx:
        ctx.prec = 50
        basis,components = quantity_basis(request),common_components(request)
        zero_rows = tuple(evaluate_scenario(request,i,ZERO,components) for i in range(len(request.scenarios)))
        assessments = () if basis.new_available_mwh is None else tuple(
            evaluate_candidate(request,basis,q,labels,components,zero_rows)
            for q,labels in proposed_candidates(request,basis))
        base,robust = select(assessments,"base"),select(assessments,"robust")
        assessments = selection_notes(assessments,base,robust)
        advice = explain(request,basis,assessments,base,robust)
        if basis.new_available_mwh is None:
            advice = GenerationAdvice(False,None,None,"机制数量未确认，暂不推荐新增合约",(
                "仅保留原合同和可评价的市场分项；没有把机制量当0，也没有按全发电量换基数。",BOUNDARY_ZH),
                ("MECHANISM_QUANTITY_UNKNOWN",))
        status = RunStatus.OPTIMAL if advice.available else RunStatus.UNRESOLVED
        metadata = ResultMetadata("generation",request.input_sha256,status,run_id,computed_at_utc,components,
                                  tuple(c for c in ("mechanism_difference","environment_value","compensation","fees","full_profit")
                                        if c not in components))
        return GenerationCalculation(GenerationOutput(metadata,tuple(a.candidate for a in assessments)),basis,assessments,
            base,robust,advice,assumptions(request),zero_rows if not assessments else (),request.scenario_month,
            request.rule_reference_date.isoformat(),request.subject_scenario,request.rule_relation,len(request.scenarios))
