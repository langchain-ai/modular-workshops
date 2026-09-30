"""Exercise the real notebook cells and reports, with only network I/O replaced."""

import ast
import asyncio
import copy
import io
import json
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from utils import coding_agent_analytics as analytics
from utils import coding_agent_diagnostics as diagnostics
from utils import langsmith_rules as rules
from utils.coding_agent_workshop.tests.test_diagnostics import PROJECT, LLM, ROOT


REPO = Path(__file__).resolve().parents[3]
REQUEST_ID = "12345678-abcd-4321-abcd-123456789012"


def notebook_cells():
    return {cell["id"]: "".join(cell["source"]) for cell in json.loads(
        (REPO / "modules/06_coding_agent_analytics.ipynb").read_text())["cells"]}


class Response:
    status_code = 200
    headers = {"x-request-id": REQUEST_ID, "authorization": "PRIVATE-HEADER"}

    def __init__(self, rows, parse_error=False):
        self.rows, self.parse_error = rows, parse_error

    async def json(self):
        return {"items": copy.deepcopy(self.rows)}

    async def parse(self):
        if self.parse_error:
            raise TypeError("PRIVATE-SDK-ERROR")
        return SimpleNamespace(items=copy.deepcopy(self.rows))


class FailureFixture:
    """No real LangSmith client or credentials; every permitted request is explicit."""

    def __init__(self):
        self.since = datetime(2026, 9, 30, tzinfo=timezone.utc)
        self.project = SimpleNamespace(id=PROJECT, tenant_id=PROJECT)
        self.llm = {"id": LLM, "trace_id": ROOT, "run_type": "llm",
                    "start_time": self.since, "total_cost": None, "total_tokens": 123,
                    "extra": {"metadata": {"ls_model_name": "claude-example", "ls_provider": "anthropic"}},
                    "outputs": {"messages": [{"role": "assistant", "content": [
                        {"type": "text", "text": "PRIVATE-TRACE"},
                        {"type": "tool_call", "name": "Skill", "args": {"skill": "PRIVATE-ARG"}}]}]}}
        self.root = {"id": ROOT, "run_type": "chain", "total_cost": None, "trace_total_cost": None}
        self.traces = {ROOT: [self.root, self.llm]}
        self.calls = []
        self.legacy_matches = False
        self.v2_matches = False
        self.parse_error = False
        self.probe_error = False
        self.query_error = None
        self.primary_matches = False
        self.structural_matches = False
        self.feedback_matches = False
        self.client = SimpleNamespace(
            api_url="https://example.test:8443/api/v1",
            runs=SimpleNamespace(with_raw_response=SimpleNamespace(query=self.modern)),
            traces=SimpleNamespace(with_raw_response=SimpleNamespace(query=self.trace_query)),
        )

    def api(self, client, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if method == "GET" and path == "/info":
            return {"version": "0.16.65"}
        if method == "GET" and path == "/runs/rules":
            return []
        if method == "GET" and path == "/model-price-map/":
            raise rules.LangSmithRequestError(method, path, status=403, category="permissions", request_id=REQUEST_ID)
        if method == "POST" and path == "/runs/query":
            body = kwargs["json"]
            if self.probe_error and body.get("filter") == 'eq(output_value, "Skill")':
                raise rules.LangSmithRequestError(method, path, status=422, category="validation", request_id=REQUEST_ID)
            matched = "output_value" not in body.get("filter", "") or self.legacy_matches
            return {"runs": [self.llm if body["id"] == [LLM] else self.root] if matched else []}
        raise AssertionError("Unexpected network operation")

    async def modern(self, **kwargs):
        self.calls.append(("POST", "/api/v2/runs/query", kwargs))
        matched = "output_value" not in kwargs.get("filter", "") or self.v2_matches
        return Response([self.llm if kwargs["ids"] == [LLM] else self.root] if matched else [], self.parse_error)

    async def trace_query(self, **kwargs):
        self.calls.append(("POST", "/api/v2/traces/query", kwargs))
        return Response([{"root_run": self.root, "trace_aggregates": {"total_cost": None}}], self.parse_error)

    async def primary(self, *args, **kwargs):
        if self.query_error is not None:
            raise self.query_error
        predicate = kwargs.get("filter", "")
        if "feedback_key" in predicate:
            return [self.llm] if self.feedback_matches else []
        if self.structural_matches and "output_key" not in predicate:
            return [self.llm]
        return [self.llm] if self.primary_matches else []

    def patches(self):
        stack = ExitStack()
        stack.enter_context(patch.object(rules, "api_request", side_effect=self.api))
        stack.enter_context(patch.object(analytics, "query_runs", side_effect=self.primary))
        stack.enter_context(patch.object(analytics, "query_turns", new_callable=AsyncMock, return_value=[self.root]))
        return stack

    def namespace(self):
        return dict(analytics=analytics, rules=Mock(), json=json, client=self.client, project=self.project,
                    llm_run=self.llm, since=self.since, call_path="messages.content.name",
                    activity_source="live", web_url="https://example.test", workshop_rules={},
                    skill_filter_validation="stale success", agent_filter="root-filter", traces=self.traces,
                    perform_eval=lambda run: {}, selection_prompt="prompt", selection_schema={}, judge_model={},
                    datetime=datetime, timezone=timezone, timedelta=timedelta)


async def execute_cell(cell_id, namespace):
    code = compile(notebook_cells()[cell_id], cell_id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    result = eval(code, namespace)
    if asyncio.iscoroutine(result):
        await result


class FailureOutputTests(unittest.IsolatedAsyncioTestCase):
    async def run_failure(self, fixture):
        namespace = fixture.namespace()
        with fixture.patches(), redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(ValueError, "Automatic diagnostics"):
                await execute_cell("m06-17", namespace)
        return namespace, output.getvalue()

    async def test_actual_failure_cell_prints_all_probes_and_blocks_both_registrations(self):
        fixture = FailureFixture()
        namespace, output = await self.run_failure(fixture)
        for expected in ("DIAGNOSTICS BEGIN", "DIAGNOSTICS END", "skill-filter-no-match", PROJECT, LLM,
                         "2026-09-30.2", "0.16.65", "example.test:8443/api/v1", "requested_filter",
                         "id only", "LLM type", "shallow output pair", "output key", "output value",
                         "output pair", "full Skill filter", '"legacy"', '"v2"', '"matched": false',
                         "sdk_matched", "costs: trace", "skill_rules", "pricing", '"status": 403', REQUEST_ID):
            self.assertIn(expected, output)
        self.assertNotIn("PRIVATE-", output)
        self.assertIsNone(namespace["skill_filter_validation"])
        for cell in ("m06-25", "m06-38"):
            with self.assertRaisesRegex(ValueError, "Section 2.2"):
                await execute_cell(cell, namespace)
        self.assertFalse(namespace["rules"].mock_calls)
        legacy = [kwargs["json"] for method, path, kwargs in fixture.calls if path == "/runs/query"]
        modern = [kwargs for method, path, kwargs in fixture.calls if path == "/api/v2/runs/query"]
        self.assertEqual({row["start_time"] for row in legacy}, {fixture.since.isoformat()})
        self.assertEqual({row["end_time"] for row in legacy}, {row["max_start_time"].isoformat() for row in modern})
        self.assertTrue(all(row["session"] == [PROJECT] and len(row["id"]) == 1 for row in legacy))
        self.assertTrue(all(method == "GET" or path.endswith("/query") for method, path, _ in fixture.calls))

    async def test_http_failure_prints_original_status_and_request_id(self):
        fixture = FailureFixture()
        fixture.query_error = rules.LangSmithRequestError("POST", "/api/v2/runs/query", status=403,
                                                         category="permissions", request_id=REQUEST_ID)
        _, output = await self.run_failure(fixture)
        self.assertIn("original_error", output)
        self.assertIn("skill-filter-query-error", output)
        self.assertIn(REQUEST_ID, output)
        self.assertIn('"status": 403', output)
        self.assertIn("full Skill filter", output)

    async def test_probe_error_and_sdk_parse_error_keep_other_evidence(self):
        fixture = FailureFixture()
        fixture.probe_error = True
        fixture.parse_error = True
        fixture.legacy_matches = True
        _, output = await self.run_failure(fixture)
        self.assertIn('"status": 422', output)
        self.assertIn('"error_type": "TypeError"', output)
        self.assertIn('"matched": true', output)
        self.assertIn('"matched": false', output)
        self.assertIn('"sdk_error"', output)
        self.assertIn("costs: trace", output)
        self.assertIn("full Skill filter", output)
        self.assertIn('"status": "finished"', output)
        self.assertNotIn("PRIVATE-", output)

    async def test_success_does_not_run_diagnostics(self):
        fixture = FailureFixture()
        fixture.primary_matches = True
        with fixture.patches(), patch.object(analytics, "show_runs"), redirect_stdout(io.StringIO()) as output:
            namespace = fixture.namespace()
            await execute_cell("m06-17", namespace)
        self.assertIsNotNone(namespace["skill_filter_validation"])
        self.assertIn("Skill filter matched", output.getvalue())
        self.assertNotIn("DIAGNOSTICS", output.getvalue())
        self.assertFalse(fixture.calls)

    async def test_missing_cost_cell_runs_diagnostics_independently_of_skill_validation(self):
        fixture = FailureFixture()
        namespace = fixture.namespace()
        namespace["skill_filter_validation"] = None
        with fixture.patches(), patch.object(analytics, "ranked_bars"), patch.object(analytics, "display_table"), \
                redirect_stdout(io.StringIO()) as output:
            await execute_cell("m06-57", namespace)
        self.assertIn("missing-turn-costs", output.getvalue())
        self.assertIn("costs: helper root", output.getvalue())
        self.assertIn("pricing", output.getvalue())
        self.assertIn("DIAGNOSTICS END", output.getvalue())

    async def test_known_zero_cost_does_not_trigger_diagnostics(self):
        fixture = FailureFixture()
        fixture.root["trace_total_cost"] = 0
        with fixture.patches(), redirect_stdout(io.StringIO()) as output:
            await analytics.diagnose_missing_costs(fixture.client, fixture.project, fixture.traces, since=fixture.since)
        self.assertFalse(fixture.calls)
        self.assertEqual(output.getvalue(), "")

    async def test_mixed_cost_sample_inspects_unpriced_llm_not_first_priced_turn(self):
        fixture = FailureFixture()
        paid = {"id": "paid-root", "trace_total_cost": 0.5}
        paid_llm = {**fixture.llm, "id": "paid-llm", "total_cost": 0.5}
        no_usage = {**fixture.llm, "id": "no-usage", "total_tokens": None}
        traces = {"paid-root": [paid, paid_llm], ROOT: [fixture.root, no_usage, fixture.llm]}
        with patch.object(diagnostics, "print_diagnostics", new_callable=AsyncMock) as report, \
                redirect_stdout(io.StringIO()) as output:
            await analytics.diagnose_missing_costs(fixture.client, fixture.project, traces, since=fixture.since)
        self.assertEqual(report.call_args.kwargs["llm_run"]["id"], LLM)
        self.assertIn("1 of 2 sampled turns lack cost", output.getvalue())

    async def test_unpriced_turn_without_llms_reports_absence_without_wrong_sample(self):
        fixture = FailureFixture()
        with patch.object(diagnostics, "print_diagnostics", new_callable=AsyncMock) as report, \
                redirect_stdout(io.StringIO()) as output:
            await analytics.diagnose_missing_costs(fixture.client, fixture.project,
                                                  {ROOT: [fixture.root]}, since=fixture.since)
        report.assert_not_called()
        self.assertIn("No LLM spans", output.getvalue())

    async def test_early_cost_check_loads_only_bounded_unpriced_trees(self):
        fixture = FailureFixture()
        roots = [{"id": "priced", "trace_total_cost": 0},
                 *[{"id": f"missing-{index}", "trace_total_cost": None} for index in range(3)]]
        with patch.object(analytics, "read_trace", new_callable=AsyncMock,
                          side_effect=lambda client, project, root: [root, fixture.llm]) as read, \
                patch.object(analytics, "diagnose_missing_costs", new_callable=AsyncMock) as diagnose, \
                redirect_stdout(io.StringIO()):
            await analytics.diagnose_recent_costs(fixture.client, fixture.project, roots, since=fixture.since)
        self.assertEqual([call.args[2]["id"] for call in read.call_args_list], ["missing-0", "missing-1"])
        self.assertEqual(set(diagnose.call_args.args[2]), {"missing-0", "missing-1"})

    async def test_partial_output_survives_deadline_and_preserves_original_failure(self):
        fixture = FailureFixture()

        async def slow(*args, emit, **kwargs):
            emit("scope", {"llm_run_id": LLM})
            emit("completed_probe", {"matched": False})
            await asyncio.sleep(60)

        with patch.object(diagnostics, "collect_diagnostics", side_effect=slow), \
                patch.object(diagnostics, "REPORT_TIMEOUT_SECONDS", 0.02):
            namespace, output = await self.run_failure(fixture)
        self.assertIn("completed_probe", output)
        self.assertIn('"status": "incomplete"', output)
        self.assertIn("TimeoutError", output)
        self.assertIn("DIAGNOSTICS END", output)
        self.assertIsNone(namespace["skill_filter_validation"])

    async def test_unexpected_diagnostic_failure_prints_safe_location_and_original_guard(self):
        fixture = FailureFixture()
        with patch.object(diagnostics, "collect_diagnostics", side_effect=KeyError("PRIVATE-ERROR")):
            namespace, output = await self.run_failure(fixture)
        self.assertIn('"error_type": "KeyError"', output)
        self.assertIn('"location"', output)
        self.assertIn('"status": "incomplete"', output)
        self.assertNotIn("PRIVATE-", output)
        self.assertIsNone(namespace["skill_filter_validation"])

    async def test_setup_detects_old_imported_helpers(self):
        with patch.object(analytics, "FAILURE_DIAGNOSTICS_VERSION", "old"), \
                patch("dotenv.load_dotenv") as load:
            with self.assertRaisesRegex(RuntimeError, "restart the kernel"):
                await execute_cell("m06-03", {})
        load.assert_not_called()

    async def test_unexpected_response_shape_is_not_reported_as_no_match(self):
        fixture = FailureFixture()

        async def wrong_shape(**kwargs):
            response = Response([])
            response.json = AsyncMock(return_value={"unexpected": "PRIVATE-RESPONSE"})
            return response

        fixture.client.runs.with_raw_response.query = wrong_shape
        _, output = await self.run_failure(fixture)
        self.assertIn('"category": "response-shape"', output)
        self.assertIn("items: list of at most 10 objects", output)
        self.assertIn("full Skill filter", output)
        self.assertIn("costs: trace", output)
        self.assertIn('"status": "finished"', output)
        self.assertNotIn("PRIVATE-", output)

    async def test_minimal_metadata_failure_does_not_stop_filter_probes(self):
        fixture = FailureFixture()
        original_api = fixture.api
        fixture.api = lambda client, method, path, **kwargs: (None if path == "/info" else
                                                             original_api(client, method, path, **kwargs))
        _, output = await self.run_failure(fixture)
        self.assertIn('"expected": "info object"', output)
        self.assertIn("full Skill filter", output)
        self.assertIn('"status": "finished"', output)

    async def test_synchronous_transport_does_not_block_report_deadline(self):
        import time

        with patch.object(diagnostics, "PROBE_TIMEOUT_SECONDS", 0.01):
            result = await diagnostics._capture(lambda: time.sleep(0.15), "/runs/query")
        self.assertEqual(result["category"], "timeout")

    async def test_cost_detail_select_failure_does_not_change_filter_probe_fields(self):
        fixture = FailureFixture()
        original = fixture.modern

        async def modern(**kwargs):
            if "PRICE_MODEL_ID" in kwargs["selects"]:
                raise rules.LangSmithRequestError("POST", "/api/v2/runs/query", status=422, category="validation")
            self.assertEqual(kwargs["selects"], analytics.RUN_FIELDS)
            return await original(**kwargs)

        fixture.client.runs.with_raw_response.query = modern
        _, output = await self.run_failure(fixture)
        self.assertIn("full Skill filter", output)
        self.assertIn("cost_detail_query", output)
        self.assertIn('"status": 422', output)
        self.assertIn("costs: legacy LLM", output)

    async def test_missing_id_and_unsupported_v2_still_probe_the_observed_call(self):
        fixture = FailureFixture()
        original_api = fixture.api
        fixture.api = lambda client, method, path, **kwargs: ({"runs": []} if path == "/runs/query" else
                                                             original_api(client, method, path, **kwargs))

        async def unavailable(**kwargs):
            raise rules.LangSmithRequestError("POST", "/api/v2/runs/query", status=404, category="not-found")

        fixture.client.runs.with_raw_response.query = unavailable
        _, output = await self.run_failure(fixture)
        self.assertIn("ID-only queries did not resolve it", output)
        self.assertIn('"status": 404', output)
        self.assertIn("full Skill filter", output)
        self.assertIn("costs: trace", output)
        self.assertIn('"status": "finished"', output)



if __name__ == "__main__":
    unittest.main()
