"""Bounded, read-only Module 06 diagnostics. Reports exclude trace content and secrets."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import traceback
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import requests
from langsmith import APIError, Client
from langsmith.utils import LangSmithError

from utils import coding_agent_analytics as analytics
from utils import langsmith_rules as rules


ERRORS = (LangSmithError, APIError, requests.RequestException, TimeoutError, ValueError, RuntimeError, OSError)
COST_FIELDS = ("total_cost", "prompt_cost", "completion_cost", "total_tokens", "prompt_tokens", "completion_tokens")
RUN_SELECTS = ["ID", "TRACE_ID", "RUN_TYPE", "START_TIME", "END_TIME", "OUTPUTS", "EXTRA", "METADATA",
               "PRICE_MODEL_ID", *[name.upper() for name in COST_FIELDS]]
MODEL_FIELDS = ("ls_model_name", "ls_provider", "ls_integration_version", "ls_agent_runtime_version")
DIAGNOSTICS_VERSION = "2026-09-30.1"
REPORT_TIMEOUT_SECONDS = 120
PROBE_TIMEOUT_SECONDS = 20


class DiagnosticResponseError(ValueError):
    """Distinguish an unexpected response envelope from an empty query result."""

    def __init__(self, expected):
        self.expected = expected
        super().__init__("Unexpected diagnostic response shape.")


def _text(value):
    if value is None:
        return None
    text = str(value)
    if re.search(r"(?:lsv2_[a-z]+_|sk-|ghp_|xox[baprs]-)[A-Za-z0-9_-]{15,}", text):
        return "[redacted]"
    return text[:160]


def _timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise ValueError("Use an explicit timezone-aware timestamp for diagnostic bounds.")
    return result.astimezone(timezone.utc)


def _uuid(value):
    return str(UUID(str(value)))


def _dict(value):
    return value if isinstance(value, dict) else value.to_dict(mode="python", use_api_names=False)


def _error(exc, path):
    try:
        error = exc if isinstance(exc, rules.LangSmithRequestError) else rules._request_error("READ", path, exc)
    except Exception:
        # A malformed/streaming error response must not break error reporting too.
        error = rules.LangSmithRequestError("READ", path, category="error-classification-failed")
    return {"ok": False, "status": error.status_code,
            "category": "response-shape" if isinstance(exc, DiagnosticResponseError) else error.category,
            "operation": path,
            "expected": exc.expected if isinstance(exc, DiagnosticResponseError) else None,
            "request_id": _text(error.request_id), "error_type": type(exc).__name__,
            "location": [f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                         for frame in traceback.extract_tb(exc.__traceback__)[-3:]]}


async def _capture(call, path):
    try:
        # Legacy reads are synchronous. Keep them off the notebook event loop so
        # the report deadline can fire and completed probe output stays visible.
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            result = await asyncio.to_thread(call)
            if asyncio.iscoroutine(result):
                result = await result
        return {"ok": True, "result": result}
    except Exception as exc:
        # A diagnostic parse/SDK error must be reported without hiding other probes.
        return _error(exc, path)


def _rows(data, key):
    rows = data.get(key) if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) > 10 or any(not isinstance(row, dict) for row in rows):
        raise DiagnosticResponseError(f"{key}: list of at most 10 objects")
    return rows


def _one(rows, run_id):
    return next((row for row in rows if str(row.get("id")) == run_id), None)


def _measurement(row, name):
    if name not in row:
        return {"state": "absent"}
    value = row[name]
    if value is None:
        return {"state": "null"}
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return {"state": "value", "value": float(value)}
    return {"state": "non-numeric"}


def _cost_summary(row):
    return {"id": _text(row.get("id")), "price_model_id": _text(row.get("price_model_id")),
            **{key: _measurement(row, key) for key in COST_FIELDS}}


async def _modern_runs(client, project_id, ids, since, until, predicate=None, selects=None):
    kwargs = dict(project_ids=[project_id], ids=ids, min_start_time=since, max_start_time=until,
                  selects=selects or analytics.RUN_FIELDS, page_size=10, timeout=10)
    if predicate:
        kwargs["filter"] = predicate
    async with asyncio.timeout(35):
        response = await client.runs.with_raw_response.query(**kwargs)
        raw = await response.json()
        result = {"raw": _rows(raw, "items"), "sdk": [],
                  "status": getattr(response, "status_code", None),
                  "request_id": _text(getattr(response, "headers", {}).get("x-request-id"))}
        try:
            parsed = await response.parse()
            result["sdk"] = [_dict(row) for row in parsed.items]
        except Exception as exc:
            result["sdk_error"] = _error(exc, "/api/v2/runs/query:parse")
    return result


def _legacy_runs(client, project_id, ids, since, until, predicate=None):
    body = {"session": [project_id], "id": ids, "start_time": since.isoformat(),
            "end_time": until.isoformat(), "limit": 10,
            "select": [name.lower() for name in RUN_SELECTS if name != "METADATA"]}
    if predicate:
        body["filter"] = predicate
    return _rows(rules.api_request(client, "POST", "/runs/query", json=body, timeout=10), "runs")


def _match_summary(result, run_id, modern=False):
    if not result["ok"]:
        return result
    rows = result["result"]["raw"] if modern else result["result"]
    summary = {"ok": True, "matched": _one(rows, run_id) is not None,
               "returned_ids": [_text(row.get("id")) for row in rows]}
    if modern:
        summary.update({"status": result["result"]["status"], "request_id": result["result"]["request_id"],
                        "sdk_matched": _one(result["result"]["sdk"], run_id) is not None,
                        "sdk_returned_ids": [_text(row.get("id")) for row in result["result"]["sdk"]]})
        if "sdk_error" in result["result"]:
            summary["sdk_error"] = result["result"]["sdk_error"]
    return summary


def _payload_summary(run):
    """Evidence about the call's shape, never its content or arguments."""
    calls = analytics.tool_calls(run)
    return {"id": _text(analytics.field(run, "id")),
            "trace_id": _text(analytics.field(run, "trace_id")),
            "start_time": _text(analytics.field(run, "start_time")),
            "run_type": _text(analytics.field(run, "run_type")),
            "skill_call_count": sum(call["name"] == "Skill" for call in calls),
            "observed_call_path": analytics.observed_call_path(run) if calls else None}


