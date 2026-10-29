# Module 6 — Managed Deep Agents (Design)

**Date:** 2026-10-29
**Status:** Approved (pending spec review)

## Goal

Teach the jump from a **self-hosted deployment** (`create_deep_agent` +
`langgraph deploy`, Module 3) to a **Managed Deep Agent** (MDA:
`define_deep_agent` + `mda deploy`). The narrative is a side-by-side port:
the *same* research agent, the *same* governed OpenAI model, hosted on MDA's
managed runtime instead of a server the user operates.

Anchored on the MDA quickstart's "using another provider" angle — the workshop
runs on OpenAI (`openai:gpt-5.6-terra`), while MDA's default scaffold is
Anthropic, so configuring the provider explicitly is the focal point.

## Decisions (locked)

- **Form factor:** a new standalone module notebook `modules/06_managed_deep_agents.ipynb`
  plus a new self-contained project directory `agents/managed_deep_agent/`.
  Module 3 and its `langgraph deploy` story stay untouched.
- **Agent scope:** faithful 1:1 port of the Module 3 deep agent **minus HITL**
  (no `interrupt_on`). Carries the tavily_search tool, the `research-agent`
  subagent, the linkedin/twitter skills, memory, and instructions.
- **Model:** gateway-routed OpenAI, configured **inline in `agent.py`** (reusing
  the `utils/models.py` gateway block's shape). The managed agent stays governed,
  consistent with Module 3. The removed `--gateway` scaffold flag is called out.
- **Notebook style:** light on executable Python. Mostly markdown that *points
  at* the project files to read and shows the `mda …` commands to run in a
  terminal. The project directory is the real artifact; the notebook narrates it.
- **Deploy:** optional, mirroring Module 3 §2.5. `mda dev` is the core hands-on
  step; live `mda deploy` is a "run if you want" block.
- **Numbering:** `06` (Module 5 is Engine).

## Key constraint

`mda deploy` archives the project directory as its build root, so the project
**cannot import from the workshop's `utils/`** (that lives outside the root).
The managed project must be self-contained:

- Gateway model config lives **inline in `agent.py`**.
- The Tavily search tool + a trimmed resilient-fallback helper live in
  `tools/search.py` (ported from `utils/search.py`).

**Managed fields** (`backend`, `store`, `checkpointer`, `memory`, `skills`,
system prompt) are **not** set in `define_deep_agent` — the runtime injects them.
This is the headline contrast: the harness wired by hand in Module 3 becomes
managed infrastructure.

## File layout

```
agents/managed_deep_agent/        self-contained mda project (own root)
  agent.py                        define_deep_agent(name, model, tools, subagents)
                                  + inline gateway-routed OpenAI model
  instructions.md                 system prompt = Module 3 system_prompt + AGENTS.md
                                  workflow/rules, merged; memory path adapted to
                                  /memories/agent/
  tools/
    search.py                     tavily_search @tool + trimmed resilient fallback
  skills/
    linkedin-post/SKILL.md        copied verbatim from deep_agent
    twitter-post/SKILL.md         copied verbatim from deep_agent
  memory.py                       define_memory(scope="agent")
  identity.py                     define_identity(auth=auth.langsmith_api_key())  (mda init default)
  pyproject.toml                  own manifest (from mda init)
  .env.example                    names only: LANGSMITH_API_KEY, LANGSMITH_API_KEY_GATEWAY,
                                  OPENAI_API_KEY, TAVILY_API_KEY
  (no sandbox/ — deleted; agent needs only prompt + tools + memory)

modules/06_managed_deep_agents.ipynb
```

## Feature mapping (the teaching payload)

| Module 3 (`create_deep_agent`) | Module 6 (`define_deep_agent`) |
|---|---|
| `system_prompt=` + `memory=["./AGENTS.md"]` | `instructions.md` (always-on system prompt) |
| `tools=[tavily_search]` | `tools/search.py`, imported into `agent.py` |
| `skills=["./skills/"]` | `skills/<name>/SKILL.md` → Context Hub |
| `backend=CompositeBackend(routes={"/memories/": StoreBackend()})` | `memory.py` → managed `/memories/agent/` tree |
| `subagents=[{research-agent}]` | `subagents=[...]` (unchanged, author-set) |
| `interrupt_on={write,edit}` | dropped |
| `model` from `utils.models` gateway block | gateway-routed client **inline in `agent.py`** |

## Notebook narrative (~25 min, mirrors Module 3's shape)

1. **Why managed** — self-hosted vs managed trade-off and when to pick each
   (from the skill: custom routes / stronger isolation / non-US → `langgraph deploy`;
   otherwise MDA).
2. **Install the CLI** — `uv tool install --prerelease allow managed-deepagents`.
3. **An agent is a directory** — walk the file layout + the mapping table; point
   the reader at each file in `agents/managed_deep_agent/`.
4. **Using another provider** — MDA defaults to Anthropic; we configure the
   gateway-routed OpenAI client explicitly in `agent.py`. Note `--gateway` is gone.
5. **Run it locally** — `mda dev agents/managed_deep_agent` (Studio + hot reload);
   send a message, confirm the tool is called.
6. **Deploy (optional)** — `mda deploy agents/managed_deep_agent`.
7. **Recap** — self-hosted vs managed, feature by feature.

Cells are predominantly markdown with fenced shell blocks. Any Python shown is
illustrative (the `define_deep_agent` snippet) rather than executed against a
kernel, since the agent runs under `mda dev` / `mda deploy`, not in-notebook.

## Doc touch-ups

- `README.md`: add a "Managed Deep Agents (Module 6)" section and the new
  directory in Project Structure; list `06_managed_deep_agents.ipynb` in the
  modules tree.
- `.env.example`: no new keys required (reuses the existing four:
  `LANGSMITH_API_KEY`, `LANGSMITH_API_KEY_GATEWAY`, `OPENAI_API_KEY`,
  `TAVILY_API_KEY`).

## Build approach

Scaffold with `mda init` first, then port features in — so the committed project
matches what the CLI actually generates (correct `pyproject.toml`, `identity.py`,
default `.gitignore` for `.env`), rather than hand-authoring and drifting from
the current SDK surface. Verify authoring surfaces against the installed package
(`mda --help`) since the SDK moves quickly.

## Out of scope

- HITL / `interrupt_on`.
- Sandbox, channels (Slack), schedules, MCP servers, connections, evals,
  Supabase identity — mentioned only if they clarify the contrast; not built.
- Changes to Modules 1–5 or the existing `agents/deep_agent/`.
- Actually performing a live deployment as part of authoring (the deploy cell is
  optional/demonstrative).
```
