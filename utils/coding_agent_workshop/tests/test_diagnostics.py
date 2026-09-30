"""Diagnostic reports must stay scoped, bounded, and free of trace contents."""

import copy
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from utils import coding_agent_diagnostics as diagnostics
from utils import langsmith_rules as rules


PROJECT = "10000000-0000-4000-8000-000000000001"
LLM = "10000000-0000-4000-8000-000000000002"
ROOT = "10000000-0000-4000-8000-000000000003"
DASHBOARD = "10000000-0000-4000-8000-000000000004"


class RawResponse:
    def __init__(self, items):
        self.items = items

    async def json(self):
        return {"items": copy.deepcopy(self.items)}

    async def parse(self):
        return SimpleNamespace(items=copy.deepcopy(self.items))


class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.project = SimpleNamespace(id=PROJECT, tenant_id=PROJECT)
        self.since = datetime(2026, 9, 29, tzinfo=timezone.utc)
        self.until = datetime(2026, 9, 30, tzinfo=timezone.utc)
        self.run = {"id": LLM, "trace_id": ROOT, "run_type": "llm", "total_cost": None,
                    "prompt_cost": 0, "total_tokens": 100,
                    "extra": {"metadata": {"ls_model_name": "claude-example", "ls_provider": "anthropic",
                                           "ls_integration_version": "0.3.1", "private": "PRIVATE-METADATA"}},
                    "outputs": {"messages": [{"role": "assistant", "content": [
                        {"type": "text", "text": "PRIVATE-TRACE"},
                        {"type": "tool_call", "name": "Skill", "args": {"skill": "PRIVATE-ARG"}}]}]}}
        self.root = {"id": ROOT, "total_cost": 2.17, "total_tokens": 100}
        self.calls = []

        async def modern(**kwargs):
            self.assertEqual(kwargs["project_ids"], [PROJECT])
            self.assertEqual(kwargs["min_start_time"], self.since)
            self.assertEqual(kwargs["max_start_time"], self.until)
            self.assertLessEqual(kwargs["page_size"], 10)
            return RawResponse([self.run if kwargs["ids"] == [LLM] else self.root])

        self.client = SimpleNamespace(
            runs=SimpleNamespace(with_raw_response=SimpleNamespace(query=modern)),
            traces=SimpleNamespace(with_raw_response=SimpleNamespace(query=AsyncMock(return_value=RawResponse([
                {"root_run": {"id": ROOT}, "trace_aggregates": {"total_cost": 2.17}}])))),
        )

    def api(self, client, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if (method, path) == ("GET", "/info"):
            return {"version": "0.16.65", "private": "PRIVATE-SERVER"}
        if (method, path) == ("POST", "/runs/query"):
            body = kwargs["json"]
            self.assertEqual(body["session"], [PROJECT])
            self.assertEqual(body["start_time"], self.since.isoformat())
            self.assertEqual(body["end_time"], self.until.isoformat())
            self.assertIn(body["id"], ([LLM], [ROOT]))
            if "output_value" in body.get("filter", ""):
                return {"runs": []}
            return {"runs": [self.run if body["id"] == [LLM] else self.root]}
        if (method, path) == ("GET", "/runs/rules"):
            self.assertEqual(kwargs["params"], {"session_id": PROJECT})
            return [{"id": PROJECT, "display_name": "module06-skill-name", "is_enabled": True,
                     "sampling_rate": 1.0, "evaluators": {"private": "PRIVATE-JUDGE"}}]
        if (method, path) == ("GET", f"/runs/rules/{PROJECT}/logs"):
            self.assertEqual(kwargs["params"], {"limit": 10})
            return [{"evaluators": {"outcome": "success", "message": "PRIVATE-LOG"}}]
        if (method, path) == ("GET", "/model-price-map/"):
            raise rules.LangSmithRequestError(method, path, status=403, category="permissions")
        if method == "POST" and path == f"/charts/section/{DASHBOARD}":
            if not kwargs["json"].get("start_time"):
                raise rules.LangSmithRequestError(method, path, status=404, category="chart-time-window")
            return {"charts": [{"id": PROJECT, "private": "PRIVATE-CHART"}]}
        self.fail(f"Unexpected operation {method} {path}")

    async def test_report_compares_paths_without_trace_or_provider_payloads(self):
        with patch.object(rules, "api_request", side_effect=self.api), \
                patch.object(diagnostics.analytics, "query_turns", new_callable=AsyncMock,
                             return_value=[{**self.root, "trace_total_cost": None}]):
            report = await diagnostics.collect_diagnostics(
                self.client, self.project, llm_run_id=LLM, since=self.since, until=self.until,
                dashboard_id=DASHBOARD, include_pricing=True)
        self.assertNotIn("PRIVATE-", json.dumps(report))
        self.assertEqual(report["observed_call_path"], "messages.content.name")
        self.assertEqual(len(report["skill_probes"]), 7)
        self.assertFalse(report["skill_probes"][-1]["legacy"]["matched"])
        self.assertTrue(report["skill_probes"][-1]["v2"]["matched"])
        costs = report["costs"]["legacy LLM"][0]
        self.assertEqual(costs["total_cost"], {"state": "null"})
        self.assertEqual(costs["prompt_cost"], {"state": "value", "value": 0})
        self.assertEqual(costs["completion_cost"], {"state": "absent"})
        self.assertEqual(report["costs"]["helper root"][0]["trace_total_cost"], {"state": "null"})
        self.assertEqual(report["dashboard"]["without_window"]["category"], "chart-time-window")
        self.assertTrue(report["dashboard"]["bounded_window"]["ok"])
        self.assertEqual(report["pricing"]["category"], "permissions")
        self.assertEqual(report["skill_rules"][0]["recent_log_outcomes"], {"success": 1})

    async def test_root_id_comes_from_trace_response_instead_of_assuming_trace_id(self):
        self.run["trace_id"] = DASHBOARD
        with patch.object(rules, "api_request", side_effect=self.api), \
                patch.object(diagnostics.analytics, "query_turns", new_callable=AsyncMock, return_value=[]) as normalized:
            report = await diagnostics.collect_diagnostics(self.client, self.project, llm_run_id=LLM,
                                                           since=self.since, until=self.until)
        self.assertEqual(normalized.call_args.kwargs["ids"], [ROOT])
        self.assertEqual(report["costs"]["root_id_source"], "trace response")
        self.assertEqual(report["costs"]["v2 root raw"][0]["id"], ROOT)

    async def test_missing_run_does_not_skip_independent_dashboard_check(self):
        async def empty_modern(**kwargs):
            return RawResponse([])

        def api(client, method, path, **kwargs):
            return {"runs": []} if path == "/runs/query" else self.api(client, method, path, **kwargs)

        self.client.runs.with_raw_response.query = empty_modern
        with patch.object(rules, "api_request", side_effect=api):
            report = await diagnostics.collect_diagnostics(self.client, self.project, llm_run_id=LLM,
                since=self.since, until=self.until, dashboard_id=DASHBOARD)
        self.assertIn("did not resolve", report["next_step"])
        self.assertTrue(report["dashboard"]["bounded_window"]["ok"])

    async def test_invalid_scope_is_rejected_before_network(self):
        with patch.object(rules, "api_request") as api:
            with self.assertRaises(ValueError):
                await diagnostics.collect_diagnostics(self.client, self.project, llm_run_id="bad", since=self.since)
            with self.assertRaises(ValueError):
                await diagnostics.collect_diagnostics(self.client, self.project, llm_run_id=LLM,
                                                      since=self.since, until=self.since)
            with self.assertRaises(ValueError):
                await diagnostics.collect_diagnostics(self.client, self.project, llm_run_id=LLM, since="2026-09-29")
            api.assert_not_called()

    def test_pricing_candidate_search_is_bounded_and_does_not_claim_a_match(self):
        page = [{"id": PROJECT, "name": "candidate"}] * 100
        with patch.object(rules, "api_request", return_value=page) as api:
            result = diagnostics._pricing(self.client, {"ls_provider": "anthropic"})
        self.assertEqual(api.call_count, 3)
        self.assertFalse(result["search_complete"])
        self.assertTrue(result["candidates_truncated"])
        self.assertEqual(len(result["candidates"]), 20)
        self.assertIn("do not prove", result["note"])

    def test_recorded_price_is_visible_and_other_provider_candidates_are_excluded(self):
        rows = [{"id": str(index), "name": "bedrock", "provider": "amazon_bedrock"} for index in range(30)]
        rows += [{"id": PROJECT, "name": "claude-example", "provider": "anthropic"}]
        with patch.object(rules, "api_request", return_value=rows):
            result = diagnostics._pricing(self.client, {"ls_provider": "anthropic", "ls_model_name": "claude-example"}, PROJECT)
        self.assertTrue(result["recorded_price_id_in_results"])
        self.assertEqual([row["id"] for row in result["candidates"]], [PROJECT])


if __name__ == "__main__":
    unittest.main()