async def _trace_costs(client, project_id, trace_id, since, until):
    async with asyncio.timeout(35):
        response = await client.traces.with_raw_response.query(
            project_id=project_id, trace_ids=[trace_id], min_start_time=since, max_start_time=until,
            selects=["ID", "TRACE_ID", *[key.upper() for key in COST_FIELDS]], page_size=10, timeout=10,
        )
        raw = _rows(await response.json(), "items")
        try:
            parsed = await response.parse()
            sdk = [_dict(row) for row in parsed.items]
            sdk_error = None
        except Exception as exc:
            sdk, sdk_error = [], _error(exc, "/api/v2/traces/query:parse")
    result = {}
    for source, traces in (("raw", raw), ("sdk", sdk)):
        result[source] = [{"root_id": _text((trace.get("root_run") or {}).get("id")),
                           "aggregates": _cost_summary(trace.get("trace_aggregates") or {})} for trace in traces]
    if sdk_error:
        result["sdk_error"] = sdk_error
    return result


def _pricing(client, model, price_model_id=None):
    """Candidate search only: q is substring search, not the server's price matcher."""
    rows = []
    complete = False
    provider = model.get("ls_provider")
    for offset in range(0, 300, 100):
        params = {"limit": 100, "offset": offset}
        if provider:
            params["q"] = provider
        page = rules.api_request(client, "GET", "/model-price-map/", params=params, timeout=10)
        if not isinstance(page, list) or len(page) > 100:
            raise ValueError("Unexpected pricing page shape.")
        rows.extend(page)
        if len(page) < 100:
            complete = True
            break
    compatible = [row for row in rows if not row.get("provider") or not provider
                  or str(row["provider"]).lower() == provider.lower()]
    model_name = (model.get("ls_model_name") or "").lower()
    compatible.sort(key=lambda row: (str(row.get("id")) != price_model_id,
                                    model_name not in str(row.get("name", "")).lower()))
    return {"search": provider, "search_complete": complete, "returned": len(rows),
            "compatible_provider_candidates": len(compatible),
            "recorded_price_id_in_results": any(str(row.get("id")) == price_model_id for row in rows)
            if price_model_id else None,
            "candidates": [{key: _text(row.get(key)) for key in
                            ("id", "name", "provider", "match_pattern", "start_time")} for row in compatible[:20]],
            "candidates_truncated": len(compatible) > 20,
            "note": "Candidate substring search only; absent results do not prove no matching price. "
                    "Check the actual model, provider, activation date, rates and cache-token prices in the UI."}


