"""Tool registry.

A tool is a plain function the model may decide to call. The model never sees
the body -- only the name, the signature and the docstring. That docstring is
the contract, which is why it is written in the same language as the answers.

To add a tool: write it in its own module, then register it in TOOLS.
"""

from langchain_core.tools import BaseTool

from rag_agent.tools.calculator import calculate
from rag_agent.tools.documentation import search_documentation

TOOLS: list[BaseTool] = [search_documentation, calculate]

__all__ = ["TOOLS", "calculate", "search_documentation"]
