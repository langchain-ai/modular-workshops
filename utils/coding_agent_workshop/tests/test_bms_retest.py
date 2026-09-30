"""Regressions from the September 29 export and the 0.16.65 read contract."""

import ast
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import requests

from utils import coding_agent_analytics as analytics
from utils import langsmith_rules as rules
from utils.coding_agent_workshop.tests.test_module06 import FakeClient, ROOT, llm_output, skill_call


def notebook_cells():
    notebook = json.loads((ROOT / "modules/06_coding_agent_analytics.ipynb").read_text())
    return {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}


class SkillRegistrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = object()
        self.project = SimpleNamespace(id="project")
        self.llm = {"id": "llm", "run_type": "llm", **llm_output([skill_call("workshop:fix-bug")])}
        self.since = datetime(2026, 9, 29, tzinfo=timezone.utc)

    async def verify(self, predicate="filter"):
        with patch.object(analytics, "query_runs", new_callable=AsyncMock, return_value=[self.llm]), \
                redirect_stdout(io.StringIO()):
            return await analytics.verify_skill_filter(self.client, self.project, self.llm, predicate, since=self.since)

    async def test_validation_rejects_every_changed_scope(self):
        verified = await self.verify()
        args = [self.client, self.project, self.llm, "filter"]
        analytics.require_skill_filter_validation(verified, *args, since=self.since)
        replacements = [object(), SimpleNamespace(id="other"), {**self.llm, "id": "other"}, "other-filter"]
        for index, replacement in enumerate(replacements):
            changed = args.copy()
            changed[index] = replacement
            with self.subTest(scope=index), self.assertRaisesRegex(ValueError, "Section 2.2"):
                analytics.require_skill_filter_validation(verified, *changed, since=self.since)
        with self.assertRaises(ValueError):
            analytics.require_skill_filter_validation(verified, *args, since=self.since + timedelta(seconds=1))

    async def test_failed_notebook_rerun_invalidates_success_and_blocks_both_writes(self):
        cells = notebook_cells()
        api = Mock()
        namespace = dict(analytics=analytics, rules=api, json=json, client=self.client, project=self.project,
                         llm_run=self.llm, since=self.since, call_path="messages.content.name",
                         activity_source="live", web_url="https://example.test", workshop_rules={},
                         perform_eval=lambda run: {}, selection_prompt="prompt", selection_schema={},
                         judge_model={}, agent_filter="root-filter")
        namespace["skill_filter_validation"] = await self.verify()
        code = compile(cells["m06-17"], "m06-17", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        with patch.object(analytics, "query_runs", new_callable=AsyncMock, return_value=[]):
            with self.assertRaisesRegex(ValueError, "indexing"):
                await eval(code, namespace)
        self.assertIsNone(namespace["skill_filter_validation"])
        for cell_id in ("m06-25", "m06-38"):
            with self.subTest(cell=cell_id), self.assertRaisesRegex(ValueError, "Section 2.2"):
                exec(compile(cells[cell_id], cell_id, "exec"), namespace)
        self.assertFalse(api.mock_calls)

        with patch.object(analytics, "query_runs", new_callable=AsyncMock, return_value=[self.llm]), \
                patch.object(analytics, "query_turns", new_callable=AsyncMock, return_value=[]), \
                patch.object(analytics, "show_runs"), redirect_stdout(io.StringIO()):
            await eval(code, namespace)
            api.ensure_code_evaluator.return_value = {"name": "skill", "id": "code", "url": "url"}
            api.ensure_llm_evaluator.return_value = {"name": "selection", "id": "judge", "url": "url"}
            for cell_id in ("m06-25", "m06-38"):
                exec(compile(cells[cell_id], cell_id, "exec"), namespace)
        api.ensure_code_evaluator.assert_called_once()
        api.ensure_llm_evaluator.assert_called_once()

    async def test_wrong_result_id_or_non_skill_payload_cannot_validate(self):
        with patch.object(analytics, "query_runs", new_callable=AsyncMock, return_value=[{"id": "other"}]):
            with self.assertRaises(ValueError):
                await analytics.verify_skill_filter(self.client, self.project, self.llm, "filter", since=self.since)
        negative = {"id": "llm", "run_type": "llm", **llm_output([])}
        with patch.object(analytics, "query_runs", new_callable=AsyncMock, return_value=[negative]):
            with self.assertRaisesRegex(ValueError, "contains a Skill"):
                await analytics.verify_skill_filter(self.client, self.project, negative, "filter", since=self.since)


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


class FeedbackCoverageTests(unittest.TestCase):
    def test_latest_zero_selection_score_counts_and_missing_feedback_is_visible(self):
        runs = [{"id": name, "run_type": "llm", **llm_output([skill_call("workshop:fix-bug")])}
                for name in ("scored", "unscored")]
        runs.append({"id": "no-skill", "run_type": "llm", **llm_output([])})
        feedback = [{"run_id": "scored", "key": "skill_name", "value": ["workshop:fix-bug"], "created_at": "1"},
                    {"run_id": "scored", "key": "skill_selection", "score": 1, "created_at": "1"},
                    {"run_id": "scored", "key": "skill_selection", "score": 0, "created_at": "2"}]
        with patch.object(analytics, "display_table"), redirect_stdout(io.StringIO()) as output:
            rows = analytics.show_skill_feedback(runs, feedback)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["skill_selection"], 0)
        self.assertEqual(rows[0]["feedback"], "complete")
        self.assertIsNone(rows[1]["skill_selection"])
        self.assertIn("skill_selection", rows[1]["feedback"])
        self.assertIn("eligibility", output.getvalue())


if __name__ == "__main__":
    unittest.main()
