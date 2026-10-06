"""Shared serialization and money/result states, not shared asset business logic."""
from dataclasses import dataclass, is_dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import re

from . import (CORE_VERSION, INPUT_SCHEMA_VERSION, OUTPUT_SCHEMA_VERSION,
              STORAGE_MODEL_VERSION, GENERATION_MODEL_VERSION)
from .errors import require
from .numbers import MAX_ABS_AMOUNT, decimal_text, number


class AmountStatus(str, Enum):
    EVALUATED = "evaluated"
    UNKNOWN = "unknown"
    NOT_EVALUABLE = "not_evaluable"
    NOT_APPLICABLE = "not_applicable"
    NOT_MODELLED = "not_modelled"


class RunStatus(str, Enum):
    NOT_RUN = "not_run"
    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"
    TIME_LIMIT = "time_limit"
    SOLVER_ERROR = "solver_error"
    INPUT_INVALID = "input_invalid"
    UNRESOLVED = "unresolved"
    BUSY = "busy"


@dataclass(frozen=True)
class Amount:
    status: AmountStatus
    value_yuan: Decimal | None

    def __post_init__(self):
        require(isinstance(self.status, AmountStatus), "金额状态未登记。")
        if self.status is AmountStatus.EVALUATED:
            object.__setattr__(self, "value_yuan", number(self.value_yuan, minimum=-MAX_ABS_AMOUNT, maximum=MAX_ABS_AMOUNT))
        else:
            require(self.value_yuan is None, "未评价或不适用的金额必须保留为空，不能填零。")


