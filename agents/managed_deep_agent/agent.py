"""Managed Deep Agent — the Module 3 research agent, hosted on MDA.

Same agent as `agents/deep_agent/` (tavily search + a research subagent + skills
+ memory), ported from the open-source `create_deep_agent` harness to the managed
`define_deep_agent` surface. The contrast is what's *missing* here: `backend`,
`store`, `checkpointer`, `memory`, `skills`, and the system prompt are managed
fields the runtime injects — so they are declared by file location
(`instructions.md`, `skills/`, `memory.py`) rather than wired up by hand.

Model: gateway-routed OpenAI, configured inline. MDA scaffolds to Anthropic by
default; this is the "using another provider" path. Routing through the LangSmith
Gateway's `base_url` keeps the agent governed by the same workspace policies as
Module 3 (PII / secrets redaction). `LANGSMITH_API_KEY_GATEWAY` is the gateway
credential under a non-reserved name (the platform strips `LANGSMITH_API_KEY`).
"""

import os

from langchain.chat_models import init_chat_model
from managed_deepagents import define_deep_agent

from tools.search import tavily_search

model = init_chat_model(
    model="gpt-5.6-terra",
    model_provider="openai",
    base_url="https://gateway.smith.langchain.com/openai",
    use_responses_api=True,
    api_key=os.environ["LANGSMITH_API_KEY_GATEWAY"],
)

agent = define_deep_agent(
    name="managed-research-assistant",
    model=model,
    tools=[tavily_search],
    subagents=[
        {
            "name": "research-agent",
            "description": "Delegate research tasks. Give one topic at a time.",
            "system_prompt": "You are a research assistant. Use tools to gather "
            "information and cite sources. Limit to 3 search calls.",
            "tools": [tavily_search],
        }
    ],
)
