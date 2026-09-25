# Module 6 pre-work and presenter guide

Open [`06_coding_agent_analytics.ipynb`](../../modules/06_coding_agent_analytics.ipynb) for the participant walkthrough.

## Participant pre-work

1. Clone this repository and follow its normal Python/Jupyter setup. Module 6's sample app and local MCP use only the standard library; there are no additional packages to install.
2. Install and authenticate [Claude Code](https://code.claude.com/docs/en/setup). Confirm that a short prompt works before the workshop.
3. Install the official [LangSmith tracing plugin](https://docs.langchain.com/langsmith/trace-claude-code). Inside Claude Code, use the current documented commands:

   ```text
   /plugin marketplace add langchain-ai/langsmith-claude-code-plugins
   /plugin install langsmith-tracing@langsmith-claude-code-plugins
   /reload-plugins
   ```

   If the plugin is already installed under an older marketplace alias, check `/plugin` instead of installing a duplicate.

4. Reuse the root `.env` from the other modules: `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT`, and `WORKSPACE_ID`. A standard `LANGSMITH_WORKSPACE_ID`, if set, takes precedence over `WORKSPACE_ID`. For self-hosted UI links, also set `LANGSMITH_WEB_URL`. Never paste a key into a notebook cell.
5. Run the notebook's setup cells, then copy its launch command into a terminal. The launcher loads the same root `.env`, applies the notebook's selected endpoint/project/workspace, and starts Claude Code in the sample copy. Credentials stay in the process environment. If you use only shell-provided credentials, launch Jupyter and Claude Code from shells with that configuration.
   The notebook defaults `chart_format` to `"v2"` for the SaaS rehearsal; change it to `"legacy"` for the older self-hosted deployment. No extra environment variable is needed. You can also change `project_name` in that cell for an isolated practice project.
6. Install [LangSmith CLI](https://docs.langchain.com/langsmith/langsmith-cli) and [langsmith-skills](https://docs.langchain.com/langsmith/skills) for the closing exercise. Verify the CLI's endpoint/project before querying.

The notebook loads the supplied task plugin with `claude --plugin-dir <absolute-plugin-path>`. No marketplace publication is needed. Its two skills are `workshop:fix-bug` and `workshop:review-change`; its MCP tools are `mcp__plugin_workshop_issues__get_issue` and `mcp__plugin_workshop_issues__get_acceptance_criteria`.

Ask Claude to **invoke the named skill** in natural language. Direct slash commands can expand a skill before the model runs and do not necessarily produce a native LLM `Skill` call.

## Hosted judges

Module 6 and Module 4's online evaluator use the shared helper and model default in `utils/langsmith_rules.py`. For this SaaS rehearsal, cell `m06-27` selects the workspace's existing `OPENAI_API_KEY` secret through the helper's `api_key_env` argument:

- Direct OpenAI: a workspace secret named `OPENAI_API_KEY`.
- Repository Gateway setup: select `LANGSMITH_API_KEY_GATEWAY` in that cell when a workspace secret with that name exists. Omitting `api_key_env` retains the shared helper's automatic local-environment selection, including legacy `LC_GATEWAY_KEY` support.
- Other/self-hosted providers: replace the notebook's judge assignment with `rules.judge_model_config(client, template_rule_id="<working-rule-uuid>")`. This advanced option copies an existing working inline evaluator's serialized model and saved-configuration reference without printing them.

`DEFAULT_JUDGE_MODEL` is the shared model default for both modules. Hosted judges need their provider credential in LangSmith because they run there. Module 4's offline judges instead use the local model in `utils/models.py`. Local key values are never uploaded. Reuse a working workspace provider secret; selecting OpenAI for hosted judges leaves local Gateway configuration in place.

Earlier drafts introduced `CODING_AGENT_PROJECT`, `WORKSHOP_JUDGE_MODEL`, `WORKSHOP_JUDGE_TEMPLATE_RULE_ID`, and `WORKSHOP_CHART_FORMAT`. These are no longer read; any entries left in your `.env` can be removed. Claude Code queries and evaluator rules are scoped to `ls_integration=claude-code` within the shared project. An existing project thread-inactivity setting is preserved.

## Presenter preparation

1. Verify the target deployment's rule, thread-evaluation, metadata-grouped legacy chart, and preview APIs. Version is unknown for the planned self-hosted delivery, so do not rely on newer dashboards or categorical-feedback chart grouping.
2. Run the notebook's local checks and smoke prompt. Inspect the actual LLM output and Skill/MCP tool names before registering filters or evaluators.
3. Register the five rules, then work through the prompt cards. Confirm categorical `skill_name`, root quality/completion, LLM selection feedback, and session outcome after inactivity. Root/thread completion judgments deliberately permit insufficient evidence.
4. Prepare two or three **real captured sessions**: a fix/review, an incomplete result, and a later correction. Keep their IDs/project links privately with your presenter notes. Do not substitute synthetic test fixtures for captured activity. Use the same project and recent time window, or edit the notebook's `since` value to include them.
5. Build the sampled root-ID groups and preview/provision the native dashboard. Verify invocations against tool spans and root cost/quality against a small sample. Native legacy bars are time-bucket charts; horizontal notebook rankings are whole-window summaries. All native charts use the sampled completed turns: trace IDs for invocations and root IDs for cost/quality. Rerun analysis and chart cells after new activity. Larger comparisons split into charts with up to three series. The notebook selects this dashboard as the project default if none is selected; use **Prebuilt** in the dashboard selector for the Tools section.
6. Confirm CLI trace/thread queries work. Remote MCP is optional: self-hosted 0.16+ additionally needs hostname/signing configuration and network access to its own `/api/mcp` endpoint. The [local LangSmith MCP server](https://docs.langchain.com/langsmith/langsmith-mcp-server) is an optional alternative for older deployments.
7. Have BMS validate its connector separately before offering the optional extension. The required exercise uses the local fixture MCP.

The agenda totals 85 minutes with the break. To fit 80 minutes, shorten dashboards to 15 minutes and have the native charts prepared.

## Starter app and expected results

The notebook copies `sample_repo/` to a new temporary working directory. It never resets an existing attempt. Keep the Claude session in that directory so all turns belong to the same exercise.

- **TASK-001:** the starter's four tests have two failures. The fix excludes completed tasks and tasks due today, and preserves the input.
- **TASK-002:** adds stable oldest-first ordering and an ordering regression test. The initial tests do not cover it; passing them does not establish TASK-002 success.
- **Presenter solution:** `solutions/tracker.py` satisfies both issues. It lives outside participant copies.

The MCP is deliberately small: a local stdio process serves fixed issue IDs. It has no arbitrary file, shell, or network tools. Protocol output is newline-delimited JSON on stdout. Implementation notes and tests live beside the sample rather than in the teaching cells.

## Verification

Run the offline checks from the repository root:

```bash
uv run python -m unittest discover -s utils/coding_agent_workshop/tests -v
```

They check shared setup and judge defaults, launcher/CLI configuration, the known failing starter against the solution, MCP messages over actual stdio, extraction edge cases, metric aggregation, disjoint cohort coverage, and rerunnable API requests using an in-memory transport. These test fixtures are explicitly synthetic. Live SaaS verification and the later self-hosted rehearsal are separate checks.

The notebook intentionally requires human Claude Code activity between sections. Do not expect an unattended Run All on an empty project to create that activity. Complete the smoke task before Part 2 and the prompt cards before Part 5. The final cell pauses only this notebook's recorded evaluator IDs.

### Completed development checks

- **Local:** 32 tests pass, including shared configuration, explicit hosted-provider selection, provider secret references, launcher/CLI workspace propagation, conflicting saved Claude credentials, preserved thread settings, the real stdio MCP lifecycle, intentionally failing starter, reference solution, extraction, aggregation, cohort coverage, chart population, and provisioning behavior.
- **Notebook:** all 43 code cells compile and begin with a purpose comment. The longest code cell is 23 lines. Notebook format validation and HTML conversion pass; saved outputs and execution counts are empty.
- **Live SaaS (2026-09-25):** all 43 code cells executed successfully in a real Jupyter kernel, with actual Claude Code prompts between sections. Five exercise turns contain five Skill spans and ten local MCP calls. All five evaluator types produced feedback. Hosted judges used the existing OpenAI workspace secret and the shared `gpt-5.6-luna` default. The edited sample passes seven tests.
- **Charts and CLI:** legacy previews and saved v2 definitions return matching counts, measured costs, and quality scores. Registration reruns retain all five rule IDs, three chart IDs, and five series IDs. CLI trace/thread queries and the Claude LangSmith-skill exercise pass. The final cell disabled the five workshop rules.

### Remaining deployment checks

- Test the older self-hosted deployment with `chart_format = "legacy"` in the setup cell, including saved dashboards, code execution, thread evaluation, and its provider configuration. Validate the optional BMS connector separately.
- Optional LangSmith Chat and Remote MCP were not exercised in this SaaS rehearsal.
- Prepare additional real sessions with varied output quality before teaching a leaderboard comparison. The four scored exercise turns all received quality 1.0; this validates the pipeline, not judge calibration or a difference between skills.

## Troubleshooting

- **No Skill run:** request the skill by name in a normal prompt, check `/plugin`, and inspect the raw LLM output. Tool-call output paths depend on plugin version.
- **No MCP tools:** check `/mcp`, the absolute `--plugin-dir` path, and whether `python3` is on the terminal's PATH. The notebook checks the stdio server independently.
- **No traces:** rerun the notebook's launch command so Claude Code gets the shared `.env` and current notebook selections. Check `/plugin` and that the thread is unmuted. The launcher sets `TRACE_TO_LANGSMITH=true`.
- **Saved Claude tracing settings:** the launcher sets the selected project/endpoint/workspace for this invocation. If a saved Claude settings file supplies a different tracing key, the launcher reports its path and variable name before starting. Remove that override to use the root `.env`; if removal is temporary, restore it after the rehearsal.
- **Hosted judge errors:** inspect the evaluator's error in LangSmith; confirm the same workspace provider secret used for Module 4, or copy a working model configuration as described above.
- **Blank feedback averages:** only `output_quality` and `skill_selection` are numeric. Inspect the text values and comments for `skill_name`, `task_completion`, and `session_outcome`. `insufficient_evidence` is a judgment, not an execution error; root/thread judges cannot inspect child test results.
- **Missing final feedback:** wait for quality, completion, and the idle-thread outcome before running cleanup. Pausing the rules too soon can leave the last turn unscored.
- **SaaS rejects legacy chart series:** set `chart_format = "v2"` in setup and rerun chart cells. Use `"legacy"` for the older self-hosted rehearsal.
- **Custom charts not visible:** open the dashboard link printed by the notebook, or select `Module 06 — <project name>` from the dashboard selector. Include the exercise timestamps in the dashboard's time range.
- **No thread feedback:** leave the session idle for at least the configured interval, then allow evaluator processing time. Feedback is not attached to every child run.
- **Chart counts differ:** align time windows, check the notebook's completed-turn filter, allow indexing time, and rerun analysis/chart cells for new turns. Missing scores/costs remain missing.
- **Analysis window exceeds the limit:** narrow `since` or explicitly increase `max_turns`; the utility does not silently truncate totals.
