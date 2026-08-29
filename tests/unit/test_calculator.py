"""Agent calculator: arithmetic accuracy and refusal of arbitrary code."""

from __future__ import annotations

import pytest

from rag_agent.tools import calcular


def evaluate(expression: str) -> str:
    """Invoke the tool the way the agent would."""
    return calcular.invoke({"expressao": expression})


class TestArithmetic:
    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("2 + 3", "5"),
            ("890 * 12", "10680"),
            ("(300 - 50) / 2", "125"),
            ("10 / 4", "2.5"),
            ("2 ** 10", "1024"),
            ("7 // 2", "3"),
            ("7 % 3", "1"),
            ("-5 + 2", "-3"),
            ("3.2 * 100", "320"),
        ],
    )
    def test_computes_correctly(self, expression: str, expected: str) -> None:
        assert evaluate(expression) == expected

    def test_whole_results_lose_the_trailing_zero(self) -> None:
        assert evaluate("10 / 2") == "5"


class TestSafety:
    @pytest.mark.parametrize(
        "expression",
        [
            "__import__('os').system('dir')",
            "open('secret.txt').read()",
            "exec('x=1')",
            "[].__class__",
            "lambda: 1",
            "x = 1",
        ],
    )
    def test_refuses_anything_that_is_not_arithmetic(self, expression: str) -> None:
        assert evaluate(expression).startswith("Não foi possível calcular")

    def test_refuses_huge_exponents(self) -> None:
        result = evaluate("2 ** 999999")

        assert "Expoente muito grande" in result

    @pytest.mark.parametrize("expression", ["1 / 0", "1 // 0", "1 % 0"])
    def test_refuses_division_by_zero(self, expression: str) -> None:
        assert "Divisão por zero" in evaluate(expression)


class TestErrorContract:
    def test_never_raises_so_the_agent_can_recover(self) -> None:
        assert isinstance(evaluate("2 +"), str)

    def test_explains_why_it_failed(self) -> None:
        assert evaluate("2 +").startswith("Não foi possível calcular")