def _rule_summary(client, project_id, predicate):
    entries = rules.api_request(client, "GET", "/runs/rules", params={"session_id": project_id}, timeout=10)
    if not isinstance(entries, list) or len(entries) > 1000:
        raise ValueError("Unexpected rule list shape or size.")
    result = []
    for rule in entries:
        name = rule.get("display_name")
        if name not in {"module06-skill-name", "module06-skill-selection"}:
            continue
        entry = {"id": _text(rule.get("id")), "name": name, "enabled": rule.get("is_enabled") is True,
                 "sampling_rate": _measurement(rule, "sampling_rate"),
                 "filter_matches_observed": rule.get("filter") == predicate}
        path = f"/runs/rules/{_uuid(rule['id'])}/logs"
        try:
            logs = rules.api_request(client, "GET", path, params={"limit": 10}, timeout=10)
            if not isinstance(logs, list) or len(logs) > 10:
                raise ValueError("Unexpected evaluator log page.")
            outcomes = [(log.get("evaluators") or {}).get("outcome") for log in logs]
            entry["recent_log_outcomes"] = dict(Counter(
                outcome if outcome in {"success", "error", "skipped"} else "other" for outcome in outcomes))
        except ERRORS as exc:
            entry["recent_logs"] = _error(exc, path)
        result.append(entry)
    return result


async def _dashboard_summary(client, dashboard_id):
    report = {"id": dashboard_id}
    endpoint = f"/charts/section/{dashboard_id}"
    for label, body in (("without_window", {"omit_data": True}), ("bounded_window", analytics.section_read_body())):
        result = await _capture(lambda: rules.api_request(client, "POST", endpoint, json=body, timeout=10), endpoint)
        report[label] = ({"ok": True, "chart_ids": [
            _text(chart.get("id")) for chart in (result["result"].get("charts") or [])]}
            if result["ok"] else result)
    return report


