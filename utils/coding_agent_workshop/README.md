# Module 6: Coding Agent Analytics — participant guide

Open [`06_coding_agent_analytics.ipynb`](../../modules/06_coding_agent_analytics.ipynb). This standalone workshop takes about 85 minutes, including a break. Module 4 is an optional reference.

Use Claude Code to fix and review a small Python application, then explore its activity in LangSmith:

- Inspect traces, threads, Skill invocations, and MCP tool calls.
- Evaluate response quality, task completion, and session outcomes.
- Compare skill usage, whole-turn cost, and quality in notebook rankings and a LangSmith dashboard.
- Query traces and threads from the terminal.

## Participant pre-work

1. Clone this repository and check out the workshop branch **`avi/coding-agent-analysis`**. Pull the full repository, including `utils/`. From the repository root, run:

   ```bash
   uv sync
   uv run python -m ipykernel install --user --name=venv --display-name "Python (modular-workshop)"
   uv run jupyter notebook
   ```

   Select **Python (modular-workshop)**. Python 3.12+ is required. `uv sync` creates `.venv` and installs the shared dependencies. After pulling notebook updates, restart the kernel and rerun setup.

2. Install and authenticate [Claude Code](https://code.claude.com/docs/en/setup). Confirm a short prompt works.
3. Install the official [LangSmith tracing plugin](https://docs.langchain.com/langsmith/trace-claude-code). Inside Claude Code:

   ```text
   /plugin marketplace add langchain-ai/langsmith-claude-code-plugins
   /plugin install langsmith-tracing@langsmith-claude-code-plugins
   /reload-plugins
   ```

   If it is already installed under an older marketplace alias, check `/plugin` before installing a duplicate.

4. Configure the root `.env` with your LangSmith connection settings:

   | Variable | Purpose |
   |---|---|
   | `LANGSMITH_API_KEY` | LangSmith authentication |
   | `LANGSMITH_ENDPOINT` | API URL, including any required `/api` prefix |
   | `LANGSMITH_WEB_URL` | UI URL; set this for self-hosted deployments |
   | `LANGSMITH_PROJECT` | Base project name |
   | `WORKSPACE_ID` | Workspace ID; `LANGSMITH_WORKSPACE_ID` takes precedence if set |

   Never paste a key into a notebook cell.

5. Set `participant_id` in notebook setup. It defaults to your OS username; use a unique ID if accounts are shared. The notebook appends it to the project name so your traces, evaluators, and dashboard use the same project.
6. Run Section 1.1 in the notebook, then paste its printed command into a terminal in the same environment to start Claude Code.
7. Install [LangSmith CLI](https://docs.langchain.com/langsmith/langsmith-cli) and [langsmith-skills](https://docs.langchain.com/langsmith/skills) for the closing exercise.

The tracing plugin records activity. The included workshop plugin supplies two skills, `workshop:fix-bug` and `workshop:review-change`, and two local MCP tools, `get_issue` and `get_acceptance_criteria`.

Ask Claude to invoke the skill in natural language, following the notebook prompts. Slash commands can expand it before the model runs and may not produce an LLM `Skill` call.

## Hosted judges

The notebook registers three evaluators: `output_quality`, `task_completion`, and `session_outcome`. Hosted judges run in LangSmith and require a provider secret in the selected workspace. A key in your local `.env` does not create that workspace secret.

| Provider | Notebook configuration | Required workspace secret |
|---|---|---|
| OpenAI | Default when Azure settings are absent | `OPENAI_API_KEY` |
| Azure OpenAI | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, and `AZURE_OPENAI_DEPLOYMENT_NAME` | `AZURE_OPENAI_API_KEY` |
| LangSmith Gateway | Set `judge_provider = "gateway"` | `LANGSMITH_API_KEY_GATEWAY` |

For Azure, use the deployment name configured for your endpoint; it may differ from the underlying model name. For a custom provider or APIM route, set `template_rule_id` to an existing working evaluator's rule ID to reuse its provider configuration. See `.env.example` for configuration names.

New activity receives feedback after registration. All three judges return numeric scores (`0`, `0.5`, or `1`) with explanations. They assess response quality, reported task completion, and the conversation's reported outcome. They do not independently verify repository changes or test execution; inspect the tool runs for that evidence. Session outcome arrives after the thread's inactivity interval.

Rerunning registration updates the same rules for future activity. Existing feedback keeps its original result. Local Skill-name extraction in Section 3.1 does not write feedback.

## Activity options

Start with Section 1 in a fresh kernel for each option.

| Option | Setting | What to do |
|---|---|---|
| Run Claude Code yourself | `activity_source = "live"` | Complete the inspection prompt, register evaluators, then follow the task prompts |
| Use a recorded session | `activity_source = "replay"` | Upload the inspection turn in Section 1 and the remaining turns in Section 4 after registering all three evaluators |
| Explore an existing project | `activity_source = "prepared"` | Enter the shared project name, run Sections 1–2, then Section 5; adjust `since` to include its traces |

Replay uses the [included recording](fixtures/README.md). Its messages, token counts, and costs describe the original activity; hosted judges generate new feedback. Allow time for ingestion and evaluation. Thread feedback still waits for inactivity after upload.

Replay progress is saved in `.module06/replay/`. Keep that state when resuming after a kernel restart or interrupted upload; completed stages are skipped. Use a new participant ID/project for a separate attempt.

Prepared mode reads existing traces and feedback without changing evaluators or dashboards. You can build notebook rankings and open the project's existing dashboard.

## The exercise

The notebook creates a fresh copy of `sample_repo/` for your changes.

Section 1.1 includes expandable views of the starting app, sample tasks, tests, and both skills. These show the supplied starting files, not your edited working copy. The tracing plugin records Skill invocations but omits the loaded skill instructions.

- **TASK-001:** fix overdue-task filtering without mutating the input. The starter tests include two expected failures.
- **TASK-002:** add stable oldest-first ordering and regression coverage. Passing the original tests does not establish this requirement.

Use both supplied skills and keep the same Claude session for the follow-up tasks. Inspect the issue criteria, edits, test results, and review in the trace.

## Reading the results

Skill and MCP counts come from actual tool executions. Cost and quality are grouped by the skills used within each turn; they describe the whole turn, not an individual skill's incremental cost or effect on quality.

Missing costs and scores are excluded from totals and averages. Use the costed-turn and scored-turn counts to understand coverage. A recorded zero is valid; an absent measurement is unknown. The quality chart averages `output_quality`; completion and session scores are available in the feedback table.

The dashboard link opens the last 24 hours. Align its time range with the notebook when comparing values. After new activity, rerun Section 5 from trace loading through chart saving to refresh the sample.

## When finished

Wait for the final turn's feedback, then run the notebook's last cell to pause the evaluator rules registered during your session. Your traces, feedback, and dashboards remain available. Rerunning registration re-enables the same rules.

## Troubleshooting

- **Wrong kernel:** select **Python (modular-workshop)** after registering it with `uv run python`.
- **Self-hosted setup error:** check both API and UI URLs in the root `.env`, then rerun setup.
- **No traces:** use the printed launch command, check `/plugin`, and confirm tracing is enabled for the session.
- **No Skill rows:** check the project and time window, ask Claude to invoke the supplied skill by name, then refresh. Parent-turn rows and tool-execution rows count different units.
- **One MCP row:** a matching-turn table can contain one row for a turn with several tool executions. Check the execution table too.
- **One thread:** expected for one Claude session. Send another prompt in the same session for another turn; start a new session for another thread.
- **Saved tracing key conflict:** use the settings path and variable name reported by the launcher to resolve the saved override so the root `.env` can supply the key.
- **Evaluator registration fails:** check the selected workspace, permissions, workspace provider secret, and model configuration. Keep the HTTP status and request ID if you need help; avoid sharing credentials or raw error bodies.
- **Missing feedback:** allow time for indexing, model processing, and thread inactivity. Check the project's evaluator page for execution errors.
- **Earlier text labels or N/A averages:** older completion/session feedback used categorical labels. Register the current numeric judges and generate fresh activity. Past labels are preserved and cannot contribute to numeric averages.
- **Missing charts:** open the printed dashboard link or select `Module 06 — <project name>`. Include the trace timestamps in the date range. Use **Prebuilt → Tools** for built-in tool charts.
- **Empty quality chart:** check the notebook's scored-turn counts, allow processing time, then refresh the dashboard.
- **Missing costs:** confirm the model has a pricing entry and inspect costed-turn coverage. Use the notebook cost ranking if the native cost chart is empty.
- **Totals differ:** align the time window and sample. Never add an aggregate root's cost to its child costs. Rerun analysis and chart cells after additional activity.
- **Query exceeds its bound:** narrow `since` or intentionally raise the limit; the helpers report an error instead of silently truncating results.
