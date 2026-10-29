"""Tavily web search tool for the managed research agent.

Self-contained on purpose: `mda deploy` archives this project directory as the
build root, so it cannot import the workshop's `utils/` package (that lives
outside the root). This is a trimmed port of `utils/search.py` — the retry +
canned-fallback plumbing stays local so the agent still answers during a
workshop with a flaky network.

The `@tool` decorator stays at the call site so the tool's name, docstring, and
signature remain visible to the reader.
"""

from __future__ import annotations

import time
from typing import Optional

from langchain_core.tools import tool
from tavily import TavilyClient

# Canned fallbacks keyed by lowercase substrings, shaped like Tavily results.
# Order matters: more specific keys first.
_FALLBACKS: list[tuple[tuple[str, ...], str]] = [
    (
        ("langchain vs langgraph", "difference between langchain and langgraph"),
        "**LangChain vs LangGraph**\nhttps://docs.langchain.com/oss/python/concepts/products\n"
        "LangChain provides high-level agent/chain abstractions; LangGraph is the lower-level "
        "stateful runtime they compile to. Use LangChain for a quick ReAct agent, LangGraph for "
        "custom state, multi-agent topologies, or fine-grained control of the execution loop.",
    ),
    (
        ("managed deep agent", "mda"),
        "**Managed Deep Agents**\nhttps://docs.langchain.com/langsmith/managed-deep-agents-quickstart\n"
        "A hosted runtime for code-first Deep Agents in LangSmith. You author an agent as a "
        "directory, test it with `mda dev`, and ship it with `mda deploy`. The runtime manages the "
        "backend, store, checkpointer, memory, skills, and system prompt for you.",
    ),
    (
        ("langsmith",),
        "**LangSmith**\nhttps://docs.smith.langchain.com/\n"
        "A framework-agnostic platform for tracing, evaluating, and monitoring LLM applications.",
    ),
]

_GENERIC_FALLBACK = (
    "**Search temporarily unavailable**\nhttps://fallback.example/no-results\n"
    "The web search service didn't return results. Use what you already know; if information is "
    "missing, say so plainly rather than guessing."
)

# Lazy singleton — instantiated once on first call, then reused.
_client: Optional[TavilyClient] = None


def _pick_fallback(query: str) -> str:
    q = query.lower()
    for keys, text in _FALLBACKS:
        if any(k in q for k in keys):
            return text
    return _GENERIC_FALLBACK


@tool(parse_docstring=True)
def tavily_search(query: str) -> str:
    """Search the web for information on a given query.

    Args:
        query: Search query to execute.
    """
    global _client
    if _client is None:
        _client = TavilyClient()  # reads TAVILY_API_KEY from the environment

    last_error: Exception | None = None
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            hits = _client.search(query, max_results=3).get("results", [])
            if hits:
                return "\n\n".join(
                    f"**{h['title']}**\n{h['url']}\n{h['content']}" for h in hits
                )
            last_error = RuntimeError("Tavily returned 0 results")
        except Exception as exc:  # noqa: BLE001 — fall back on any Tavily failure
            last_error = exc
            if attempt < max_retries:
                time.sleep(1.0 * (attempt + 1))  # linear backoff

    notice = f"[fallback content; live search unavailable -- {type(last_error).__name__}]\n\n"
    return notice + _pick_fallback(query)
