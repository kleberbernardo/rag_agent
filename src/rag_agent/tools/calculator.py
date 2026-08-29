"""Safe arithmetic evaluation, exposed as an agent tool.

The expression is parsed into a syntax tree and walked node by node against
an allow-list. Anything that is not plain arithmetic -- a function call, an
attribute access, an import -- is refused before evaluation, which is what
keeps a model-authored string from becoming arbitrary code execution.
"""

from __future__ import annotations

import ast
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_MAX_EXPONENT = 100

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.FloorDiv,
    ast.USub,
    ast.UAdd,
)


@tool
def calculate(expression: str) -> str:
    """Calcula uma expressão aritmética e devolve o resultado exato.

    Use SEMPRE que a resposta envolver conta -- soma, multiplicação,
    porcentagem, total anual. Modelos de linguagem erram aritmética;
    esta ferramenta não erra.

    Args:
        expression: expressão em notação Python. Ex: "890 * 12", "(300-50)/2".

    Returns:
        O resultado, ou uma mensagem explicando por que a expressão é inválida.
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _evaluate(tree)
    except (ValueError, SyntaxError, TypeError) as error:
        logger.warning("calculate(%r) failed: %s", expression, error)
        return f"Não foi possível calcular: {error}"

    return _format(result)


def _evaluate(node: ast.AST) -> float:
    """Walk the expression tree, refusing any node outside the allow-list."""
    if not isinstance(node, _ALLOWED_NODES):
        msg = f"Elemento não permitido na expressão: {node.__class__.__name__}"
        raise ValueError(msg)

    if isinstance(node, ast.Expression):
        return _evaluate(node.body)

    if isinstance(node, ast.Constant):
        return _evaluate_constant(node)

    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand)
        return -value if isinstance(node.op, ast.USub) else value

    if isinstance(node, ast.BinOp):
        return _evaluate_binary(node)

    msg = f"Operador não suportado: {node.__class__.__name__}"
    raise ValueError(msg)


def _evaluate_constant(node: ast.Constant) -> float:
    if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
        msg = "Só números são aceitos."
        raise ValueError(msg)
    return float(node.value)


def _evaluate_binary(node: ast.BinOp) -> float:
    left = _evaluate(node.left)
    right = _evaluate(node.right)
    operator = node.op

    if isinstance(operator, ast.Add):
        return left + right
    if isinstance(operator, ast.Sub):
        return left - right
    if isinstance(operator, ast.Mult):
        return left * right
    if isinstance(operator, (ast.Div, ast.FloorDiv, ast.Mod)):
        return _evaluate_division(operator, left, right)
    if isinstance(operator, ast.Pow):
        return _evaluate_power(left, right)

    msg = f"Operador não suportado: {operator.__class__.__name__}"
    raise ValueError(msg)


def _evaluate_division(operator: ast.operator, left: float, right: float) -> float:
    if right == 0:
        msg = "Divisão por zero."
        raise ValueError(msg)
    if isinstance(operator, ast.Div):
        return left / right
    if isinstance(operator, ast.FloorDiv):
        return left // right
    return left % right


def _evaluate_power(left: float, right: float) -> float:
    """Reject huge exponents: 2 ** 999999999 would exhaust memory."""
    if abs(right) > _MAX_EXPONENT:
        msg = f"Expoente muito grande (máximo {_MAX_EXPONENT})."
        raise ValueError(msg)
    return left**right


def _format(result: float) -> str:
    """Print 10680 rather than 10680.0, without losing real decimals."""
    if result.is_integer():
        return str(int(result))
    return f"{result:g}"