async def collect_diagnostics(client, project, *, llm_run_id, since, until=None,
                              dashboard_id=None, include_pricing=False, observed_run=None,
                              requested_filter=None, emit=None):
    """Read one known LLM/root and optional dashboard; never create or update resources."""
    project_id, llm_id = _uuid(project.id), _uuid(llm_run_id)
    if dashboard_id is not None:
        dashboard_id = _uuid(dashboard_id)
    since = _timestamp(since)
    until = _timestamp(until or datetime.now(timezone.utc))
    if until <= since:
        raise ValueError("The diagnostic end must follow its start.")
    def publish(section, value):
        if emit is not None:
            emit(section, value)

    parsed_url = urlsplit(str(getattr(client, "api_url", "")))
    host = parsed_url.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parsed_url.port is not None:
        host += f":{parsed_url.port}"
    safe_url = urlunsplit((parsed_url.scheme, host, parsed_url.path, "", ""))
    report = {"diagnostics_version": DIAGNOSTICS_VERSION, "api_url": _text(safe_url),
              "project_id": project_id, "workspace_id": _text(analytics.field(project, "tenant_id")),
              "llm_run_id": llm_id, "since": since.isoformat(), "until": until.isoformat(),
              "sdk_version": version("langsmith"), "requested_filter": _text(requested_filter),
              "v2_probe_selects": analytics.RUN_FIELDS,
              "query_paths": {"legacy": "/runs/query", "v2": "/api/v2/runs/query"}}
    publish("scope", report.copy())
    if observed_run is not None:
        report["selected_payload"] = _payload_summary(observed_run)
        publish("selected_payload", report["selected_payload"])
    info = await _capture(lambda: rules.api_request(client, "GET", "/info", timeout=10), "/info")
    if info["ok"]:
        report["server_version"] = (_text(info["result"].get("version")) if isinstance(info["result"], dict)
                                    else _error(DiagnosticResponseError("info object"), "/info"))
    else:
        report["server_version"] = info
    publish("server_version", report["server_version"])
    if dashboard_id:
        dashboard_result = await _capture(lambda: _dashboard_summary(client, dashboard_id), "/charts/section")
        report["dashboard"] = dashboard_result["result"] if dashboard_result["ok"] else dashboard_result
        publish("dashboard", report["dashboard"])
    report["skill_probes"] = []

    async def probe(label, predicate=None):
        publish("probe_started", {"probe": label, "filter": _text(predicate)})

        async def execute(backend, call):
            result = await _capture(call, report["query_paths"][backend])
            summary = _match_summary(result, llm_id, modern=backend == "v2")
            publish("skill_probe", {"probe": label, "filter": _text(predicate),
                                    "backend": backend, **summary})
            return result, summary

        old, new = await asyncio.gather(
            execute("legacy", lambda: _legacy_runs(client, project_id, [llm_id], since, until, predicate)),
            execute("v2", lambda: _modern_runs(client, project_id, [llm_id], since, until, predicate)),
        )
        report["skill_probes"].append({"probe": label, "filter": _text(predicate),
                                       "legacy": old[1], "v2": new[1]})
        return old[0], new[0]

    legacy, modern = await probe("id only")
    run = (_one(legacy["result"], llm_id) if legacy["ok"] else None)
    if run is None and modern["ok"]:
        run = _one(modern["result"]["raw"], llm_id)
    if run is None:
        report["next_step"] = "The known run did not resolve. Check project, run ID, connection and fixed time bounds."
        publish("next_step", report["next_step"])
        if observed_run is None:
            return report
        run = _dict(observed_run)
        report["payload_source"] = "already loaded notebook run; ID-only queries did not resolve it"
    else:
        report["payload_source"] = "ID-only query"
    publish("payload_source", report["payload_source"])
    report["queried_payload"] = _payload_summary(run)
    publish("queried_payload", report["queried_payload"])
    run = {**run, "run_type": (run.get("run_type") or "").lower()}
    report["model"] = {key: _text(analytics.metadata(run).get(key)) for key in MODEL_FIELDS}
    publish("model", report["model"])
    has_skill = any(call["name"] == "Skill" for call in analytics.tool_calls(run))
    report["payload_has_skill_call"] = has_skill
    predicate = None
    probes = [("LLM type", 'eq(run_type, "llm")'),
              ("shallow output pair", 'and(eq(output_key, "messages.role"), eq(output_value, "assistant"))')]
    if has_skill:
        path = analytics.observed_call_path(run)
        report["observed_call_path"] = path
        key = f'eq(output_key, {json.dumps(path)})'
        value = 'eq(output_value, "Skill")'
        predicate = f'and(eq(run_type, "llm"), {key}, {value})'
        probes += [("output key", key), ("output value", value),
                   ("output pair", f"and({key}, {value})"), ("full Skill filter", predicate)]
    if requested_filter and requested_filter != predicate:
        probes.append(("actual notebook filter", requested_filter))
    for label, query in probes:
        await probe(label, query)

    report["costs"] = {}
    # Extra cost/pricing selects must not change the queries used to diagnose the
    # original filter. Retain baseline evidence if a deployment rejects them.
    detail = await _capture(lambda: _modern_runs(client, project_id, [llm_id], since, until,
                                                 selects=RUN_SELECTS), "/api/v2/runs/query:cost-fields")
    publish("cost_detail_query", _match_summary(detail, llm_id, modern=True))
    if detail["ok"]:
        detail_run = _one(detail["result"]["raw"], llm_id)
        if detail_run is not None:
            run = {**run, **{key: detail_run[key] for key in (*COST_FIELDS, "price_model_id") if key in detail_run}}
            modern = detail
    for label, result in (("legacy LLM", legacy), ("v2 LLM", modern)):
        if result["ok"]:
            rows = result["result"] if label.startswith("legacy") else result["result"]["raw"]
            report["costs"][label] = [_cost_summary(row) for row in rows]
        else:
            report["costs"][label] = result
        publish("costs: " + label, report["costs"][label])
    if modern["ok"]:
        report["costs"]["SDK LLM"] = modern["result"].get("sdk_error", [
            _cost_summary(row) for row in modern["result"]["sdk"]])
        publish("costs: SDK LLM", report["costs"]["SDK LLM"])
    trace_id = _uuid(run.get("trace_id") or llm_id)
    traces = await _capture(lambda: _trace_costs(client, project_id, trace_id, since, until), "/api/v2/traces/query")
    report["costs"]["trace"] = traces["result"] if traces["ok"] else traces
    publish("costs: trace", report["costs"]["trace"])
    root_ids = {row["root_id"] for row in traces["result"]["raw"] if row.get("root_id")} if traces["ok"] else set()
    root_id = _uuid(next(iter(root_ids))) if len(root_ids) == 1 else trace_id
    report["costs"]["root_id_source"] = "trace response" if len(root_ids) == 1 else "assumed equal to trace_id; verify"
    publish("root_scope", {"root_id": root_id, "trace_id": trace_id,
                           "source": report["costs"]["root_id_source"]})
    roots = await _capture(lambda: _legacy_runs(client, project_id, [root_id], since, until), "/runs/query")
    report["costs"]["legacy root"] = [_cost_summary(row) for row in roots["result"]] if roots["ok"] else roots
    publish("costs: legacy root", report["costs"]["legacy root"])
    v2_roots = await _capture(lambda: _modern_runs(client, project_id, [root_id], since, until), "/api/v2/runs/query")
    for source in ("raw", "sdk"):
        report["costs"][f"v2 root {source}"] = ([_cost_summary(row) for row in v2_roots["result"][source]]
                                                    if v2_roots["ok"] else v2_roots)
        if source == "sdk" and v2_roots["ok"] and "sdk_error" in v2_roots["result"]:
            report["costs"][f"v2 root {source}"] = v2_roots["result"]["sdk_error"]
        publish(f"costs: v2 root {source}", report["costs"][f"v2 root {source}"])
    normalized = await _capture(lambda: analytics.query_turns(
        client, project, since=since, ids=[root_id], max_start_time=until, max_runs=1), "/api/v2/runs/query")
    report["costs"]["helper root"] = ([{"id": _text(row.get("id")),
                                          "trace_total_cost": _measurement(row, "trace_total_cost"),
                                          "root_total_cost": _measurement(row, "total_cost")}
                                         for row in normalized["result"]] if normalized["ok"] else normalized)
    publish("costs: helper root", report["costs"]["helper root"])
    selected = await _capture(lambda: _rule_summary(client, project_id, predicate), "/runs/rules")
    report["skill_rules"] = selected["result"] if selected["ok"] else selected
    publish("skill_rules", report["skill_rules"])
    if include_pricing:
        prices = await _capture(lambda: _pricing(client, report["model"], run.get("price_model_id")), "/model-price-map/")
        report["pricing"] = prices["result"] if prices["ok"] else prices
        publish("pricing", report["pricing"])
    return report


