# Module 6 pre-work and presenter guide

Open [`06_coding_agent_analytics.ipynb`](../../modules/06_coding_agent_analytics.ipynb). It stands alone; Module 4 is an optional reference.

## Approved BMS delivery scope — October 1

For the October 1 workshop, the notebook focuses on local Skill extraction and three hosted root/thread evaluators. Hosted Skill labeling and selection scoring have been removed; no manual skips are needed.

Keep the main story: **observe a coding session, identify Skill/MCP activity, evaluate useful results, and compare usage, measured cost, and quality**. Finish with CLI inspection.

| Area | Current notebook |
|---|---|
| Tracing and skills | Inspect the model output, extract names locally in 3.1, query actual Skill/MCP tool spans and their parent turns, and inspect Threads |
| Hosted evaluation | Three rules: `output_quality`, `task_completion`, and `session_outcome`; session outcome is now 3.5 |
| Removed | Hosted `skill_name` labeling, `skill_selection` scoring, their output-index validation/fallback, and the old feedback-comparison tables |
| Exercise | Both supplied skills, local MCP tools, TASK-001 fix/review, and TASK-002 review/correction remain |
| Analysis and dashboards | Keep all three custom charts and participant dashboard creation: Skill invocations, total turn cost, mean turn quality; notebook comparison is now 5.1, dashboard creation 5.2, and MCP tools 5.3 |
| Terminal | CLI trace list, thread get, and the trace-analysis prompt remain |

Local extraction teaches how the requested skill appears in model output. Hosted decision-level suitability scoring is deferred. Usage counts and cost/quality groups read actual tool spans and root feedback; they require neither removed feedback key.

**Cost fallback:** the native cost chart was still blank at the end of the call despite priced traces. Keep chart creation and notebook cost coverage. If the native chart stays empty, show notebook costs/coverage and continue; one blank chart is acceptable for delivery.

**Recovery:** replay now requires the three retained evaluator names and has no output-index requirement. It still needs BMS verification. Prepared mode reads a verified existing project and skips writes; the presenter supplies both-skill activity, root/session feedback, known costs, and charts. Presenter follow-along remains the agreed setup fallback.

**Reused rehearsal projects:** removing cells does not disable rules already on BMS. Before reusing a project, the facilitator should inspect and pause its exact `module06-skill-name` and `module06-skill-selection` rule IDs separately. The notebook's final cell pauses only IDs successfully registered in the current kernel, including partial registration. It does not search for or disable other rules.

**Final rehearsal:** restart the kernel, run the three registrations, exercise both skills and TASK-002, wait for root/session feedback, save charts twice, check the date range and notebook cost coverage, run CLI cells, then pause the three registered IDs. Rerun registration after a kernel restart to recover the same IDs. Confirm ordinary Editor access before delivery.

The notebook keeps its 85-minute agenda, with time freed in the evaluator block for questions and setup recovery. For 80 minutes, shorten dashboard discussion by five minutes. Keep plugin evals, remote/BMS connectors, Chat, custom plugins, and newer-dashboard experiments as follow-on material; no new integrations are needed for this cut.

## Participant pre-work

1. Clone this repository and, for the October 1 BMS workshop, check out **`avi/coding-agent-analysis`**. Use the final revision shared by the presenter and pull the full repository, including `utils/`. From its root, run:

   ```bash
   uv sync
   uv run python -m ipykernel install --user --name=venv --display-name "Python (modular-workshop)"
   uv run jupyter notebook
   ```

   Select **Python (modular-workshop)**. Python 3.12+ is required. `uv sync` creates `.venv` and installs the shared dependencies, including LangSmith SDK 0.10.15 or later. The sample app and local MCP use only the standard library.

