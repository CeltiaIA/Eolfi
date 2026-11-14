"""Evaluación aritmética local, pequeña y segura para evidencia verificable."""
from __future__ import annotations

import ast
import re
from decimal import Decimal, InvalidOperation
from typing import Any


_CANDIDATE = re.compile(r"(?<![\w.])[-+]?(?:\d|\()[\d\s+*/()%-]*")
_MAX_EXPRESSION_CHARS = 128
_MAX_AST_NODES = 64
_MAX_ABSOLUTE_RESULT = 10**12


def arithmetic_evidence(text: Any) -> str | None:
    """Return evidence for the last bounded arithmetic expression, if any."""
    def evaluate(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return (1 if isinstance(node.op, ast.UAdd) else -1) * evaluate(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return left / right
            if isinstance(node.op, ast.FloorDiv): return left // right
            return left % right
        raise ValueError("operación no permitida")

    for candidate in reversed(_CANDIDATE.findall(str(text))):
        expression = candidate.strip()
        if len(expression) > _MAX_EXPRESSION_CHARS or not any(op in expression for op in ("+", "-", "*", "/", "%")):
            continue
        try:
            tree = ast.parse(expression, mode="eval")
            if sum(1 for _ in ast.walk(tree)) > _MAX_AST_NODES:
                continue
            value = evaluate(tree)
            if not isinstance(value, (int, float)) or abs(value) > _MAX_ABSOLUTE_RESULT:
                continue
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
            continue
        rendered = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
        return f"EVIDENCIA DE CALCULADORA LOCAL: {expression} = {rendered}."
    return None


def inventory_evidence(text: Any) -> str | None:
    """Derive an explicit Spanish inventory calculation only when unambiguous."""
    source = str(text)
    lots = re.findall(r"\blote\s+[\wáéíóúñ]+\s*:\s*(\d+)\s+unidades\s*,\s*(\d+)\s+defectuosas\b", source, re.I)
    reserve = re.search(r"\breserv(?:a|an|ar)[^.]{0,80}?\b(?:de\s+)?(\d+)\s+unidades\b", source, re.I)
    pack = re.search(r"\bpaquetes?\s+de\s+(\d+)\b", source, re.I)
    price = re.search(r"\bcada\s+paquete\s+se\s+vende\s+a\s+(\d+(?:[.,]\d+)?)\s+euros?\b", source, re.I)
    commission = re.search(r"\bcomisi[oó]n[^.]{0,80}?(\d+(?:[.,]\d+)?)\s*%", source, re.I)
    if not lots or not reserve or not pack:
        return None
    try:
        usable = sum(int(total) - int(defective) for total, defective in lots)
        remaining, size = usable - int(reserve.group(1)), int(pack.group(1))
        if remaining < 0 or size <= 0:
            return None
        packages, leftover = divmod(remaining, size)
        data: dict[str, Any] = {"utilizables": usable, "paquetes": packages, "sobrantes": leftover}
        if price:
            gross = Decimal(packages) * Decimal(price.group(1).replace(",", "."))
            data["bruto"] = float(gross)
            if commission:
                fee = gross * (Decimal(commission.group(1).replace(",", ".")) / Decimal(100))
                data["comision"], data["neto"] = float(fee), float(gross - fee)
    except (InvalidOperation, ValueError, ArithmeticError):
        return None
    import json
    return "EVIDENCIA DE INVENTARIO LOCAL: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "."


def numeric_evidence(text: Any) -> str | None:
    return inventory_evidence(text) or arithmetic_evidence(text)
