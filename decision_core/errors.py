"""Safe, deterministic diagnostics; no input values, paths or solver logs."""
from enum import Enum


class ErrorCode(str, Enum):
    INPUT_INVALID = "INPUT_INVALID"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    TIME_GRID_INVALID = "TIME_GRID_INVALID"
    ENGINEERING_LIMIT = "ENGINEERING_LIMIT"
    ASSUMPTION_REQUIRED = "ASSUMPTION_REQUIRED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class ContractError(ValueError):
    def __init__(self, code: ErrorCode, message: str):
        self.code = code
        super().__init__(message)


def require(condition, message, code=ErrorCode.INPUT_INVALID):
    if not condition:
        raise ContractError(code, message)


def exact_keys(value, required, optional=()):
    require(isinstance(value, dict), "输入必须是约定的参数对象。")
    keys = set(value)
    require(not keys - set(required) - set(optional), "存在未支持的参数，请使用规定的输入栏。", ErrorCode.UNKNOWN_FIELD)
    require(set(required) <= keys, "必要条件没有填全，请补充后再计算。")

