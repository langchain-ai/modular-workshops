"""Plumbing for Module 6; the notebook keeps filters, rubrics, and metrics visible."""

from __future__ import annotations

import asyncio
import html
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from langsmith import Client
from langsmith.utils import LangSmithNotFoundError

from utils.langsmith_rules import api_request


FAILURE_DIAGNOSTICS_VERSION = "2026-09-30.2"


def field(obj, name, default=None):
    """Read SDK objects and JSON fixtures through the same small interface."""
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def metadata(run):
    return {**((field(run, "extra") or {}).get("metadata") or {}), **(field(run, "metadata") or {})}


def check_settings(api_url: str, web_url: str):
    """Validate origins and credential presence without printing credentials."""
    for label, url in (("API", api_url), ("UI", web_url)):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"Set a valid {label} URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(f"The {label} URL must not contain credentials, a query, or a fragment.")
    if not os.environ.get("LANGSMITH_API_KEY"):
        raise ValueError("Set LANGSMITH_API_KEY in your environment before connecting.")
    if not is_cloud_url(api_url) and is_cloud_url(web_url):
        raise ValueError("LANGSMITH_ENDPOINT selects self-hosted but LANGSMITH_WEB_URL selects SaaS. "
                         "Set both URLs in the root .env and rerun setup.")
    print("LangSmith credential: set")
    print("API:", api_url)
    print("UI: ", web_url)


def is_cloud_url(url):
    host = urlsplit(url).hostname or ""
    return host == "smith.langchain.com" or host.endswith(".smith.langchain.com")


def participant_project(base, participant):
    """Use one stable participant suffix for SDK, Claude, CLI, and dashboards."""
    suffix = re.sub(r"[^a-z0-9-]+", "-", participant.lower()).strip("-")
    if not suffix or len(suffix) > 48:
        raise ValueError("Use a short participant ID containing letters or numbers.")
    if not base or len(base) > 150:
        raise ValueError("Set a short LANGSMITH_PROJECT base name.")
    return base if base.endswith("-" + suffix) else f"{base}-{suffix}"


def ensure_project(client: Client, project_name: str):
    """Create only the explicitly selected project when it does not yet exist."""
    try:
        return client.read_project(project_name=project_name)
    except LangSmithNotFoundError:
        return client.create_project(project_name, description="Module 6: Claude Code skills and MCP workshop.")


def project_url(project, web_url: str) -> str:
    return f"{web_url.rstrip('/')}/o/{project.tenant_id}/projects/p/{project.id}"


def run_url(run, project, web_url: str) -> str:
    return f"{project_url(project, web_url)}/r/{field(run, 'id')}"


def thread_id(run):
    info = metadata(run)
    return field(run, "thread_id") or info.get("thread_id") or info.get("session_id") or info.get("conversation_id")


def thread_filter(run):
    """Match the metadata key actually used by the captured session."""
    info = metadata(run)
    for key in ("thread_id", "session_id", "conversation_id"):
        if info.get(key):
            return f'and(eq(metadata_key, {json.dumps(key)}), eq(metadata_value, {json.dumps(info[key])}))'
    if field(run, "thread_id"):
        return f'eq(thread_id, {json.dumps(str(field(run, "thread_id")))})'
    raise ValueError("Selected turn has no thread ID. Inspect its metadata before querying a session.")


def prepare_workspace(project_root: Path) -> Path:
    """Copy the starter app into a new directory, keeping prior attempts intact."""
    parent = Path(tempfile.mkdtemp(prefix="module06-"))
    workspace = parent / "task-tracker"
    shutil.copytree(project_root / "utils/coding_agent_workshop/sample_repo", workspace,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return workspace


def check_local_setup(project_root: Path):
    """Exercise the local MCP lifecycle before launching a coding agent."""
    server = project_root / "utils/coding_agent_workshop/plugin/server.py"
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "workshop-check", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "get_issue", "arguments": {"issue_id": "TASK-001"}}},
    ]
    result = subprocess.run([sys.executable, str(server)], text=True, capture_output=True,
                            input="".join(json.dumps(item) + "\n" for item in messages), timeout=10)
    if result.returncode:
        raise RuntimeError("The local MCP server could not start; check Python and the plugin path.")
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    if len(replies) != 3 or any("error" in reply for reply in replies):
        raise RuntimeError("Unexpected MCP lifecycle response.")
    print("MCP tools:", ", ".join(tool["name"] for tool in replies[1]["result"]["tools"]))
    print("Claude Code:", "available" if shutil.which("claude") else "install before the smoke task")


