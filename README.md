# Modular Workshops

This repository contains hands-on tutorials for learning LangChain, LangGraph, and Deep Agents.

This is a condensed version of LangChain Academy, intended to be run in a session with a LangChain engineer. If you're interested in going into more depth, or working through tutorials on your own, check out [LangChain Academy](https://academy.langchain.com/courses/intro-to-langgraph)! LangChain Academy has helpful pre-recorded videos from our LangChain engineers.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or pip

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment variables
cp .env.example .env
# Edit .env and fill in your keys
```

| Key | Required for | Get one |
|-----|--------------|---------|
| `OPENAI_API_KEY` | Modules 1-4 (default model) | <https://platform.openai.com> |
| `LANGSMITH_API_KEY` | Modules 3 & 4 (recommended for all) | <https://smith.langchain.com> |
| `LANGSMITH_API_KEY_GATEWAY` / `WORKSPACE_ID` | Module 3 §1 (LangSmith Gateway policies) | same key as `LANGSMITH_API_KEY`; workspace ID from LangSmith Settings → Workspace |
| `TAVILY_API_KEY` | Modules 1 & 3 (web search tool) | <https://tavily.com> |

```bash
# 3. Start Jupyter
uv run jupyter notebook
```

Open whichever module(s) your recipe calls for.

## Switching Models

All modules import `model` from `utils/models.py`. Change one line there to swap providers — no notebook edits required.

```python
# utils/models.py

# OpenAI (default)
model = init_chat_model("openai:gpt-5.6-terra", use_responses_api=True)

# Anthropic
# model = init_chat_model("anthropic:claude-sonnet-4-5")

# Azure OpenAI
# from langchain_openai import AzureChatOpenAI
# model = AzureChatOpenAI(azure_deployment="gpt-5.6-terra", streaming=True)

# AWS Bedrock
# from langchain_aws import ChatBedrockConverse
# model = ChatBedrockConverse(provider="anthropic", model_id="...")
```

`utils/models.py` also ships a commented-out **LangSmith Gateway** block. Module 3 §1.4 walks through flipping the default to it so every model call (notebooks *and* the deployed agent) is routed through the gateway and subject to workspace policies.

## Deploy + Govern (Module 3)

Module 3 first creates a workspace-level **LangSmith Gateway** policy (PII / secrets redaction), routes the model through the gateway, then deploys the agent at `agents/deep_agent/` to LangSmith via the `langgraph` CLI (installed by `uv sync`). The deploy config is `langgraph.json` at the workshop root.

Because `agents/deep_agent/agent.py` imports `model` from `utils.models`, whichever block is active in `utils/models.py` at deploy time is what ships — flip on the gateway block and the deployed agent inherits it with no extra flags.

Your `LANGSMITH_API_KEY` must have deployment permissions (use a `lsv2_sk_...` service key). The gateway block reads `LANGSMITH_API_KEY_GATEWAY` (the same key under a non-reserved name, since `langgraph deploy` strips `LANGSMITH_API_KEY` during upload).

## Engine (Module 5)

Module 5 introduces **LangSmith Engine** — it reads your deployed agent's production traces, clusters recurring failures into issues, diagnoses the root cause against your connected source code, and proposes fixes as GitHub PRs. It runs on the Module 3 deployment, driven through an *assistant* (a saved graph configuration) that swaps in a deliberately broken search tool so Engine has a clear, reproducible issue to find.

Engine's first analysis takes ~20 minutes, so it's best primed before a session. Needs the Module 3 deployment and a `LANGSMITH_API_KEY`.

## Managed Deep Agents (Module 6)

Module 6 ports the Module 3 deep agent from the self-hosted path (`create_deep_agent` + `langgraph deploy`) to a **Managed Deep Agent** — authored as a directory and shipped with the `mda` CLI, so the managed runtime provides the backend, store, checkpointer, memory, skills, and system prompt.

The ported project is `agents/managed_deep_agent/`: same tavily search, research subagent, skills, and memory, on the same gateway-routed OpenAI model as Module 3 (configured inline in its `agent.py`, since an `mda` project is a self-contained directory and can't import the workshop's `utils/`). HITL is dropped to keep the port focused.

Install the CLI once (`uv tool install --prerelease allow managed-deepagents`), then `mda dev agents/managed_deep_agent` to run it in Studio, or `mda deploy agents/managed_deep_agent` to host it. Reuses the existing `LANGSMITH_API_KEY`, `LANGSMITH_API_KEY_GATEWAY`, and `TAVILY_API_KEY`; the project has its own `pyproject.toml` (run `uv sync` inside it). MDA is in public beta on US LangSmith Cloud only.

## Project Structure

```
modular-workshops/
├── README.md                       (this file — recipes + setup)
├── pyproject.toml                  (shared dependencies)
├── .env.example
├── langgraph.json                  (registers agents/deep_agent for langgraph dev)
├── utils/
├── agents/
│   ├── research_agent.py           (shared agent factory — Module 1 references, Module 4 imports for eval)
│   ├── deep_agent/                 (deployable + governed agent for Module 3)
│   │   ├── agent.py
│   │   ├── AGENTS.md
│   │   └── skills/
│   │       ├── linkedin-post/SKILL.md
│   │       └── twitter-post/SKILL.md
│   └── managed_deep_agent/         (Managed Deep Agent — Module 6; self-contained mda project)
│       ├── agent.py                (define_deep_agent + inline gateway-routed model)
│       ├── instructions.md         (system prompt)
│       ├── tools/search.py
│       ├── skills/
│       ├── memory.py
│       ├── identity.py
│       ├── pyproject.toml          (own deps — run `uv sync` inside this dir)
│       └── .env.example
├── images/                         (diagrams used by the notebooks)
└── modules/
    ├── 01_deep_agents.ipynb        (Module 1)
    ├── 02_langgraph.ipynb          (Module 2)
    ├── 03_deploy_and_govern.ipynb  (Module 3)
    ├── 04_langsmith.ipynb          (Module 4)
    ├── 05_engine.ipynb             (Module 5)
    └── 06_managed_deep_agents.ipynb (Module 6)
```

## Common Issues

**`langgraph deploy` fails with 403 / permission denied**
Your API key is a personal token. Generate a service key (`lsv2_sk_...`) in LangSmith settings.

**Notebook can't find `utils` / `agents`**
Each module's setup cell prepends `project_root` (the workshop root) to `sys.path`. If you moved a notebook, update the `Path().resolve().parent` line to point at the workshop root.

## For LangChain Internal Users
Please refer to this linked [Notion document](https://app.notion.com/p/Modular-Workshops-37d808527b1780318063fd210446aa03?source=copy_link) for instructions on setup and usage.
