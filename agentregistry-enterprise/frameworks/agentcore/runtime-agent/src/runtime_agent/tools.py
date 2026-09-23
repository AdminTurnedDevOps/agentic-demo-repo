"""Local tools for the AgentCore Runtime agent. No network calls."""

import ast
import operator
from datetime import datetime, timezone

from strands import tool

_BINOPS: dict[type[ast.operator], object] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], object] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return float(_BINOPS[type(node.op)](_eval(node.left), _eval(node.right)))  # type: ignore[operator]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return float(_UNARY[type(node.op)](_eval(node.operand)))  # type: ignore[operator]
    raise ValueError("only numbers and + - * / // % ** are allowed")


@tool
def current_time() -> str:
    """Return the current time in UTC as an ISO-8601 timestamp.

    Use this when the user asks for the time, the date, or "now".
    """
    return datetime.now(timezone.utc).isoformat()


@tool
def calculate(expression: str) -> str:
    """Evaluate one arithmetic expression.

    Args:
        expression: Numbers combined with + - * / // % ** and parentheses.
            Example: "(2 + 3) * 4".
    """
    try:
        value = _eval(ast.parse(expression, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError) as error:
        return f"cannot evaluate {expression!r}: {error}"
    if value.is_integer():
        return str(int(value))
    return str(value)
