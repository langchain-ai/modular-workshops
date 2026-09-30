"""Exercise the fallback without assuming BMS output or feedback indexes work."""

import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

from utils import coding_agent_analytics as analytics
from utils import coding_agent_diagnostics as diagnostics
from utils import langsmith_rules as rules
from utils.coding_agent_workshop.tests.test_failure_output import FailureFixture, execute_cell
from utils.coding_agent_workshop.tests.test_module06 import load_evaluator


class FeedbackFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = FailureFixture()
        self.label_filter = 'and(eq(run_type, "llm"), root-filter)'

    async def resolve(self, responses):
        fixture = self.fixture
        with patch.object(analytics, "query_runs", new_callable=AsyncMock, side_effect=responses), \
                patch.object(diagnostics, "print_diagnostics", new_callable=AsyncMock), \
                redirect_stdout(io.StringIO()):
            return await analytics.resolve_skill_filters(
                fixture.client, fixture.project, fixture.llm, "output-filter",
                since=fixture.since, agent_filter="root-filter")

    async def test_no_match_fallback_only_validates_labeler_until_real_feedback_exists(self):
        result = await self.resolve([[], [self.fixture.llm]])
        self.assertEqual(result["mode"], "feedback")
        self.assertEqual(result["label_filter"], self.label_filter)
        self.assertIn('like(feedback_value, "%")', result["selection_filter"])
        self.assertNotIn("output_value", result["selection_filter"])
        self.assertIsNone(result["selection_validation"])
        analytics.require_skill_filter_validation(
            result["label_validation"], self.fixture.client, self.fixture.project,
            self.fixture.llm, self.label_filter, since=self.fixture.since)

    async def test_request_errors_do_not_activate_fallback(self):
        fixture = self.fixture
        error = rules.LangSmithRequestError("POST", "/runs/query", status=403, category="permissions")
        with patch.object(analytics, "query_runs", new_callable=AsyncMock, side_effect=error) as query, \
                patch.object(diagnostics, "print_diagnostics", new_callable=AsyncMock):
            with self.assertRaisesRegex(ValueError, "query failed"):
                await analytics.resolve_skill_filters(fixture.client, fixture.project, fixture.llm,
                    "output-filter", since=fixture.since, agent_filter="root-filter")
        self.assertEqual(query.await_count, 1)

    async def test_success_keeps_original_output_selector(self):
        result = await self.resolve([[self.fixture.llm]])
        self.assertEqual(result["mode"], "outputs")
        self.assertEqual(result["selection_filter"], "output-filter")
        self.assertEqual(result["selection_validation"], result["label_validation"])

    async def test_wait_verifies_actual_run_and_labels(self):
        fixture = self.fixture
        feedback = [{"run_id": fixture.llm["id"], "key": "skill_name", "value": "PRIVATE-ARG"}]
        with patch.object(analytics, "query_runs", new_callable=AsyncMock,
                          side_effect=[[], [fixture.llm]]) as query, \
                patch.object(analytics, "read_feedback", return_value=feedback), \
                redirect_stdout(io.StringIO()) as output:
            run = await analytics.wait_for_skill_label(fixture.client, fixture.project, "feedback-filter",
                                                       since=fixture.since, poll_interval=0)
        self.assertEqual(run["id"], fixture.llm["id"])
        self.assertEqual(query.call_args.kwargs["filter"], "feedback-filter")
        self.assertEqual(query.call_args.kwargs["since"], fixture.since)
        self.assertNotIn("PRIVATE-", output.getvalue())

    async def test_error_or_wrong_run_feedback_does_not_validate(self):
        fixture = self.fixture
        cases = [None, "different-skill", "PRIVATE-ARG"]
        for value in cases:
            with self.subTest(value=value), \
                    patch.object(analytics, "query_runs", new_callable=AsyncMock, return_value=[fixture.llm]), \
                    patch.object(analytics, "read_feedback", return_value=[{
                        "run_id": fixture.llm["id"] if value != "PRIVATE-ARG" else "other-run",
                        "key": "skill_name", "value": value,
                    }]), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "before timeout"):
                    await analytics.wait_for_skill_label(fixture.client, fixture.project, "feedback-filter",
                                                         since=fixture.since, timeout=0.02, poll_interval=0.005)

    async def test_non_skill_result_cannot_enable_judge(self):
        fixture = self.fixture
        with patch.object(analytics, "query_runs", new_callable=AsyncMock,
                          return_value=[{**fixture.llm, "outputs": {}}]), \
                redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(ValueError, "verification failed"):
                await analytics.wait_for_skill_label(fixture.client, fixture.project, "feedback-filter",
                                                     since=fixture.since)
        self.assertNotIn("PRIVATE-", output.getvalue())

    async def test_actual_cells_register_labeler_then_wait_before_hosted_judge(self):
        fixture = self.fixture
        namespace = fixture.namespace()
        namespace.update(datetime=datetime, timedelta=timedelta, timezone=timezone)
        namespace["rules"].ensure_code_evaluator.return_value = {
            "id": "code-rule", "name": "module06-skill-name", "url": "url"}
        namespace["rules"].ensure_llm_evaluator.return_value = {
            "id": "judge-rule", "name": "module06-skill-selection", "url": "url"}
        with patch.object(analytics, "query_runs", new_callable=AsyncMock,
                          side_effect=[[], [fixture.llm]]), \
                patch.object(diagnostics, "print_diagnostics", new_callable=AsyncMock), \
                patch.object(analytics, "query_turns", new_callable=AsyncMock, return_value=[]), \
                patch.object(analytics, "show_runs"), redirect_stdout(io.StringIO()):
            await execute_cell("m06-17", namespace)
            await execute_cell("m06-25", namespace)
        api = namespace["rules"]
        self.assertEqual(api.ensure_code_evaluator.call_args.kwargs["filter"], self.label_filter)
        self.assertIsNone(namespace["skill_filter_validation"])
        api.ensure_llm_evaluator.assert_not_called()
        with patch.object(analytics, "wait_for_skill_label", new_callable=AsyncMock,
                          side_effect=ValueError("pending")):
            with self.assertRaisesRegex(ValueError, "pending"):
                await execute_cell("m06-38", namespace)
        api.ensure_llm_evaluator.assert_not_called()
        with patch.object(analytics, "wait_for_skill_label", new_callable=AsyncMock, return_value=fixture.llm), \
                patch.object(analytics, "query_runs", new_callable=AsyncMock, return_value=[fixture.llm]), \
                redirect_stdout(io.StringIO()):
            await execute_cell("m06-38", namespace)
        self.assertEqual(api.ensure_llm_evaluator.call_args.kwargs["filter"], namespace["skill_filter"])
        self.assertNotEqual(namespace["skill_filter"], self.label_filter)

    def test_non_skill_labeler_output_remains_truthy_and_has_no_labels(self):
        evaluator = load_evaluator()
        self.assertEqual(evaluator({"outputs": {"messages": []}}), {"skill_name": []})


if __name__ == "__main__":
    unittest.main()