async def print_diagnostics(client, project, *, llm_run, since, trigger, requested_filter=None,
                            original_error=None, dashboard_id=None):
    """Stream a bounded report into the current cell, including partial failures."""
    def emit(section, value):
        print(json.dumps({section: value}, indent=2, ensure_ascii=True), flush=True)

    print("=== MODULE 06 DIAGNOSTICS BEGIN ===", flush=True)
    emit("diagnostic_start", {"version": DIAGNOSTICS_VERSION, "trigger": trigger,
                              "time_budget_seconds": REPORT_TIMEOUT_SECONDS,
                              "instructions": "Wait for DIAGNOSTICS END, then export HTML with this cell output."})
    report = None
    try:
        if original_error is not None:
            emit("original_error", _error(original_error, "/notebook/" + trigger))
        async with asyncio.timeout(REPORT_TIMEOUT_SECONDS):
            report = await collect_diagnostics(
                client, project, llm_run_id=analytics.field(llm_run, "id"), since=since,
                observed_run=llm_run, requested_filter=requested_filter, dashboard_id=dashboard_id,
                include_pricing=True, emit=emit,
            )
        emit("diagnostic_end", {"status": "finished", "note": "Individual probe errors are recorded above."})
    except Exception as exc:
        emit("diagnostic_end", {"status": "incomplete", "error": _error(exc, "/diagnostics"),
                                "note": "Keep the partial results above; the original issue remains unresolved."})
    finally:
        print("=== MODULE 06 DIAGNOSTICS END ===", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Exact existing participant project name")
    parser.add_argument("--llm-run-id", required=True, type=_uuid)
    parser.add_argument("--since", required=True, type=_timestamp)
    parser.add_argument("--until", type=_timestamp)
    parser.add_argument("--dashboard-id", type=_uuid)
    parser.add_argument("--include-pricing", action="store_true")
    args = parser.parse_args()
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
    try:
        client = Client(api_url=os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
                        workspace_id=os.getenv("LANGSMITH_WORKSPACE_ID") or os.getenv("WORKSPACE_ID"),
                        auto_batch_tracing=False)
        project = client.read_project(project_name=args.project)
        report = asyncio.run(collect_diagnostics(client, project, llm_run_id=args.llm_run_id,
                            since=args.since, until=args.until, dashboard_id=args.dashboard_id,
                            include_pricing=args.include_pricing))
    except ERRORS as exc:
        print(json.dumps(_error(exc, "/diagnostics"), indent=2))
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
