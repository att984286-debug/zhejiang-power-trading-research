"""Bounded Decimal conversion. Limits are tool limits, never market rules."""
from decimal import Decimal, InvalidOperation, localcontext

from .errors import ContractError, ErrorCode, require

MAX_POWER_MW = Decimal("10000")
MAX_CAPACITY_MWH = Decimal("100000")
MAX_MONTH_ENERGY_MWH = Decimal("100000000")
MAX_ABS_PRICE = Decimal("1000000")
MAX_DEGRADATION = Decimal("100000")
MAX_CYCLES = Decimal("10")
MIN_EFFICIENCY = Decimal("0.01")
MAX_ABS_AMOUNT = Decimal("10000000000000000")


def number(value, *, minimum=None, maximum=None):
    require(not isinstance(value, bool), "数值不能填写成是或否。")
    require(isinstance(value, (str, int, float, Decimal)), "请填写有限数值。")
    if isinstance(value, str):
        require(0 < len(value) <= 64 and value.strip() == value, "数值格式或长度不符合要求。")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ContractError(ErrorCode.INPUT_INVALID, "请填写有限数值。") from None
    require(result.is_finite(), "缺失值、无穷和非数值不能进入测算。")
    # Bound the decimal representation before canonicalization / arithmetic.
    require(len(result.as_tuple().digits) <= 32 and -18 <= result.as_tuple().exponent <= 18,
            "数值精度超出本工具范围。", ErrorCode.ENGINEERING_LIMIT)
    require(minimum is None or result >= minimum, "数值低于允许范围。")
    require(maximum is None or result <= maximum, "数值超过本工具允许范围。", ErrorCode.ENGINEERING_LIMIT)
    return result


def price(value):
    return number(value, minimum=-MAX_ABS_PRICE, maximum=MAX_ABS_PRICE)


def ratio(value):
    return number(value, minimum=Decimal(0), maximum=Decimal(1))


def percent(value):
    with localcontext() as ctx:
        ctx.prec = 50
        return number(value, minimum=Decimal(0), maximum=Decimal(100)) / Decimal(100)


def decimal_text(value):
    value = value if isinstance(value, Decimal) else number(value)
    require(value.is_finite() and len(value.as_tuple().digits) <= 64 and abs(value.as_tuple().exponent) <= 96,
            "规范化后的数值无法安全序列化。")
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