2. Install and authenticate [Claude Code](https://code.claude.com/docs/en/setup). Confirm a short prompt works.
3. Install the official [LangSmith tracing plugin](https://docs.langchain.com/langsmith/trace-claude-code). Inside Claude Code:

   ```text
   /plugin marketplace add langchain-ai/langsmith-claude-code-plugins
   /plugin install langsmith-tracing@langsmith-claude-code-plugins
   /reload-plugins
   ```

   If it is already installed under an older marketplace alias, check `/plugin` before installing a duplicate.

4. Reuse the root `.env`: `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT`, and `WORKSPACE_ID`. `LANGSMITH_WORKSPACE_ID`, if set, takes precedence. On self-hosted, set `LANGSMITH_WEB_URL` to the UI origin too. Ask the facilitator for the API URL, including any required `/api` prefix; the SDK accepts that prefix. Never paste a key into a notebook cell.
5. Set `participant_id` in notebook setup. It defaults to your OS username; use a unique ID if accounts are shared. The same project suffix is used by the SDK, launcher, CLI, evaluators, and dashboard. Self-hosted defaults to `chart_format = "legacy"`; SaaS uses `"v2"`.
6. Run setup and copy its launch command into a terminal. The launcher loads the root `.env` and the notebook's selections, keeping credentials in the process environment. It loads the supplied plugin with `claude --plugin-dir <absolute-plugin-path>`; no marketplace publication is needed.
7. Install [LangSmith CLI](https://docs.langchain.com/langsmith/langsmith-cli) and [langsmith-skills](https://docs.langchain.com/langsmith/skills) for the closing exercise. Remote MCP is optional.

The supplied skills are `workshop:fix-bug` and `workshop:review-change`. Both use `mcp__plugin_workshop_issues__get_issue` and `mcp__plugin_workshop_issues__get_acceptance_criteria`. Ask Claude to invoke the skill in natural language: slash commands can expand it before the model runs and may not produce an LLM `Skill` call.

## Hosted judges

Hosted judges run in LangSmith. A key in the local `.env` does not provision a workspace secret. The facilitator configures the provider credential once, before attendees register evaluators.

If the workshop uses a temporary APIM credential, the facilitator distributes it through the approved channel and rotates it after the session.

| Provider | Notebook configuration | LangSmith credential |
|---|---|---|
| Azure OpenAI | Existing `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, plus `AZURE_OPENAI_DEPLOYMENT_NAME` | Workspace secret `AZURE_OPENAI_API_KEY` |
| OpenAI | Shared `DEFAULT_JUDGE_MODEL` from `utils/langsmith_rules.py` | Workspace secret `OPENAI_API_KEY` |
| LangSmith Gateway | Set `judge_provider = "gateway"` | Workspace secret `LANGSMITH_API_KEY_GATEWAY` |
| Custom APIM/provider setup | Set `template_rule_id` to a working inline evaluator's rule UUID | Copies its serialized model and saved configuration reference |

Azure is selected when `AZURE_OPENAI_ENDPOINT` is set; otherwise the notebook selects OpenAI. Azure's **deployment name** is the required routing identifier. It need not equal the underlying model name. The supplied serializer omits temperature because support differs by deployment. BMS mentioned a `gpt-5.4` deployment; confirm that name, the endpoint, API version, and APIM authentication with the facilitator. Placeholders are in `.env.example`.

For APIM endpoints that need a custom route or header, reuse a working LangSmith evaluator configuration. A local Azure model working does not establish that the self-hosted evaluator workers can reach the same endpoint. Test one hosted quality evaluator before the group starts.

Module 4's online evaluator and Module 6 share `DEFAULT_JUDGE_MODEL`. Module 4's offline judges use the local model in `utils/models.py`; this notebook leaves that choice intact. The helper serializes secret **names**, never local key values. Do not print a copied provider configuration.

## Recovery checkpoints

Always start a fresh kernel with Section 1 so imports, connection settings, and project scope are initialized.

| Starting point | Selection | Next steps |
|---|---|---|
| Normal exercise | `activity_source = "live"` | Capture the inspection turn, then continue |
| Claude setup blocked | `activity_source = "replay"` | Section 1 uploads the recorded inspection; Section 4 uploads four more turns after evaluator registration |
| Join at dashboards | `activity_source = "prepared"` and the presenter's project name | Run Sections 1–2, then Section 5; adjust `since` to include the supplied traces |

Replay uses the [reviewed recording](fixtures/README.md): five genuine turns from this sample app, 78 runs, five Skill executions, and ten MCP executions. It preserves messages, ordering, durations, token counts, and measured costs. Personal metadata and local paths are removed. Historical feedback is omitted; the enabled judges produce new feedback. Costs describe the original activity, not the cost of running the upload script.

Replay assigns new run/thread IDs per target project and persists its attempt in ignored `.module06/replay/`. Keep that state when resuming after a kernel restart or interrupted upload. Completed stages are skipped. To run a separate rehearsal, use a new participant ID/project; don't delete state midway through an attempt.

The smoke turn is uploaded before evaluators, so it normally has no evaluation. Upload usage only after all three rules are enabled. Rules select newly received runs even though recorded timestamps are shifted into the recent past. Thread feedback still waits for real inactivity after ingestion. If usage was already uploaded with rules disabled, use a new project for a new rehearsal or arrange an explicit backfill with the presenter.

Prepared mode reads an existing project. It skips project creation, rule registration, thread-setting updates, dashboard writes, replay, and cleanup. The presenter supplies populated traces, feedback, and a dashboard; participants can still build notebook rankings and open the existing dashboard.

## Presenter preparation

1. Verify the target deployment and an ordinary **Editor** account. The BMS dry run used self-hosted **0.16.65**. Its source supports the selected query/rule contracts, but its feature flags, custom permissions, network access, and provider configuration must be tested on that instance. Don't use workspace admin as the default workaround. Creating/rotating workspace secrets is a facilitator operation requiring secret-management permission.
2. Check the notebook's API/UI URLs, participant project, local MCP, and smoke prompt. In 2.2, compare actual Skill/MCP execution rows with the containing root turns. These queries use tool type/name; output-content indexing is not a workshop prerequisite.
3. Verify the three hosted rules on incoming activity: root quality/completion and session outcome after inactivity. Open the semantic `?tab=evaluators` link. If an old UI doesn't honor it, click **Evaluators** from the project.
4. Keep a prepared project with a genuine recorded session, populated feedback, and a dashboard. Rehearse both recovery checkpoints from a fresh kernel. One recorded session has one thread; multiple turns do not imply multiple threads. Use a separate replay project to test isolation.
5. Save the legacy dashboard on self-hosted, then save again, including after a kernel restart. The SaaS v2 conversion endpoint is not assumed available on 0.16.65. Check stable dashboard/chart IDs, invocation totals, measured whole-trace costs, and numeric quality scores against the notebook. Each native series uses the same sampled trace/root IDs; rerun analysis and chart cells after new activity.
6. Verify CLI access. Remote MCP on self-hosted 0.16+ additionally needs hostname/signing configuration and reachability to `/api/mcp`; see the [setup guide](https://docs.langchain.com/langsmith/langsmith-remote-mcp#self-hosted-langsmith). LangSmith Chat is optional.
7. Have BMS validate its M365 connector on an approved demo mailbox. The notebook prompt only reads. Jira is an alternative for users with access; neither connector is required for the local exercise. Never capture real employee messages into the shared workshop fixture.
8. After final feedback lands, pause the workshop rules. Partial registration is recorded incrementally, so cleanup also works after a later registration failure. A fresh kernel must rerun registration to recover those IDs, or the presenter can pause the named rules in the UI.

## Final rehearsal

1. Pull the full repository on `avi/coding-agent-analysis`, restart the kernel, and rerun setup.
2. Inspect Skill/MCP executions and their parent turns. Run the short local Skill extraction example.
3. Register the three judges; run the fix/review and TASK-002 follow-up tasks. Confirm `output_quality`, `task_completion`, and `session_outcome` after processing and thread inactivity.
4. Check Skill/MCP counts, known costs and scored-turn coverage. Missing cost stays unknown; a recorded zero remains valid.
5. Save the three custom charts, inspect the time range, and save again to confirm reuse. A blank native cost chart is acceptable if notebook costs are available. Investigate remaining chart issues separately from the attendee flow.
6. Run the CLI cells, wait for final feedback, and pause the exact registered IDs. Inspect obsolete Skill rules separately in reused projects.
7. Export the completed rehearsal as HTML for review. Clear outputs and execution counts in the distributed notebook.

The attendee notebook displays instructional results and normal actionable errors. Diagnostic reports, pricing probes, chart-query previews and resource-ID dumps are outside its execution path. Three rules and all three charts are retained.

## Capacity for 40–60 attendees

Use a separate project per participant, even within one shared workspace. Confirm project/rule/chart permissions, trace-ingestion limits, evaluator-worker capacity, Azure/APIM requests-per-minute and tokens-per-minute limits, and any workspace spending limits with the deployment owner.

The recorded exercise contributes **78 runs and three rules per participant**: 3,120 runs/120 rules for 40 people, or 4,680 runs/180 rules for 60. Its four evaluated turns normally request eight run-level LLM judgments and one idle-thread judgment: roughly 360 or 540 LLM calls respectively, plus model-validation requests and any extra turns. Long conversations can raise token usage substantially. Replay ingestion is faster than live typing, so avoid asking the entire room to replay simultaneously.

Start with one Editor, then a small agreed cohort (for example five attendees). Stagger evaluator registration and activity; monitor queue age, 429s, provider quota, and feedback latency. If queues grow, stop adding turns, let the queue drain, and use the prepared-project checkpoint. Don't run an uncoordinated 40-person load test. A single SaaS rehearsal cannot establish BMS capacity.

The agenda totals 85 minutes including the break. To fit 80, shorten dashboards to 15 minutes and prepare the native charts ahead of time.

## Starter app

The notebook copies `sample_repo/` to a new temporary directory without resetting prior work. Keep the same Claude session for the follow-up tasks.

- **TASK-001:** four starter tests, two expected failures. Fix filtering without mutating the input.
- **TASK-002:** stable oldest-first ordering plus regression coverage. Passing the original tests doesn't establish success.
- **Presenter solution:** `solutions/tracker.py` satisfies both tasks and is kept outside participant copies.

The local MCP exposes fixed issue lookups over stdio. It has no arbitrary file, shell, or network tools.

## Verification

From the repository root:

```bash
uv run python -m unittest discover -s utils/coding_agent_workshop/tests -v
```

Tests cover configuration reuse, safe error diagnostics, Azure serialization, pagination, thread aliases, replay integrity/resumption/isolation, metric aggregation, scoped provisioning, the real stdio MCP, and the starter/reference solution. Unit-test mocks and fixtures do not establish live self-hosted compatibility.

The live path requires Claude activity between sections. Replay mode permits a notebook rehearsal without Claude, with a wait for indexing and hosted feedback. Prepared mode validates analysis against an existing project. Keep notebook outputs cleared before sharing.

### Final notebook release checklist

- [ ] Keep [Claude plugin evals](https://code.claude.com/docs/en/plugin-evals), importing results into LangSmith, and evaluating the evaluator in the follow-on lab under the recommended October 1 scope; add no new integration for tomorrow.
- [ ] Rehearse every cell on BMS and review its output. Automatic diagnostics and redundant resource tables have been removed locally; keep the remaining instructional results concise.
- [x] Remove automatic diagnostic reports, version banners, chart previews and duplicate resource tables from the attendee flow. Preserve real errors and missing-data coverage; facilitator diagnostics are manual.
- [x] Clear saved cell outputs and execution counts in the final notebook; clear again if the distributable copy is used for rehearsal.

## Troubleshooting

- **Wrong kernel:** select **Python (modular-workshop)** after registering it through `uv run python`; a system `python -m ipykernel` can register the wrong environment.
- **Self-hosted setup error:** set both API and UI URLs in root `.env`, then rerun setup. Hostnames aren't restricted to SaaS.
- **No Skill rows:** confirm the selected project/time window and inspect the trace for a tool span named `Skill`. Ask Claude to invoke the supplied skill by name, then refresh. Parent-turn rows and tool execution rows count different units. No hosted Skill feedback is needed.
- **One MCP row:** the first table counts matching turns. The second counts actual tool executions; the smoke task should show two local MCP tools in one turn.
- **One thread:** expected for one Claude session. Send another prompt in the same session for another turn, or start a new session for another thread. The helper supports `thread_id`, `session_id`, and `conversation_id` metadata.
- **No traces:** use the printed launch command, check `/plugin`, and confirm the thread isn't muted. The launcher sets `TRACE_TO_LANGSMITH=true`.
- **Saved tracing key conflict:** the launcher reports the settings path and variable name. Resolve the saved override so the root `.env` can supply the key. Restore temporary global configuration changes after testing.
- **Evaluator registration fails:** the helper reports the operation, HTTP status, safe category, and request ID when available. `401` means authentication; `403` requires checking workspace/operation permissions; `400/422` can indicate a missing hosted secret or invalid provider/model configuration; `404` can indicate an unsupported path; `429` means rate limiting. Share these diagnostics with the deployment owner, who can inspect server logs. Avoid sharing raw bodies or credentials.
- **Rule exists but feedback fails:** check the evaluator's execution error and provider connectivity from LangSmith workers. Local skill-name extraction does not validate Azure credentials or model settings.
- **Missing feedback:** allow indexing, model processing, and the configured thread-idle interval. Only `output_quality` is numeric; `task_completion` and `session_outcome` are text. `insufficient_evidence` is a valid result, not an execution error.
- **Missing custom charts:** open the printed dashboard link or select `Module 06 — <project name>`. Include the trace timestamps in the time range. Choose **Prebuilt → Tools** for the built-in tool charts.
- **Feedback exists but the quality chart is blank:** chart aggregates can lag the feedback table. Check the notebook's scored-turn counts, allow processing time, then refresh the dashboard. Don't rewrite or duplicate feedback to fill the chart.
- **Totals differ:** align the time window and sample. Root cost semantics differ between native and legacy query backends, so notebook turn costs use the explicit trace aggregate. Never sum an aggregate root with its children. Missing costs/scores remain missing. Rerun analysis and chart cells after additional activity.
- **Query exceeds its bound:** narrow `since` or intentionally raise the limit. The helpers raise instead of silently truncating totals.
