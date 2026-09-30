"""Regressions from the September 29 export and the 0.16.65 read contract."""

import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests

from utils import coding_agent_analytics as analytics
from utils import langsmith_rules as rules
from utils.coding_agent_workshop.tests.test_module06 import FakeClient, ROOT


def notebook_cells():
    notebook = json.loads((ROOT / "modules/06_coding_agent_analytics.ipynb").read_text())
    return {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}


class LegacySectionClient(FakeClient):
    """Model the release's populated-section streaming despite omit_data=True."""

    def request_with_retries(self, method, path, **kwargs):
        if path.startswith("/charts/section/"):
            body = kwargs["request_kwargs"].get("json", {})
            detail = None
            if not any(section["id"] == path.rsplit("/", 1)[-1] for section in self.sections):
                detail = "Section not found"
            elif any(not any(s.get("metric_definition") for s in chart["series"]) for chart in self.charts):
                if not body.get("start_time"):
                    detail = "start_time must be set."
                elif not body.get("end_time"):
                    detail = "end_time must be set."
            if detail:
                response = requests.Response()
                response.status_code = 404
                response._content = json.dumps({"detail": detail}).encode()
                return response
        return super().request_with_retries(method, path, **kwargs)


class DashboardRerunTests(unittest.TestCase):
    def setUp(self):
        self.client = LegacySectionClient()
        self.project = SimpleNamespace(id="project", tenant_id="workspace", name="retest")
        self.spec = {"title": "Skill invocations", "metric": "run_count", "filter": 'in(trace_id, ["first"])'}

    def test_dashboard_link_opens_one_day_without_changing_saved_charts(self):
        dashboard = analytics.ensure_dashboard(self.client, self.project, "https://example.test")
        url = urlsplit(dashboard["url"])
        self.assertEqual(url.path, f"/o/workspace/dashboards/{dashboard['id']}")
        self.assertEqual(json.loads(parse_qs(url.query)["timeModel"][0]), {"duration": "24h"})
        self.assertEqual(self.client.charts, [])

    def test_cost_and_quality_charts_select_roots_with_rolled_up_cost(self):
        traces = {
            "root-a": [{"id": "root-a", "run_type": "chain", "total_cost": 0.3, "trace_total_cost": 0.3},
                       {"id": "llm-a", "run_type": "llm", "total_cost": 0.1},
                       {"id": "llm-b", "run_type": "llm", "total_cost": 0.2},
                       {"id": "skill", "run_type": "tool", "name": "Skill",
                        "extra": {"metadata": {"ls_skill_name": "workshop:fix-bug"}}}],
            "root-b": [{"id": "root-b", "run_type": "chain", "total_cost": None, "trace_total_cost": None}],
        }
        namespace = {"analytics": analytics, "json": json, "traces": traces}
        with patch.object(analytics, "display_table"):
            namespace["cohorts"] = analytics.cohort_filters(traces)
            exec(compile(notebook_cells()["m06-60"], "m06-60", "exec"), namespace)
        specs = {spec["metric"]: spec for spec in namespace["chart_specs"]}
        costs = analytics.chart_series(self.client, self.project, specs["total_cost"])
        quality = analytics.chart_series(self.client, self.project, specs["feedback_score_avg"])
        self.assertEqual({series["name"]: series["filters"]["filter"] for series in costs}, {
            "workshop:fix-bug": 'and(eq(is_root, true), in(id, ["root-a"]))',
            "no_skill": 'and(eq(is_root, true), in(id, ["root-b"]))'})
        self.assertEqual({series["name"]: series["filters"]["filter"] for series in quality}, {
            "workshop:fix-bug": 'and(eq(is_root, true), in(id, ["root-a"]))',
            "no_skill": 'and(eq(is_root, true), in(id, ["root-b"]))'})
        self.assertTrue(all(series["filters"]["session"] == ["project"] for series in costs + quality))
        self.assertTrue(all(series["feedback_key"] == "output_quality" for series in quality))
        metrics = {row["skill group"]: row for row in analytics.turn_metrics(traces)}
        self.assertEqual(metrics["workshop:fix-bug"]["total cost ($)"], 0.3)
        self.assertIsNone(metrics["no_skill"]["total cost ($)"])

    def test_cost_preview_distinguishes_numeric_cost_zero_and_empty_buckets(self):
        spec = {"title": "Turn cost", "metric": "total_cost", "filter": 'in(trace_id, ["root-a"])'}
        cases = [([], None, 0), ([None, None], None, 0), ([0], Decimal("0"), 1),
                 ([0.1, 0.2, None], Decimal("0.3"), 2),
                 ([float("nan"), float("inf"), True], None, 0)]
        for values, expected, count in cases:
            with self.subTest(values=values), \
                    patch.object(analytics, "api_request", return_value={"data": [{"value": v} for v in values]}), \
                    patch.object(analytics, "display_table"), redirect_stdout(io.StringIO()) as output:
                result = analytics.preview_charts(self.client, self.project, [spec], datetime.now(timezone.utc))[0]
            self.assertEqual(result["cost total ($)"], expected)
            self.assertEqual(result["cost buckets"], count)
            self.assertEqual("no numeric costs" in output.getvalue(), expected is None)

    def test_empty_then_populated_section_reproduces_old_failure_and_corrected_reruns(self):
        dashboard = analytics.ensure_dashboard(self.client, self.project, "https://example.test")
        path = f"/charts/section/{dashboard['id']}"
        self.assertEqual(rules.api_request(self.client, "POST", path, json={"omit_data": True}), {"charts": []})
        with patch.object(analytics, "display_table"):
            first = analytics.ensure_charts(self.client, self.project, dashboard, [self.spec])
        with self.assertRaises(rules.LangSmithRequestError) as caught:
            rules.api_request(self.client, "POST", path, json={"omit_data": True})
        self.assertEqual(caught.exception.category, "chart-time-window")
        before = copy.deepcopy(self.client.charts)

        # A newly constructed client represents reconnecting after a kernel restart.
        reconnected = LegacySectionClient()
        reconnected.sections = self.client.sections
        reconnected.charts = self.client.charts
        reused = analytics.ensure_dashboard(reconnected, self.project, "https://example.test")
        self.assertEqual(reused, dashboard)
        updated = {**self.spec, "filter": 'in(trace_id, ["first", "second"])'}
        with patch.object(analytics, "display_table"):
            for _ in range(2):
                self.assertEqual(analytics.ensure_charts(reconnected, self.project, reused, [updated]), first)
        self.assertEqual(len(reconnected.sections), 1)
        self.assertEqual(len(reconnected.charts), 1)
        self.assertEqual(reconnected.charts[0]["series"][0]["id"], before[0]["series"][0]["id"])
        self.assertEqual(reconnected.charts[0]["series"][0]["filters"]["filter"], updated["filter"])
        reads = [body["json"] for method, path, body in reconnected.calls if path.startswith("/charts/section/")]
        for body in reads:
            start, end = (datetime.fromisoformat(body[key]) for key in ("start_time", "end_time"))
            self.assertEqual(end - start, timedelta(minutes=1))
            self.assertEqual(start.utcoffset(), timedelta(0))
            self.assertEqual(body["stride"], {"minutes": 1})
            self.assertNotIn("bucket_info", body)

    def test_v2_section_remains_rerunnable_and_real_missing_section_stays_error(self):
        dashboard = analytics.ensure_dashboard(self.client, self.project, "https://example.test")
        converted = [{"name": "Skill invocations", "metric_definition": {"type": "run_count"}}]
        with patch.object(analytics, "chart_series", return_value=converted), patch.object(analytics, "display_table"):
            first = analytics.ensure_charts(self.client, self.project, dashboard, [self.spec], "v2")
            self.assertEqual(analytics.ensure_charts(self.client, self.project, dashboard, [self.spec], "v2"), first)
        with self.assertRaises(rules.LangSmithRequestError) as caught:
            analytics.ensure_charts(self.client, self.project, {"id": "missing"}, [self.spec])
        self.assertEqual(caught.exception.category, "not-found")
        self.assertEqual(len(self.client.charts), 1)

    def test_chart_window_diagnostic_does_not_expose_body(self):
        response = requests.Response()
        response.status_code = 404
        response._content = b'{"detail":"start_time must be set.","private":"do-not-print"}'
        client = SimpleNamespace(request_with_retries=lambda *args, **kwargs: response)
        with self.assertRaises(rules.LangSmithRequestError) as caught:
            rules.api_request(client, "POST", "/charts/section/id")
        self.assertEqual(caught.exception.category, "chart-time-window")
        self.assertNotIn("do-not-print", str(caught.exception))
        response.status_code = 422
        response._content = b'{"detail":"end_time must be set.","model":"do-not-print"}'
        with self.assertRaises(rules.LangSmithRequestError) as caught:
            rules.api_request(client, "POST", "/charts/section/id")
        self.assertEqual(caught.exception.category, "chart-time-window")


if __name__ == "__main__":
    unittest.main()
