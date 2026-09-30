# Module 6 pre-work and presenter guide

Open [`06_coding_agent_analytics.ipynb`](../../modules/06_coding_agent_analytics.ipynb). It stands alone; Module 4 is an optional reference.

## Participant pre-work

1. Clone this repository. From its root, run:

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

The smoke turn is uploaded before evaluators, so it normally has no evaluation. Upload usage only after all five rules are enabled. Rules select newly received runs even though recorded timestamps are shifted into the recent past. Thread feedback still waits for real inactivity after ingestion. If usage was already uploaded with rules disabled, use a new project for a new rehearsal or arrange an explicit backfill with the presenter.

Prepared mode reads an existing project. It skips project creation, rule registration, thread-setting updates, dashboard writes, replay, and cleanup. The presenter supplies populated traces, feedback, and a dashboard; participants can still build notebook rankings and preview the chart queries.

## Presenter preparation

1. Verify the target deployment and an ordinary **Editor** account. The BMS dry run used self-hosted **0.16.65**. Its source supports the selected query/rule contracts, but its feature flags, custom permissions, network access, and provider configuration must be tested on that instance. Don't use workspace admin as the default workaround. Creating/rotating workspace secrets is a facilitator operation requiring secret-management permission.
2. Check the notebook's API/UI URLs, participant project, local MCP, and smoke prompt. In 2.2, confirm the observed LLM output path matches the server's indexed filter. A visible raw payload doesn't prove it was indexed. Children need not carry the root's integration metadata.
3. Verify all five rules on incoming turns: categorical `skill_name`, root quality/completion, numeric LLM selection, and session outcome after inactivity. Open the semantic `?tab=evaluators` link. If an old UI doesn't honor it, click **Evaluators** from the project.
4. Keep a prepared project with a genuine recorded session, populated feedback, and a dashboard. Rehearse both recovery checkpoints from a fresh kernel. One recorded session has one thread; multiple turns do not imply multiple threads. Use a separate replay project to test isolation.
5. Preview and save the legacy dashboard on self-hosted, then save again, including after a kernel restart. The SaaS v2 conversion endpoint is not assumed available on 0.16.65. Check stable dashboard/chart IDs, invocation totals, measured whole-trace costs, and numeric quality scores against the notebook. Each native series uses the same sampled trace/root IDs; rerun analysis and chart cells after new activity.
6. Verify CLI access. Remote MCP on self-hosted 0.16+ additionally needs hostname/signing configuration and reachability to `/api/mcp`; see the [setup guide](https://docs.langchain.com/langsmith/langsmith-remote-mcp#self-hosted-langsmith). LangSmith Chat is optional.
7. Have BMS validate its M365 connector on an approved demo mailbox. The notebook prompt only reads. Jira is an alternative for users with access; neither connector is required for the local exercise. Never capture real employee messages into the shared workshop fixture.
8. After final feedback lands, pause the workshop rules. Partial registration is recorded incrementally, so cleanup also works after a later registration failure. A fresh kernel must rerun registration to recover those IDs, or the presenter can pause the named rules in the UI.

## Read-only diagnostics

### Retest and export

1. Pull the complete updated repository, including `utils/`, and restart the notebook kernel.
2. Rerun setup and confirm it prints **`Failure diagnostics: automatic (2026-09-30.1)`**. A stale helper version stops setup with a restart instruction.
3. Run Section 2.2 normally. A failed query or missing Skill match automatically prints **`MODULE 06 DIAGNOSTICS BEGIN`**, then the exact scope, original error (if any), per-predicate legacy/V2 results, costs, model details, Skill rule state, and pricing candidates. Wait for **`MODULE 06 DIAGNOSTICS END`** before exporting. Diagnostic work is bounded to two minutes; each completed probe is printed immediately, and a timeout preserves the partial report.
4. Continue the independent sections after any error. Both Skill registrations remain blocked until validation passes. Section 5.2 also prints a diagnostic report automatically if every sampled turn lacks cost, even if Skill validation succeeded. A real zero cost does not trigger it.
5. Export the notebook **as HTML with all outputs**, including the setup version, diagnostic reports, and errors. No extra cells or terminal commands are required to capture these reports. Do not clear this retest export's outputs.

Reports omit trace content, tool arguments, credentials, provider configurations, and raw error bodies. They record safe HTTP status, category, request ID, and error location when available. An individual failed probe remains visible while other probes continue. `finished` means collection finished; inspect individual probe errors too. `incomplete` means the time limit or an unexpected diagnostic failure stopped collection; share the partial report.

Evaluator and dashboard API failures already print their method/path, HTTP status, safe category, and request ID when supplied by the server. Include those cell errors in the same export. Successful registration is separate from successful scoring; check feedback and evaluator execution logs before treating a rule as validated. The final pause cell must be run after final feedback arrives to verify cleanup.

### Optional manual follow-up

The automatic reports are sufficient for the initial retest. For a targeted follow-up, this temporary cell can also inspect an existing dashboard. Keep `since` fixed so it includes the selected run:

```python
from utils.coding_agent_diagnostics import collect_diagnostics

diagnostic_report = await collect_diagnostics(
    client, project, llm_run_id=analytics.field(llm_run, "id"), since=since,
    dashboard_id=dashboard["id"] if globals().get("dashboard") else None,
    include_pricing=True,
)
print(json.dumps(diagnostic_report, indent=2))
```

The report compares the exact run through legacy and V2 queries, decomposes the Skill predicate, and compares cost fields before and after SDK/helper normalization. It includes model/provider/plugin versions, the two Skill rules' enabled/filter state, and recent execution-outcome counts. It excludes prompts, responses, tool arguments, provider configurations, and credentials. Pricing results are **candidates from substring search**, not proof that a price matches; the facilitator checks the actual model/provider/date and rates in the UI.

For a fresh terminal, run from the repository root with the actual IDs and a timestamp containing the original run:

```bash
.venv/bin/python -m utils.coding_agent_diagnostics \
  --project '<exact participant project name>' \
  --llm-run-id '<Skill-calling LLM UUID>' \
  --since '<ISO timestamp with timezone>' \
  --dashboard-id '<existing dashboard UUID>' \
  --include-pricing
```

The CLI loads the root `.env` and reads an existing project. Omit `--dashboard-id` if no dashboard has been created. Neither invocation changes rules, traces, prices, or dashboards. The optional dashboard check compares the old read request with a bounded one-minute read; it may deliberately record the old HTTP 404. Share the report with the presenter and deployment owner.

Interpret the report in order:

1. **ID-only lookup fails:** check project, ID, connection, and time bounds first.
2. **ID resolves but output probes fail on both APIs:** inspect payload indexing on the deployment. On the 0.16.65 ClickHouse path, check `FF_CH_SEARCH_ENABLED` and the indexed pairs on ingest workers. Raw outputs can exist without searchable pairs. Validate a configuration correction with new activity.
3. **Legacy matches but V2 fails:** investigate query routing/compatibility before changing the expression.
4. **Filter matches but feedback is missing:** inspect the two Skill rules and their execution logs, then generate a fresh completed Skill turn after both rules register. Section 5.1 checks both `skill_name` and `skill_selection`; the pre-registration smoke turn normally has neither. Do not bypass the registration gate.
5. **Raw LLM costs are absent:** check the actual Claude model/provider, usage metadata and price mapping. Azure judge pricing is a separate concern. If raw costs exist but normalized values disappear, compare root IDs and response fields. Pricing edits do not recalculate old traces; test new activity. Unknown cost remains unknown.
6. **Dashboard without dates fails but bounded read succeeds:** this matches the 0.16.65 populated-section time-window behavior. The updated save helper supplies dates. A genuine missing dashboard remains an error; recreating it can introduce duplicates.

After correction, exercise both workshop skills and verify all five feedback types. Save the dashboard twice and reconnect in a fresh kernel to verify the same IDs are reused. Wait for final feedback, then run the exact-ID pause cell.

### Capacity for 40–60 attendees

Use a separate project per participant, even within one shared workspace. Confirm project/rule/chart permissions, trace-ingestion limits, evaluator-worker capacity, Azure/APIM requests-per-minute and tokens-per-minute limits, and any workspace spending limits with the deployment owner.

The recorded exercise contributes **78 runs and five rules per participant**: 3,120 runs/200 rules for 40 people, or 4,680 runs/300 rules for 60. Its four evaluated turns normally request 12 run-level LLM judgments and one idle-thread judgment: roughly 520 or 780 LLM calls respectively, plus model-validation requests and any extra turns. Long conversations can raise token usage substantially. Replay ingestion is faster than live typing, so avoid asking the entire room to replay simultaneously.

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

- [ ] Before the final push, revisit [Claude plugin evals](https://code.claude.com/docs/en/plugin-evals): an optional capstone, importing results into LangSmith, and evaluating the evaluator. Decide whether to include this in the workshop or a follow-on lab.
- [ ] Run every cell and audit its output. Remove diagnostic/debug output and redundant status messages or detail dumps from the normal notebook flow; keep each cell's essential instructional results clean and minimal.
- [ ] Keep successful cell outputs minimal. Failures and wholly missing costs must automatically print diagnostic evidence in their cells; extra manual diagnostics are optional.
- [ ] Clear saved cell outputs and execution counts before distributing the final notebook.

## Troubleshooting

- **Wrong kernel:** select **Python (modular-workshop)** after registering it through `uv run python`; a system `python -m ipykernel` can register the wrong environment.
- **Self-hosted setup error:** set both API and UI URLs in root `.env`, then rerun setup. Hostnames aren't restricted to SaaS.
- **No Skill rows:** inspect the automatic Section 2.2 report. Compare ID-only, output-key, output-value, and full-filter probes across both APIs; distinguish indexing, routing, response shape, and SDK parsing before retrying. Don't silently broaden the selection judge to every LLM run.
- **One MCP row:** the first table counts matching turns. The second counts actual tool executions; the smoke task should show two local MCP tools in one turn.
- **One thread:** expected for one Claude session. Send another prompt in the same session for another turn, or start a new session for another thread. The helper supports `thread_id`, `session_id`, and `conversation_id` metadata.
- **No traces:** use the printed launch command, check `/plugin`, and confirm the thread isn't muted. The launcher sets `TRACE_TO_LANGSMITH=true`.
- **Saved tracing key conflict:** the launcher reports the settings path and variable name. Resolve the saved override so the root `.env` can supply the key. Restore temporary global configuration changes after testing.
- **Evaluator registration fails:** the helper reports the operation, HTTP status, safe category, and request ID when available. `401` means authentication; `403` requires checking workspace/operation permissions; `400/422` can indicate a missing hosted secret or invalid provider/model configuration; `404` can indicate an unsupported path; `429` means rate limiting. Share these diagnostics with the deployment owner, who can inspect server logs. Avoid sharing raw bodies or credentials.
- **Rule exists but feedback fails:** check the evaluator's execution error and provider connectivity from LangSmith workers. Successful code evaluation doesn't validate Azure credentials or model settings.
- **Missing feedback:** allow indexing, model processing, and the configured thread-idle interval. Only `output_quality` and `skill_selection` are numeric; the other feedback keys are text. `insufficient_evidence` is a valid result, not an execution error.
- **Missing custom charts:** open the printed dashboard link or select `Module 06 — <project name>`. Include the trace timestamps in the time range. Choose **Prebuilt → Tools** for the built-in tool charts.
- **Feedback exists but the quality chart is blank:** chart aggregates can lag the feedback table. The preview reports numeric feedback sample counts; rerun it after processing catches up. Don't rewrite or duplicate feedback to fill the chart.
- **Totals differ:** align the time window and sample. Root cost semantics differ between native and legacy query backends, so notebook turn costs use the explicit trace aggregate. Never sum an aggregate root with its children. Missing costs/scores remain missing. Rerun analysis and chart cells after additional activity.
- **Query exceeds its bound:** narrow `since` or intentionally raise the limit. The helpers raise instead of silently truncating totals.
