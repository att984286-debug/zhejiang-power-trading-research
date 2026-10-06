"""Storage request contract / normalization. No solver, prices fetched or files read."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

from .errors import ErrorCode, exact_keys, require
from .numbers import (MAX_CAPACITY_MWH, MAX_POWER_MW, MAX_CYCLES, MAX_DEGRADATION,
                      MIN_EFFICIENCY, decimal_text, number, price, ratio)
from .contracts import fingerprint, primitive

LOCAL = timezone(timedelta(hours=8))
INPUT_FIELDS = (
    "energy_capacity_mwh", "charge_power_limit_mw", "discharge_power_limit_mw",
    "current_soc_ratio", "min_soc_ratio", "max_soc_ratio", "terminal_soc_ratio",
    "charge_efficiency", "discharge_efficiency", "degradation_cost_yuan_per_mwh_throughput",
    "interval_minutes", "budget", "prices", "wait_until",
)


def timestamp(value):
    require(isinstance(value, str) and len(value) <= 32, "请填写明确的日期和时刻。", ErrorCode.TIME_GRID_INVALID)
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        require(False, "时间格式不正确。", ErrorCode.TIME_GRID_INVALID)
    require(result.tzinfo is not None and result.utcoffset() == timedelta(hours=8),
            "本工具时刻必须明确采用北京时间。", ErrorCode.TIME_GRID_INVALID)
    require(result.second == 0 and result.microsecond == 0, "时段不能包含秒或微秒。", ErrorCode.TIME_GRID_INVALID)
    require(2000 <= result.year <= 2100, "日期超出本工具研究范围。", ErrorCode.ENGINEERING_LIMIT)
    return result


@dataclass(frozen=True)
class PriceInterval:
    interval_start: datetime
    interval_end: datetime
    forecast_price_yuan_per_mwh: Decimal


@dataclass(frozen=True)
class BudgetRecord:
    source: str
    remaining_cycles: Decimal
    total_cycles: Decimal | None
    used_cycles: Decimal | None


def normalize_budget(value, capacity):
    exact_keys(value, ("mode",), ("remaining_cycles", "total_cycles", "used_cycles"))
    mode = value["mode"]
    if mode == "remaining":
        exact_keys(value, ("mode", "remaining_cycles"))
        remaining = number(value["remaining_cycles"], minimum=Decimal(0), maximum=MAX_CYCLES)
        record = BudgetRecord(mode, remaining, None, None)
    elif mode == "total_minus_used":
        exact_keys(value, ("mode", "total_cycles", "used_cycles"))
        total = number(value["total_cycles"], minimum=Decimal(0), maximum=MAX_CYCLES)
        used = number(value["used_cycles"], minimum=Decimal(0), maximum=MAX_CYCLES)
        require(used <= total, "已用充放额度不能超过今天总额度。")
        remaining = total - used
        record = BudgetRecord(mode, remaining, total, used)
    else:
        require(False, "请明确选择直接填剩余额度，或总额减去已用额度。")
    return 2 * capacity * remaining, record


@dataclass(frozen=True)
class StorageRequest:
    energy_capacity_mwh: Decimal
    charge_power_limit_mw: Decimal
    discharge_power_limit_mw: Decimal
    current_soc_ratio: Decimal
    min_soc_ratio: Decimal
    max_soc_ratio: Decimal
    terminal_soc_ratio: Decimal
    charge_efficiency: Decimal
    discharge_efficiency: Decimal
    degradation_cost_yuan_per_mwh_throughput: Decimal
    interval_minutes: int
    remaining_throughput_mwh: Decimal
    prices: tuple[PriceInterval, ...]
    wait_until: datetime | None
    budget_record: BudgetRecord

    @property
    def dt_hours(self):
        return Decimal(self.interval_minutes) / 60

    def business_payload(self):
        value = primitive(self)
        del value["budget_record"]  # Provenance differs; physical conditions do not.
        return value

    @property
    def input_sha256(self):
        return fingerprint(self.business_payload())

    def editable_payload(self):
        value = primitive(self)
        del value["remaining_throughput_mwh"]
        record = value.pop("budget_record")
        value["budget"] = {"mode": "remaining", "remaining_cycles": record["remaining_cycles"]}
        return value

    @classmethod
    def from_mapping(cls, value):
        exact_keys(value, INPUT_FIELDS)
        cap = number(value["energy_capacity_mwh"], minimum=Decimal("0.001"), maximum=MAX_CAPACITY_MWH)
        powers = [number(value[k], minimum=Decimal("0.001"), maximum=MAX_POWER_MW)
                  for k in ("charge_power_limit_mw", "discharge_power_limit_mw")]
        current, low, high, terminal = [ratio(value[k]) for k in
                                     ("current_soc_ratio", "min_soc_ratio", "max_soc_ratio", "terminal_soc_ratio")]
        require(low < high and low <= current <= high and low <= terminal <= high,
                "当前电量和结束目标都必须位于安全边界内。")
        charge_eff, discharge_eff = [number(value[k], minimum=MIN_EFFICIENCY, maximum=Decimal(1))
                                    for k in ("charge_efficiency", "discharge_efficiency")]
        cost = number(value["degradation_cost_yuan_per_mwh_throughput"], minimum=Decimal(0), maximum=MAX_DEGRADATION)
        interval = value["interval_minutes"]
        require(type(interval) is int and interval in (15, 30, 60), "计算时间间隔只能是15、30或60分钟。", ErrorCode.TIME_GRID_INVALID)
        throughput, record = normalize_budget(value["budget"], cap)
        rows = value["prices"]
        require(isinstance(rows, (list, tuple)) and 1 <= len(rows) <= 96, "价格表需要1至96个完整时段。", ErrorCode.ENGINEERING_LIMIT)
        clean = []
        delta = timedelta(minutes=interval)
        for row in rows:
            exact_keys(row, ("interval_start", "interval_end", "forecast_price_yuan_per_mwh"))
            start, end = timestamp(row["interval_start"]), timestamp(row["interval_end"])
            require(end - start == delta and (start.hour * 60 + start.minute) % interval == 0,
                    "每行起止时间必须与计算间隔对齐。", ErrorCode.TIME_GRID_INVALID)
            require(not clean or start == clean[-1].interval_end,
                    "时间重复、缺失或错序，不能进入测算。", ErrorCode.TIME_GRID_INVALID)
            clean.append(PriceInterval(start, end, price(row["forecast_price_yuan_per_mwh"])))
        first = clean[0].interval_start
        day_end = first.replace(hour=0, minute=0) + timedelta(days=1)
        require(all(r.interval_start.date() == first.date() and r.interval_end <= day_end for r in clean),
                "剩余计划只能覆盖同一天，最后边界可以为次日零点。", ErrorCode.TIME_GRID_INVALID)
        wait = None if value["wait_until"] is None else timestamp(value["wait_until"])
        require(wait is None or wait in {r.interval_start for r in clean} | {clean[-1].interval_end},
                "等待到的时刻必须是本次计划中的时段边界。", ErrorCode.TIME_GRID_INVALID)
        return cls(cap, *powers, current, low, high, terminal, charge_eff, discharge_eff,
                   cost, interval, throughput, tuple(clean), wait, record)


def normalize_storage(value):
    """All UI modes call this same boundary. No mode-specific formulas."""
    with localcontext() as ctx:
        ctx.prec = 50
        return StorageRequest.from_mapping(value)
