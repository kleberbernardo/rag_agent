"""Domain decoupling: the corpus is configuration, never a name written in code.

These tests exist to stop a regression that already happened once — a product
name hardcoded in the system prompt and in the search tool's description,
which made the agent claim a domain the indexed documents did not have.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_agent.config import get_settings
from rag_agent.prompts import build_search_tool_description, build_system_prompt
from rag_agent.tools import build_search_tool, build_tools

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture
def domain(monkeypatch: pytest.MonkeyPatch) -> str:
    """Configure a domain that could never be a leftover literal in the code."""
    value = "regulação do mercado de capitais brasileiro"
    monkeypatch.setenv("KNOWLEDGE_DOMAIN", value)
    get_settings.cache_clear()
    return value


class TestSystemPrompt:
    def test_carries_the_configured_domain(self, domain: str) -> None:
        assert domain in build_system_prompt()

    def test_follows_the_domain_when_it_changes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KNOWLEDGE_DOMAIN", "normas contábeis")
        get_settings.cache_clear()
        first = build_system_prompt()

        monkeypatch.setenv("KNOWLEDGE_DOMAIN", "políticas de segurança")
        get_settings.cache_clear()
        second = build_system_prompt()

        assert first != second
        assert "normas contábeis" in first
        assert "políticas de segurança" in second

    def test_keeps_the_grounding_rules(self, domain: str) -> None:
        prompt = build_system_prompt()

        assert "search_documentation" in prompt
        assert "não encontrei isso na documentação" in prompt
        assert "calculate" in prompt

    def test_leaves_no_unfilled_placeholder(self, domain: str) -> None:
        assert "{" not in build_system_prompt()


class TestSearchToolDescription:
    def test_carries_the_configured_domain(self, domain: str) -> None:
        assert domain in build_search_tool_description()

    def test_reaches_the_tool_the_model_actually_sees(self, domain: str) -> None:
        assert domain in build_search_tool().description

    def test_reaches_the_registry(self, domain: str) -> None:
        descriptions = " ".join(tool.description for tool in build_tools())

        assert domain in descriptions

    def test_leaves_no_unfilled_placeholder(self, domain: str) -> None:
        assert "{" not in build_search_tool_description()


class TestRegistry:
    def test_registers_both_tools(self, domain: str) -> None:
        assert {tool.name for tool in build_tools()} == {"search_documentation", "calculate"}

    def test_every_tool_describes_itself(self, domain: str) -> None:
        assert all(tool.description.strip() for tool in build_tools())


class TestNoHardcodedDomain:
    """The literal that caused the regression must never come back."""

    def test_source_never_names_the_old_product(self) -> None:
        offenders = [
            path.relative_to(SOURCE_ROOT)
            for path in SOURCE_ROOT.rglob("*.py")
            if "nimbus" in path.read_text(encoding="utf-8").lower()
        ]

        assert offenders == []

    def test_default_domain_is_generic(self) -> None:
        assert get_settings().knowledge_domain == "a documentação interna da organização"
