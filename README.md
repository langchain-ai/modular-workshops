# Modular Workshops

This repository contains hands-on tutorials for learning LangChain, LangGraph, and Deep Agents.

This is a condensed version of LangChain Academy, intended to be run in a session with a LangChain engineer. If you're interested in going into more depth, or working through tutorials on your own, check out [LangChain Academy](https://academy.langchain.com/courses/intro-to-langgraph)! LangChain Academy has helpful pre-recorded videos from our LangChain engineers.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or pip
- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) only if you plan to use Google Vertex AI

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment variables
cp .env.example .env
# Edit .env for the model provider you plan to use
```

| Key | Required for | Get one |
|-----|--------------|---------|
| `OPENAI_API_KEY` | Direct OpenAI model block | <https://platform.openai.com> |
| `LANGSMITH_API_KEY` | Modules 3 & 4 (recommended for all) | <https://smith.langchain.com> |
| `LANGSMITH_API_KEY_GATEWAY` / `WORKSPACE_ID` | Module 3 §1 (LangSmith Gateway policies) | same key as `LANGSMITH_API_KEY`; workspace ID from LangSmith Settings → Workspace |
| `GCP_PROJECT_ID` | Google Vertex AI model block | Your Google Cloud project ID |

The text-to-SQL module does not use Tavily, so `TAVILY_API_KEY` is not required. Later modules that demonstrate web search can use bundled fallback responses when it is not set.

Keep `.env` local and do not commit it.

```bash
# 3. Start Jupyter
uv run jupyter notebook
```

Open whichever module(s) your recipe calls for.

## Deep Agents: Text-to-SQL (Module 1)

Module 1 builds a Deep Agent that turns business questions into checked SQL and grounded answers. It runs against the bundled `data/chinook.db` fixture, which is opened read-only.

No database download, database server, BigQuery setup, or database credentials are required.

## Switching Models

All modules import `model` from `utils/models.py`. To switch providers, comment out the active `MODEL_SPEC` / `API_KEY_ENV` pair and uncomment the pair you want. Keep exactly one pair active; no notebook edits are required.

The file includes configurations for direct OpenAI, the LangSmith LLM Gateway, Anthropic, Azure OpenAI, Google Vertex AI, and AWS Bedrock.

For local Vertex AI development, first configure Application Default Credentials:

```bash
gcloud auth application-default login
```

Then set `GCP_PROJECT_ID` in `.env` and enable the Google Vertex AI block in `utils/models.py`. Region, model, temperature, thinking, and output-token settings are optional and documented in `.env.example`.

Module 3 §1.4 walks through enabling the **LangSmith Gateway** block so every model call—both notebooks and the deployed agent—is routed through the gateway and subject to workspace policies.

## Deploy + Govern (Module 3)

Module 3 first creates a workspace-level **LangSmith Gateway** policy (PII / secrets redaction), routes the model through the gateway, then deploys the agent at `agents/deep_agent/` to LangSmith via the `langgraph` CLI (installed by `uv sync`). The deploy config is `langgraph.json` at the workshop root.

Because `agents/deep_agent/agent.py` imports `model` from `utils.models`, whichever block is active in `utils/models.py` at deploy time is what ships — flip on the gateway block and the deployed agent inherits it with no extra flags.

Your `LANGSMITH_API_KEY` must have deployment permissions (use a `lsv2_sk_...` service key). The gateway block reads `LANGSMITH_API_KEY_GATEWAY` (the same key under a non-reserved name, since `langgraph deploy` strips `LANGSMITH_API_KEY` during upload).

## Engine (Module 5)

Module 5 introduces **LangSmith Engine** — it reads your deployed agent's production traces, clusters recurring failures into issues, diagnoses the root cause against your connected source code, and proposes fixes as GitHub PRs. It runs on the Module 3 deployment, driven through an *assistant* (a saved graph configuration) that swaps in a deliberately broken search tool so Engine has a clear, reproducible issue to find.

Engine's first analysis takes ~20 minutes, so it's best primed before a session. Needs the Module 3 deployment and a `LANGSMITH_API_KEY`.

## Project Structure

```
modular-workshops/
├── README.md                       (this file — recipes + setup)
├── pyproject.toml                  (shared dependencies)
├── .env.example
├── data/
│   ├── chinook.db                  (bundled read-only workshop database)
│   └── README.md                   (source and license information)
├── langgraph.json                  (registers agents/deep_agent for langgraph dev)
├── utils/
├── agents/
│   ├── research_agent.py           (shared research agent used by Module 4 evals)
│   └── deep_agent/                 (deployable + governed agent for Module 3)
│       ├── agent.py
│       ├── AGENTS.md
│       └── skills/
│           ├── linkedin-post/SKILL.md
│           └── twitter-post/SKILL.md
├── images/                         (diagrams used by the notebooks)
└── modules/
    ├── 01_deep_agents.ipynb        (Module 1 — Deep Agents text-to-SQL)
    ├── 02_langgraph.ipynb          (Module 2)
    ├── 03_deploy_and_govern.ipynb  (Module 3)
    └── 04_langsmith.ipynb          (Module 4)
```

## Common Issues

**`langgraph deploy` fails with 403 / permission denied**
Your API key is a personal token. Generate a service key (`lsv2_sk_...`) in LangSmith settings.

**Notebook can't find `utils` / `agents`**
Each module's setup cell prepends `project_root` (the workshop root) to `sys.path`. If you move a notebook, update its `project_root` discovery to point at the workshop root.

## For LangChain Internal Users
Please refer to this linked [Notion document](https://app.notion.com/p/Modular-Workshops-37d808527b1780318063fd210446aa03?source=copy_link) for instructions on setup and usage.
