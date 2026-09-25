"""Plumbing for Module 6; the notebook keeps filters, rubrics, and metrics visible."""

from __future__ import annotations

import html
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from langsmith import Client
from langsmith.utils import LangSmithNotFoundError

from utils.langsmith_rules import api_request


def field(obj, name, default=None):
    """Read SDK objects and JSON fixtures through the same small interface."""
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def metadata(run):
    return (field(run, "extra") or {}).get("metadata") or {}


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
    if "smith.langchain.com" not in urlsplit(api_url).hostname and "smith.langchain.com" in web_url:
        raise ValueError("Set LANGSMITH_WEB_URL to your self-hosted UI URL too.")
    print("LangSmith credential: set")
    print("API:", api_url)
    print("UI: ", web_url)


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
    return info.get("thread_id") or info.get("session_id") or info.get("conversation_id")


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
                    "type": field(run, "run_type"), "cost ($)": field(run, "total_cost"),
                    "thread": thread_id(run), "link": run_url(run, project, web_url)} for run in runs])


def require_first(items, message="No traces yet. Complete the smoke task and rerun the query."):
    if not items:
        raise ValueError(message)
    return items[0]


def read_trace(client, project_name, root, max_runs=500):
    """Fetch a complete trace or fail rather than silently omit tool runs."""
    # Let the SDK use the server's page size; its limit parameter is also sent
    # to the API, which can reject values above 100 even for a whole trace.
    query = client.list_runs(project_name=project_name, trace_id=field(root, "trace_id"))
    runs = list(islice(query, max_runs + 1))
    if len(runs) > max_runs:
        raise ValueError(f"Trace exceeds {max_runs} runs; raise max_runs before analyzing it.")
    if str(field(root, "id")) not in {str(field(run, "id")) for run in runs}:
        raise ValueError("Trace is still arriving; rerun this cell when its root is available.")
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


def load_traces(client, project_name, since, max_turns=30, filter=None):
    query = client.list_runs(project_name=project_name, is_root=True, start_time=since, filter=filter)
    roots = list(islice(query, max_turns + 1))
    if len(roots) > max_turns:
        raise ValueError(f"More than {max_turns} turns in this window. Narrow since or increase max_turns.")
    completed = [root for root in roots if field(root, "end_time")]
    if not completed:
        raise ValueError("No completed turns in the selected window.")
    print(f"Analyzing {len(completed)} completed turns; {len(roots) - len(completed)} still running.")
    return {str(root.id): read_trace(client, project_name, root) for root in completed}


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
        cost = field(root, "total_cost")
        if cost is not None:
            row["known_costs"].append(float(cost))
        if scores and root_id in scores:
            row["scores"].append(scores[root_id])
    return [{"skill group": name, "turns": row["turns"],
             "total cost ($)": sum(row["known_costs"]) if row["known_costs"] else None,
             "costed turns": len(row["known_costs"]),
             "mean quality": sum(row["scores"]) / len(row["scores"]) if row["scores"] else None,
             "scored turns": len(row["scores"])} for name, row in sorted(groups.items())]


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
        results.append({"chart": spec["title"], "buckets returned": len(data.get("data") or [])})
    display_table(results)
    return results


def ensure_charts(client, project, dashboard, specs, chart_format="legacy"):
    section = api_request(client, "POST", f"/charts/section/{dashboard['id']}", json={"omit_data": True})
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
