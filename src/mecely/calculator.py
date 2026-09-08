from __future__ import annotations

import ast
import operator
import re


class CalculationError(ValueError):
    pass


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_SUFFIXES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
_PERCENT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%")
_SUFFIX = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*([kKmMbB])\b")


def _normalize(expression: str) -> str:
    expression = _PERCENT.sub(r"(\1 / 100)", expression)
    return _SUFFIX.sub(lambda match: f"({match.group(1)} * {_SUFFIXES[match.group(2).lower()]})", expression)


def _evaluate_node(node: ast.AST, variables: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate_node(node.body, variables)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return float(node.value)
    if isinstance(node, ast.Name):
        try:
            return float(variables[node.id])
        except KeyError as error:
            raise CalculationError(f"Variável desconhecida: {node.id}") from error
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left, variables)
        right = _evaluate_node(node.right, variables)
        try:
            return float(_BINARY_OPERATORS[type(node.op)](left, right))
        except (ArithmeticError, OverflowError) as error:
            raise CalculationError(str(error)) from error
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return float(_UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand, variables)))
    raise CalculationError("Expressão não permitida")


def evaluate(expression: str, variables: dict[str, float] | None = None) -> float:
    variables = variables or {}
    try:
        parsed = ast.parse(_normalize(expression), mode="eval")
    except SyntaxError as error:
        raise CalculationError("Expressão inválida") from error
    return _evaluate_node(parsed, variables)


def format_number(value: float) -> str:
    magnitude = abs(value)
    for threshold, suffix in ((1_000_000_000, "b"), (1_000_000, "m"), (1_000, "k")):
        if magnitude >= threshold:
            return f"{value / threshold:.4g}{suffix}"
    return f"{value:.10g}"