def primitive(value):
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: primitive(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        require(all(isinstance(k, str) for k in value), "序列化参数名必须是文本。")
        return {k: primitive(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [primitive(v) for v in value]
    require(value is None or isinstance(value, (str, bool, int)), "仅允许规范值进入输入快照。")
    return value


def canonical(value):
    return json.dumps(primitive(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResultMetadata:
    """Output contract only. S1 does not produce computed runs."""
    case: str
    input_sha256: str
    status: RunStatus
    run_id: str
    computed_at_utc: datetime | None
    evaluated_components: tuple[str, ...] = ()
    unmodelled_components: tuple[str, ...] = ("full_profit",)
    domain: str = "sandbox"
    core_version: str = CORE_VERSION
    input_schema_version: int = INPUT_SCHEMA_VERSION
    output_schema_version: int = OUTPUT_SCHEMA_VERSION
    full_profit: Amount = Amount(AmountStatus.NOT_MODELLED, None)
    model_version: str | None = None

    def __post_init__(self):
        require(self.case in ("storage", "generation") and self.domain == "sandbox", "结果业务范围不正确。")
        expected_model = STORAGE_MODEL_VERSION if self.case == "storage" else GENERATION_MODEL_VERSION
        require(self.model_version is None or self.model_version == expected_model, "结果模型版本不匹配。")
        object.__setattr__(self, "model_version", expected_model)
        require(self.core_version == CORE_VERSION and self.input_schema_version == INPUT_SCHEMA_VERSION
                and self.output_schema_version == OUTPUT_SCHEMA_VERSION, "输入输出版本不匹配。")
        require(isinstance(self.status, RunStatus), "结果状态未登记。")
        require(isinstance(self.input_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", self.input_sha256), "输入指纹格式不正确。")
        require(isinstance(self.run_id, str) and re.fullmatch(r"[A-Za-z0-9-]{1,64}", self.run_id), "运行编号格式不正确。")
        require(self.full_profit == Amount(AmountStatus.NOT_MODELLED, None), "沙盒不能输出企业完整利润。")
        if self.status is RunStatus.NOT_RUN:
            require(self.computed_at_utc is None and not self.evaluated_components, "未运行不能伪装成已计算。")
        else:
            require(isinstance(self.computed_at_utc, datetime) and self.computed_at_utc.tzinfo is not None
                    and self.computed_at_utc.utcoffset().total_seconds() == 0, "计算时间必须明确记录为协调世界时。")


@dataclass(frozen=True)
class StorageStep:
    interval_start: datetime
    interval_end: datetime
    charge_power_mw: Decimal
    discharge_power_mw: Decimal
    stored_energy_before_mwh: Decimal
    stored_energy_after_mwh: Decimal
    remaining_throughput_mwh: Decimal
    contribution: Amount

    def __post_init__(self):
        require(isinstance(self.interval_start, datetime) and isinstance(self.interval_end, datetime)
                and self.interval_start.tzinfo is not None and self.interval_end.tzinfo is not None,
                "结果时段必须记录明确时区。")
        require((self.interval_end-self.interval_start).total_seconds() in (900, 1800, 3600), "结果时间粒度不正确。")
        for key in ("charge_power_mw", "discharge_power_mw", "stored_energy_before_mwh", "stored_energy_after_mwh", "remaining_throughput_mwh"):
            object.__setattr__(self, key, number(getattr(self, key), minimum=Decimal(0), maximum=Decimal("2000000")))
        require(not (self.charge_power_mw > 0 and self.discharge_power_mw > 0), "同一结果时段不能同时充放电。")
        require(isinstance(self.contribution, Amount), "时段金额必须有明确状态。")


@dataclass(frozen=True)
class StoragePlan:
    method: str
    status: RunStatus
    contribution: Amount
    optimality_proven: bool
    physical_check_passed: bool
    interval_rows: tuple[StorageStep, ...] = ()

    def __post_init__(self):
        require(self.method in ("optimized", "full_discharge_now", "wait_until", "no_operation"), "对照方法未登记。")
        require(isinstance(self.status, RunStatus), "方案状态未登记。")
        require(isinstance(self.contribution, Amount), "方案金额必须有明确状态。")
        require(type(self.optimality_proven) is bool and type(self.physical_check_passed) is bool, "校验结果不能用文字代替。")
        require(type(self.interval_rows) is tuple and len(self.interval_rows) <= 96
                and all(isinstance(row, StorageStep) for row in self.interval_rows), "结果时段必须使用已登记的结构。")
        if self.status is RunStatus.OPTIMAL:
            require(self.optimality_proven is True and self.physical_check_passed is True
                    and self.contribution.status is AmountStatus.EVALUATED, "建议必须经过最优性和物理检查。")
            require(bool(self.interval_rows), "已优化方案必须包含可复核的动作时段。")
        else:
            require(self.contribution.status is not AmountStatus.EVALUATED and not self.optimality_proven,
                    "失败或未运行不能显示已评价收益或声称最优。")


@dataclass(frozen=True)
class StorageOutput:
    metadata: ResultMetadata
    plans: tuple[StoragePlan, ...] = ()

    def __post_init__(self):
        require(isinstance(self.metadata, ResultMetadata), "输出必须绑定完整运行元数据。")
        require(self.metadata.case == "storage", "储能输出不能携带发电业务结果。")
        require(type(self.plans) is tuple and all(isinstance(p, StoragePlan) for p in self.plans), "储能方案不能传递任意字段字典。")
        if self.metadata.status is RunStatus.NOT_RUN:
            require(not self.plans, "未运行不能附带已生成的计划。")
        if self.metadata.status is RunStatus.OPTIMAL:
            require(any(p.method == "optimized" and p.status is RunStatus.OPTIMAL for p in self.plans), "成功输出缺少已验证优化方案。")


@dataclass(frozen=True)
class GenerationScenarioEvaluation:
    scenario_index: int
    net_energy_mwh: Decimal
    mechanism_energy_mwh: Decimal | None
    total_contract_mwh: Decimal
    market_energy: Amount
    existing_contract_difference: Amount
    new_contract_difference: Amount
    mechanism_difference: Amount
    evaluated_contribution: Amount

    def __post_init__(self):
        require(type(self.scenario_index) is int and 0 <= self.scenario_index < 9, "联合情况编号不正确。")
        for key in ("net_energy_mwh", "total_contract_mwh"):
            object.__setattr__(self, key, number(getattr(self, key), minimum=Decimal(0), maximum=Decimal("200000000")))
        if self.mechanism_energy_mwh is not None:
            object.__setattr__(self, "mechanism_energy_mwh", number(self.mechanism_energy_mwh, minimum=Decimal(0), maximum=self.net_energy_mwh))
        for key in ("market_energy", "existing_contract_difference", "new_contract_difference", "mechanism_difference", "evaluated_contribution"):
            require(isinstance(getattr(self, key), Amount), "联合情况金额必须逐项保留状态。")


@dataclass(frozen=True)
class GenerationCandidate:
    new_contract_mwh: Decimal
    coverage_ratio: Decimal | None
    recommendation_eligible: bool
    evaluated_components: tuple[str, ...]
    baseline_amount: Amount
    minimum_scenario_amount: Amount
    reason_codes: tuple[str, ...] = ()
    scenario_rows: tuple[GenerationScenarioEvaluation, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "new_contract_mwh", number(self.new_contract_mwh, minimum=Decimal(0), maximum=Decimal("100000000")))
        if self.coverage_ratio is not None:
            object.__setattr__(self, "coverage_ratio", number(self.coverage_ratio, minimum=Decimal(0), maximum=Decimal(1)))
        require(type(self.recommendation_eligible) is bool, "推荐资格必须明确。")
        require(isinstance(self.baseline_amount, Amount) and isinstance(self.minimum_scenario_amount, Amount), "候选金额必须有明确状态。")
        require(type(self.scenario_rows) is tuple and len(self.scenario_rows) <= 9
                and all(isinstance(row, GenerationScenarioEvaluation) for row in self.scenario_rows), "情景结果必须使用已登记的结构。")
        require(len({row.total_contract_mwh for row in self.scenario_rows}) <= 1, "不能在少发或涨价后改变已选合同量。")
        if self.recommendation_eligible:
            require(self.baseline_amount.status is AmountStatus.EVALUATED and self.minimum_scenario_amount.status is AmountStatus.EVALUATED,
                    "缺少同范围金额时不能推荐头寸。")
            require(bool(self.scenario_rows), "可推荐头寸必须包含可复核的联合情况。")


@dataclass(frozen=True)
class GenerationOutput:
    metadata: ResultMetadata
    candidates: tuple[GenerationCandidate, ...] = ()

    def __post_init__(self):
        require(isinstance(self.metadata, ResultMetadata), "输出必须绑定完整运行元数据。")
        require(self.metadata.case == "generation", "发电输出不能携带储能业务结果。")
        require(type(self.candidates) is tuple and all(isinstance(c, GenerationCandidate) for c in self.candidates), "发电候选不能传递任意字段字典。")
        if self.metadata.status is RunStatus.NOT_RUN:
            require(not self.candidates, "未运行不能附带已评价的候选。")
        require(len(self.candidates) <= 6, "候选不能超过五档及一个手填量。")