def launch_instructions(project_root: Path, workspace: Path, plugin_root: Path,
                        project_name: str, api_url: str, workspace_id=None):
    """Print one command that reuses the root .env and notebook selections."""
    command = [sys.executable, str(project_root / "utils/launch_claude.py"),
               "--env-file", str(project_root / ".env"), "--workspace", str(workspace),
               "--plugin-root", str(plugin_root), "--api-url", api_url,
               "--project-name", project_name, "--workspace-id", workspace_id or ""]
    print("# Run in a terminal; this loads the same root .env as the notebook:")
    print(shlex.join(command))


def display_table(rows: list[dict]):
    """Render small tables without adding a dataframe dependency."""
    from IPython.display import HTML, display

    if not rows:
        print("No rows yet. Finish a task, then rerun this cell.")
        return
    columns = list(rows[0])
    header = "".join(f"<th style='text-align:left;padding:6px'>{html.escape(str(key))}</th>" for key in columns)
    body = []
    for row in rows:
        cells = []
        for key in columns:
            value = row.get(key)
            text = "—" if value is None else str(value)
            if key == "link" and text.startswith(("https://", "http://")):
                text = f'<a href="{html.escape(text, quote=True)}" target="_blank" rel="noopener">Open</a>'
            else:
                text = html.escape(text)
            cells.append(f"<td style='padding:6px;vertical-align:top'>{text}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    display(HTML("<table><thead><tr>" + header + "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"))


def show_runs(runs, project, web_url):
    display_table([{"run": str(field(run, "id"))[:8], "name": field(run, "name"),
                    "type": field(run, "run_type"), "cost ($)": turn_cost(run),
                    "thread": thread_id(run), "link": run_url(run, project, web_url)} for run in runs])


def require_first(items, message="No traces yet. Complete the smoke task and rerun the query."):
    if not items:
        raise ValueError(message)
    return items[0]


RUN_FIELDS = ["ID", "NAME", "RUN_TYPE", "START_TIME", "END_TIME", "ERROR", "INPUTS", "OUTPUTS",
              "EXTRA", "METADATA", "TRACE_ID", "THREAD_ID", "DOTTED_ORDER", "PARENT_RUN_IDS",
              "IS_ROOT", "TOTAL_COST", "PROMPT_COST", "COMPLETION_COST", "TOTAL_TOKENS",
              "PROMPT_TOKENS", "COMPLETION_TOKENS"]


async def query_runs(client, project, *, since, max_runs=500, limit=None, **filters):
    """Read explicit fields across pages; normalize the v2 SDK at one boundary."""
    result = []
    query = client.runs.query(project_ids=[str(project.id)], min_start_time=since,
                              selects=RUN_FIELDS, page_size=100, **filters)
    async with asyncio.timeout(60):
        async for run in query:
            row = dict(run) if isinstance(run, dict) else run.to_dict(mode="python", use_api_names=False)
            row["run_type"] = (row.get("run_type") or "").lower()
            result.append(row)
            if len(result) > max_runs:
                raise ValueError(f"More than {max_runs} runs matched. Narrow the window or increase max_runs.")
            if limit and len(result) >= limit:
                break
    return result


async def query_turns(client, project, *, since, **filters):
    """Use explicit trace aggregates; root cost semantics vary by query backend."""
    roots = await query_runs(client, project, since=since, is_root=True, **filters)
    by_id = {str(field(root, "id")): root for root in roots}
    for root in roots:
        root["trace_total_cost"] = None
    ids = list(by_id)
    for start in range(0, len(ids), 100):
        query = client.traces.query(project_id=str(project.id), trace_ids=ids[start:start + 100],
                                     min_start_time=since, selects=["ID", "TRACE_ID", "TOTAL_COST"], page_size=100)
        count = 0
        async with asyncio.timeout(60):
            async for trace in query:
                count += 1
                if count > 100:
                    raise ValueError("Trace cost query returned more rows than requested.")
                root_id = str(field(field(trace, "root_run"), "id"))
                if root_id in by_id:
                    by_id[root_id]["trace_total_cost"] = field(field(trace, "trace_aggregates"), "total_cost")
    return roots


def turn_cost(run):
    return field(run, "trace_total_cost", field(run, "total_cost"))


async def read_trace(client, project, root, max_runs=500):
    """Fetch a complete trace or fail rather than silently omit tool runs."""
    start = field(root, "start_time")
    if isinstance(start, str):
        start = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if start is None:
        raise ValueError("Select a root with start_time before loading its trace.")
    runs = await query_runs(client, project, trace_id=str(field(root, "trace_id") or field(root, "id")),
                            since=start - timedelta(seconds=1), max_runs=max_runs)
    if str(field(root, "id")) not in {str(field(run, "id")) for run in runs}:
        raise ValueError("Trace is still arriving; rerun this cell when its root is available.")
    if isinstance(root, dict) and "trace_total_cost" in root:
        next(run for run in runs if str(run["id"]) == str(root["id"]))["trace_total_cost"] = root["trace_total_cost"]
    return sorted(runs, key=lambda run: field(run, "dotted_order") or str(field(run, "start_time")))


def show_trace(runs, project, web_url):
    display_table([{"run": "  " * (field(run, "dotted_order") or "").count(".") + field(run, "name", ""),
                    "type": field(run, "run_type"), "cost ($)": field(run, "total_cost"),
                    "error": bool(field(run, "error")), "link": run_url(run, project, web_url)} for run in runs])


def tool_calls(run):
    """Read native plugin content blocks, or normalized message.tool_calls."""
    calls = []
    for message in (field(run, "outputs") or {}).get("messages", []):
        content = message.get("content", [])
        blocks = content if isinstance(content, list) else []
        candidates = message.get("tool_calls") or [
            block for block in blocks if isinstance(block, dict) and block.get("type") in {"tool_call", "tool_use"}
        ]
        for call in candidates:
            args = call.get("args", call.get("input", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            calls.append({"name": call.get("name"), "args": args if isinstance(args, dict) else {},
                          "id": call.get("id")})
    return calls


def find_llm(runs, tool_name="Skill"):
    return require_first([run for run in runs if field(run, "run_type") == "llm"
                          and any(call["name"] == tool_name for call in tool_calls(run))],
                         f"No LLM {tool_name} call found. Ask Claude to invoke the skill by name, then refresh.")


def observed_call_path(run):
    messages = (field(run, "outputs") or {}).get("messages", [])
    if any(message.get("tool_calls") for message in messages):
        return "messages.tool_calls.name"
    if tool_calls(run):
        return "messages.content.name"
    raise ValueError("Inspect an LLM run with a tool call before choosing its filter path.")


class SkillFilterUnavailable(ValueError):
    """A known Skill call was retrieved but did not match its content filter."""


async def verify_skill_filter(client, project, llm_run, filter, *, since):
    """A visible payload is not proof that the server indexed its tool calls."""
    from utils.coding_agent_diagnostics import print_diagnostics

    if field(llm_run, "run_type", "").lower() != "llm" or not any(
            call["name"] == "Skill" for call in tool_calls(llm_run)):
        raise ValueError("Select an LLM run whose output contains a Skill call before verifying its filter.")
    run_id = str(field(llm_run, "id"))
    try:
        matches = await query_runs(client, project, since=since, ids=[run_id], filter=filter)
    except Exception as exc:
        await print_diagnostics(client, project, llm_run=llm_run, since=since,
                                trigger="skill-filter-query-error", requested_filter=filter, original_error=exc)
        raise ValueError("Skill filter query failed. Automatic diagnostics are printed above. "
                         "Export this cell's output as HTML. Skill evaluator registration remains blocked.") from None
    if not any(str(field(run, "id")) == run_id for run in matches):
        await print_diagnostics(client, project, llm_run=llm_run, since=since,
                                trigger="skill-filter-no-match", requested_filter=filter)
        raise SkillFilterUnavailable(
            "The observed Skill call did not match the server filter. Automatic diagnostics are printed above. "
            "Export this cell's output as HTML. Skill evaluator registration remains blocked. "
            "The raw trace contains the call; its indexing/query cause is not yet established."
        )
    print("Skill filter matched the inspected LLM run.")
    return _skill_filter_scope(client, project, llm_run, filter, since)


async def resolve_skill_filters(client, project, llm_run, indexed_filter, *, since, agent_filter):
    """Use verified output filtering, or chain deterministic labels into the judge."""
    try:
        validation = await verify_skill_filter(client, project, llm_run, indexed_filter, since=since)
    except SkillFilterUnavailable:
        label_filter = f'and(eq(run_type, "llm"), {agent_filter})'
        label_validation = await verify_skill_filter(client, project, llm_run, label_filter, since=since)
        selection_filter = (f'and({label_filter}, '
                            'and(eq(feedback_key, "skill_name"), like(feedback_value, "%")))')
        print("Output-content filtering is unavailable for this run. Using feedback-gated Skill evaluation.\n"
              "The code labeler checks Claude Code LLM outputs and emits nothing for non-Skill calls.\n"
              "The hosted judge will select successful skill_name labels; Section 3.5 must verify a fresh label.")
        return {"mode": "feedback", "label_filter": label_filter, "selection_filter": selection_filter,
                "label_validation": label_validation, "selection_validation": None,
                "turn_filter": 'and(eq(run_type, "tool"), eq(name, "Skill"))'}
    return {"mode": "outputs", "label_filter": indexed_filter, "selection_filter": indexed_filter,
            "label_validation": validation, "selection_validation": validation, "turn_filter": indexed_filter}


async def wait_for_skill_label(client, project, filter, *, since, timeout=90, poll_interval=5):
    """Find a fresh, truly labeled Skill decision before enabling its hosted judge."""
    from utils.coding_agent_diagnostics import _capture, _error, _rule_summary

    print("Waiting for a fresh Skill decision with skill_name feedback. "
          "Run the inspection prompt printed after Section 3.1.", flush=True)
    try:
        async with asyncio.timeout(timeout):
            while True:
                async with asyncio.timeout(15):
                    matches = await query_runs(client, project, since=since, filter=filter, limit=10)
                for run in matches:
                    names = {call["args"].get("skill") for call in tool_calls(run)
                             if call["name"] == "Skill" and isinstance(call["args"].get("skill"), str)
                             and call["args"]["skill"]}
                    if field(run, "run_type") != "llm" or not names:
                        raise ValueError("Feedback filter returned a run without an actual named Skill call.")
                    async with asyncio.timeout(15):
                        feedback = await asyncio.to_thread(read_feedback, client, [run], ["skill_name"])
                    labels = set()
                    for item in feedback:
                        if (str(field(item, "run_id")) != str(field(run, "id"))
                                or field(item, "key") != "skill_name"
                                or (field(item, "extra") or {}).get("error")):
                            continue
                        value = field(item, "value")
                        labels.update([value] if isinstance(value, str) else
                                      [name for name in value if isinstance(name, str)] if isinstance(value, list) else [])
                    if names <= labels:
                        print("Verified fresh Skill labels on LLM:", field(run, "id"), flush=True)
                        return run
                await asyncio.sleep(poll_interval)
    except TimeoutError:
        print("Skill label verification timed out; collecting recent rule outcomes.", flush=True)
        summary = await _capture(lambda: _rule_summary(client, str(project.id), filter), "/runs/rules:label-wait")
        print(json.dumps({"skill_label_wait": {"since": str(since), "filter": filter, "rules": summary}},
                         ensure_ascii=True), flush=True)
        raise ValueError("No verified fresh Skill labels before timeout. Complete a fresh Skill inspection after Section 3.1, "
                         "then rerun Section 3.5. Check the code evaluator logs if labels remain absent. "
                         "The hosted Skill judge was not registered by this cell.") from None
    except Exception as exc:
        print(json.dumps({"skill_label_check": _error(exc, "/skill-label-verification")}), flush=True)
        raise ValueError("Skill label verification failed; inspect the safe diagnostic above. "
                         "The hosted Skill judge was not registered by this cell.") from None


def _skill_filter_scope(client, project, llm_run, filter, since):
    return (id(client), str(project.id), str(field(llm_run, "id")), filter, str(since))


def require_skill_filter_validation(validation, client, project, llm_run, filter, *, since):
    """Reject missing or stale notebook validation before either Skill rule write."""
    if validation != _skill_filter_scope(client, project, llm_run, filter, since):
        raise ValueError("Rerun Section 2.2 successfully with the current connection, project, "
                         "LLM run, filter, and time window before registering Skill evaluators.")


def tool_name(run):
    return metadata(run).get("ls_tool_name") or field(run, "name", "")


def skill_name(run):
    """Count execution spans, not the LLM messages that requested execution."""
    if field(run, "run_type") != "tool":
        return None
    known = metadata(run).get("ls_skill_name")
    if isinstance(known, str) and known:
        return known
    if tool_name(run) == "Skill":
        inputs = field(run, "inputs") or {}
        name = inputs.get("input", inputs).get("skill")
        return name if isinstance(name, str) and name else None
    return None


def flatten_traces(traces):
    return list({str(field(run, "id")): run for runs in traces.values() for run in runs}.values())


def skill_counts(runs):
    return Counter(name for run in runs if (name := skill_name(run)))


def mcp_counts(runs):
    return Counter(tool_name(run) for run in runs if field(run, "run_type") == "tool"
                   and tool_name(run).startswith("mcp__"))


async def load_traces(client, project, since, max_turns=30, filter=None):
    roots = await query_turns(client, project, since=since, filter=filter, max_runs=max_turns)
    completed = [root for root in roots if field(root, "end_time")]
    if not completed:
        raise ValueError("No completed turns in the selected window.")
    print(f"Analyzing {len(completed)} completed turns; {len(roots) - len(completed)} still running.")
    return {str(field(root, "id")): await read_trace(client, project, root) for root in completed}


def read_feedback(client, runs, keys):
    ids = list(dict.fromkeys(str(field(run, "id")) for run in runs))
    feedback = []
    for start in range(0, len(ids), 50):
        feedback.extend(client.list_feedback(run_ids=ids[start:start + 50], feedback_key=keys))
    return feedback


def latest_scores(feedback, key):
    by_run = {}
    for item in sorted(feedback, key=lambda item: str(field(item, "created_at", ""))):
        score = field(item, "score")
        if field(item, "key") == key and isinstance(score, (float, int)) and math.isfinite(score):
            by_run[str(field(item, "run_id"))] = float(score)
    return by_run


def show_feedback(client, roots):
    keys = ["output_quality", "task_completion", "session_outcome"]
    records = read_feedback(client, roots, keys)
    by_run = defaultdict(dict)
    for item in sorted(records, key=lambda item: str(field(item, "created_at", ""))):
        value = field(item, "value")
        by_run[str(field(item, "run_id"))][field(item, "key")] = value if value is not None else field(item, "score")
    display_table([{"turn": str(field(root, "id"))[:8],
                    **{key: by_run[str(field(root, "id"))].get(key, "pending / unscored") for key in keys}}
                   for root in roots])
    return records


def label_counts(feedback):
    counts = Counter()
    for item in feedback:
        if field(item, "key") == "skill_name":
            value = field(item, "value")
            counts.update([value] if isinstance(value, str) else (value or []))
    return counts


def show_skill_feedback(runs, feedback):
    """Show both decision-level feedback types without guessing rule eligibility."""
    latest = {}
    for item in sorted(feedback, key=lambda item: str(field(item, "created_at", ""))):
        latest[(str(field(item, "run_id")), field(item, "key"))] = item
    rows = []
    for run in runs:
        calls = [call for call in tool_calls(run) if call["name"] == "Skill"]
        if field(run, "run_type") != "llm" or not calls:
            continue
        run_id = str(field(run, "id"))
        labels = field(latest.get((run_id, "skill_name")), "value")
        score = latest_scores([latest.get((run_id, "skill_selection"))], "skill_selection").get(run_id)
        missing = [key for key, value in (("skill_name", labels), ("skill_selection", score)) if value is None]
        rows.append({"decision run": run_id, "selected skills": [call["args"].get("skill") for call in calls],
                     "skill_name": labels, "skill_selection": score,
                     "feedback": "complete" if not missing else "missing " + ", ".join(missing)})
    display_table(rows)
    if any(row["feedback"] != "complete" for row in rows):
        print("Missing feedback can be pre-registration, pending, or not evaluated. "
              "Check rule eligibility and execution logs; use a fresh Skill turn after registration.")
    return rows


def cohort(runs):
    names = sorted(skill_counts(runs))
    return (names[0] if len(names) == 1 else "multiple_skills" if names else "no_skill"), names


def cohort_filters(traces):
    """Partition the sampled roots without modifying completed traces."""
    groups = defaultdict(list)
    for root_id, runs in traces.items():
        group, _ = cohort(runs)
        groups[group].append(str(root_id))
    display_table([{"skill group": name, "turns": len(ids)} for name, ids in sorted(groups.items())])
    return [{"name": name, "filter": f'and(eq(is_root, true), in(id, {json.dumps(sorted(ids))}))'}
            for name, ids in sorted(groups.items())]


def cohort_chart_specs(title, metric, cohorts, feedback_key=None):
    """Split a complete comparison into legacy charts of at most three series."""
    if not cohorts:
        raise ValueError("Load completed turns before building comparison charts.")
    specs = []
    for start in range(0, len(cohorts), 3):
        suffix = f" ({start // 3 + 1})" if len(cohorts) > 3 else ""
        spec = {"title": title + suffix, "metric": metric, "cohorts": cohorts[start:start + 3]}
        if feedback_key:
            spec["feedback_key"] = feedback_key
        specs.append(spec)
    return specs


def turn_metrics(traces, scores=None):
    groups = defaultdict(lambda: {"turns": 0, "known_costs": [], "scores": []})
    for root_id, runs in traces.items():
        root = next(run for run in runs if str(field(run, "id")) == root_id)
        group, _ = cohort(runs)
        row = groups[group]
        row["turns"] += 1
        cost = turn_cost(root)
        if cost is not None:
            row["known_costs"].append(float(cost))
        if scores and root_id in scores:
            row["scores"].append(scores[root_id])
    return [{"skill group": name, "turns": row["turns"],
             "total cost ($)": sum(row["known_costs"]) if row["known_costs"] else None,
             "costed turns": len(row["known_costs"]),
             "mean quality": sum(row["scores"]) / len(row["scores"]) if row["scores"] else None,
             "scored turns": len(row["scores"])} for name, row in sorted(groups.items())]


async def diagnose_missing_costs(client, project, traces, *, since):
    """Inspect missing measurements even when other sampled turns have costs."""
    missing = []
    for root_id, runs in traces.items():
        root = next(run for run in runs if str(field(run, "id")) == root_id)
        if turn_cost(root) is None:
            missing.append((root_id, runs))
    if not missing:
        return
    print(f"{len(missing)} of {len(traces)} sampled turns lack cost.", flush=True)
    candidates = []
    for root_id, runs in missing:
        llms = [run for run in runs if field(run, "run_type", "").lower() == "llm"]
        print(f"Unpriced turn {root_id}: {len(llms)} LLM spans; "
              f"{sum(field(run, 'total_cost') is not None for run in llms)} with recorded cost.", flush=True)
        candidates.extend((root_id, run) for run in llms)
    if not candidates:
        print("No LLM spans in the unpriced turns. There is no LLM price match to inspect in this sample.", flush=True)
        return
    # Prefer an actually unpriced LLM with usage, never one from a priced root.
    candidates.sort(key=lambda item: (field(item[1], "total_cost") is not None,
                                     not any(field(item[1], key) for key in
                                             ("total_tokens", "prompt_tokens", "completion_tokens"))))
    root_id, llm_run = candidates[0]
    print(f"Cost diagnostic selected root {root_id}, LLM {field(llm_run, 'id')}.", flush=True)
    from utils.coding_agent_diagnostics import print_diagnostics

    await print_diagnostics(client, project, llm_run=llm_run, since=since, trigger="missing-turn-costs")


async def diagnose_recent_costs(client, project, roots, *, since):
    """Run before Skill validation so a filter failure cannot hide cost evidence."""
    if not roots:
        print("No recent turns available for cost inspection.")
        return
    missing = [root for root in roots if turn_cost(root) is None]
    if not missing:
        print("All displayed recent turns have a recorded cost.")
        return
    print(f"{len(missing)} recent turns have unknown cost; inspecting at most two trace trees.", flush=True)
    from utils.coding_agent_diagnostics import _capture

    traces = {}
    for root in missing[:2]:
        result = await _capture(lambda: read_trace(client, project, root), "/api/v2/runs/query:cost-trace")
        if result["ok"]:
            traces[str(field(root, "id"))] = result["result"]
        else:
            print(json.dumps({"cost_trace_read": result}, ensure_ascii=True), flush=True)
    await diagnose_missing_costs(client, project, traces, since=since)


def ranked_bars(values, title, unit="", decimals=0):
    """Render an escaped horizontal ranking using existing IPython support."""
    from IPython.display import HTML, display

    known = sorted(((str(name), float(value)) for name, value in values.items()
                    if value is not None and math.isfinite(float(value))), key=lambda item: (-item[1], item[0]))
    if not known:
        print(f"{title}: no measured values yet.")
        return
    maximum = max(value for _, value in known) or 1
    rows = []
    for name, value in known:
        width = max(0, value / maximum * 100)
        rows.append(f"<tr><td style='padding:6px;max-width:400px;overflow-wrap:anywhere'>{html.escape(name)}</td>"
                    f"<td style='width:280px'><div style='width:{width:.2f}%;height:16px;background:#39796b'></div></td>"
                    f"<td style='padding:6px'>{value:.{decimals}f}{html.escape(unit)}</td></tr>")
    display(HTML(f"<h4>{html.escape(title)}</h4><table>{''.join(rows)}</table>"))


def configure_threads(client, project, root, idle_seconds=120):
    for name in ("inputs", "outputs"):
        if not isinstance((field(root, name) or {}).get("messages"), list):
            raise ValueError(f"Thread evaluation needs root {name}.messages. Inspect your plugin version.")
    if not thread_id(root):
        raise ValueError("Selected root has no thread ID.")
    if idle_seconds < 120:
        raise ValueError("Use at least 120 seconds of inactivity.")
    fresh = client.read_project(project_id=project.id)
    extra = dict(fresh.extra or {})
    if "thread_idle_seconds" in extra:
        idle_seconds = extra["thread_idle_seconds"]
    else:
        extra["thread_idle_seconds"] = idle_seconds
        client.update_project(project.id, project_extra=extra)
    print(f"Thread evaluator idle threshold: {idle_seconds} seconds.")


def skill_catalog(plugin_root):
    entries = []
    for path in sorted((plugin_root / "skills").glob("*/SKILL.md")):
        description = next(line.removeprefix("description: ") for line in path.read_text().splitlines()
                           if line.startswith("description: "))
        entries.append(f"workshop:{path.parent.name}: {description}")
    return "\n".join(entries)


def ensure_dashboard(client, project, web_url):
    title = f"Module 06 — {project.name}"
    sections = []
    for offset in range(0, 1000, 100):
        page = api_request(client, "GET", "/charts/section",
                           params={"title_contains": title, "limit": 100, "offset": offset})
        sections.extend(section for section in page if section["title"] == title)
        if len(page) < 100:
            break
    else:
        raise ValueError("Too many matching dashboard sections; narrow the title.")
    if len(sections) > 1:
        raise ValueError("Duplicate workshop dashboards; resolve them in the UI first.")
    section = sections[0] if sections else api_request(client, "POST", "/charts/section", json={
        "title": title, "description": "Skill invocations and turn cost/quality; refreshed by Module 6."})
    return {"id": section["id"], "url": f"{web_url.rstrip('/')}/o/{project.tenant_id}/dashboards/{section['id']}"}


def chart_series(client, project, spec, chart_format="legacy"):
    groups = spec.get("cohorts") or [{"name": spec["title"], "filter": spec["filter"]}]
    result = []
    for group in groups:
        series = {"name": group["name"], "metric": spec["metric"],
                  "filters": {"session": [str(project.id)], "filter": group["filter"]}}
        if spec.get("group_by"):
            series["group_by"] = {"attribute": "metadata", "path": spec["group_by"], "max_groups": 20}
        if spec.get("feedback_key"):
            series["feedback_key"] = spec["feedback_key"]
        result.append(series)
    if chart_format == "legacy":
        return result
    if chart_format != "v2":
        raise ValueError("chart_format must be legacy or v2.")
    converted = api_request(client, "POST", "/v1/platform/charts/convert-v2", json={
        "charts": [{"title": spec["title"], "chart_type": "bar", "series": result}]})
    converted_series = converted["charts"][0]["series"]
    if (len(converted_series) != len(result)
            or any(item.get("skipped") or not item.get("metric_definition") for item in converted_series)):
        raise ValueError("This server could not convert every workshop chart series.")
    fields = ("name", "metric_definition", "group_by_definitions", "filter_definition")
    return [{key: item[key] for key in fields if item.get(key) is not None} for item in converted_series]


def preview_charts(client, project, specs, since):
    """Preview canonical legacy queries; this endpoint does not serve v2 data."""
    results = []
    for spec in specs:
        series = [{"id": str(uuid4()), **item} for item in chart_series(client, project, spec)]
        data = api_request(client, "POST", "/charts/preview", json={
            "bucket_info": {"start_time": since.isoformat(), "end_time": datetime.now(timezone.utc).isoformat(),
                            "timezone": "UTC", "stride": {"minutes": 30}},
            "chart": {"series": series}})
        buckets = data.get("data") or []
        samples = None
        if spec.get("feedback_key"):
            samples = sum((item.get("value") or {}).get(spec["feedback_key"], {}).get("n", 0)
                          for item in buckets)
            if not samples:
                print(f"{spec['title']}: no numeric feedback in the chart yet. "
                      "Check the feedback table, then rerun this preview after processing catches up.")
        results.append({"chart": spec["title"], "buckets returned": len(buckets), "feedback samples": samples})
    display_table(results)
    return results


def section_read_body():
    """0.16.65 streams populated legacy sections even when omit_data is true."""
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    return {"omit_data": True, "start_time": (end - timedelta(minutes=1)).isoformat(),
            "end_time": end.isoformat(), "timezone": "UTC", "stride": {"minutes": 1}}


def ensure_charts(client, project, dashboard, specs, chart_format="legacy"):
    section = api_request(client, "POST", f"/charts/section/{dashboard['id']}", json=section_read_body())
    existing = section.get("charts") or []
    result = []
    for spec in specs:
        matches = [chart for chart in existing if chart["title"] == spec["title"]]
        if len(matches) > 1:
            raise ValueError(f"Duplicate chart title: {spec['title']}")
        series = chart_series(client, project, spec, chart_format)
        body = {"title": spec["title"], "chart_type": "bar", "section_id": dashboard["id"], "series": series}
        if matches:
            prior_series = matches[0].get("series") or []
            prior_ids = {item["name"]: item["id"] for item in prior_series}
            for item in series:
                item["id"] = prior_ids.get(item["name"]) or str(uuid4())
            chart = api_request(client, "PATCH", f"/charts/{matches[0]['id']}", json=body)
        else:
            chart = api_request(client, "POST", "/charts/create", json=body)
        result.append({"chart": spec["title"], "id": chart["id"]})
    display_table(result)
    return result


def set_project_dashboard(client, project, dashboard):
    """Use the workshop dashboard when the project has no custom default."""
    path = f"/sessions/{project.id}"
    current = api_request(client, "GET", path)
    metadata = dict((current.get("extra") or {}).get("metadata") or {})
    if not metadata.get("default_dashboard_id"):
        metadata["default_dashboard_id"] = dashboard["id"]
        api_request(client, "PATCH", path, json={"extra": {"metadata": metadata}})


def run_cli(arguments, api_url, project_name, workspace_id=None):
    executable = shutil.which("langsmith")
    if not executable:
        raise ValueError("Install the LangSmith CLI using the pre-work instructions.")
    env = {**os.environ, "LANGSMITH_ENDPOINT": api_url, "LANGSMITH_PROJECT": project_name}
    if workspace_id:
        env["LANGSMITH_WORKSPACE_ID"] = workspace_id
    else:
        env.pop("LANGSMITH_WORKSPACE_ID", None)
    result = subprocess.run([executable, *arguments], env=env, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError("LangSmith CLI failed. Check its version, endpoint, and authentication in the terminal.")
    print(result.stdout[:16000])
