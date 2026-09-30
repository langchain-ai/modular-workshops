"""Run the retained notebook flow without output indexing or Skill feedback."""

import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from utils import coding_agent_analytics as analytics
from utils import langsmith_rules as rules
from utils.coding_agent_workshop.tests.test_failure_output import FailureFixture, execute_cell
from utils.coding_agent_workshop.tests.test_module06 import FakeClient


RULE_NAMES = {"module06-output-quality", "module06-task-completion", "module06-session-outcome"}
PROMPT_CELLS = ("m06-29", "m06-30", "m06-33", "m06-41")
REGISTRATION_CELLS = ("m06-31", "m06-34", "m06-42")


def workshop_namespace():
    return dict(analytics=analytics, rules=rules, client=FakeClient(), json=json,
                project=SimpleNamespace(id="project", tenant_id="workspace", name="workshop"),
                activity_source="live", workshop_rules={}, web_url="https://example.test",
                root_filter='and(eq(is_root, true), eq(name, "Claude Code Turn"))',
                judge_model={"model": {"lc": 1, "type": "constructor", "id": ["offline-model"], "kwargs": {}}})


class WorkshopFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_skill_queries_use_execution_spans_and_never_require_output_or_feedback_indexes(self):
        fixture = FailureFixture()
        execution = {"id": "skill-tool", "name": "Skill", "run_type": "tool",
                     "inputs": {"skill": "workshop:fix-bug"}}
        namespace = fixture.namespace()
        with patch.object(analytics, "query_runs", new_callable=AsyncMock, return_value=[execution]) as spans, \
                patch.object(analytics, "query_turns", new_callable=AsyncMock, return_value=[fixture.root]) as turns, \
                patch.object(analytics, "verify_skill_filter", side_effect=AssertionError("No index probe")), \
                patch.object(analytics, "read_feedback", side_effect=AssertionError("No Skill feedback read")), \
                patch.object(analytics, "display_table"), patch.object(analytics, "show_runs"), \
                redirect_stdout(io.StringIO()):
            for mode in ("live", "replay", "prepared"):
                namespace["activity_source"] = mode
                await execute_cell("m06-skill-executions", namespace)
                await execute_cell("m06-17", namespace)
                self.assertEqual(namespace["skill_runs"], [execution])
                self.assertEqual(namespace["skill_turns"], [fixture.root])
        predicate = 'and(eq(run_type, "tool"), eq(name, "Skill"))'
        self.assertEqual(spans.await_count, 3)
        for call in spans.call_args_list:
            self.assertEqual(call.args, (fixture.client, fixture.project))
            self.assertEqual(call.kwargs, {"since": fixture.since, "filter": predicate})
        for call in turns.call_args_list:
            self.assertEqual(call.args, (fixture.client, fixture.project))
            self.assertEqual(call.kwargs, {"since": fixture.since, "filter": "root-filter",
                                          "tree_filter": predicate, "limit": 10})

    async def test_three_hosted_rules_rerun_and_cleanup_preserve_other_rules(self):
        namespace = workshop_namespace()
        client = namespace["client"]
        client.rules = [{"id": "old-skill-rule", "display_name": "module06-skill-name",
                         "session_id": "project", "is_enabled": True}]
        with redirect_stdout(io.StringIO()):
            for cell in PROMPT_CELLS + REGISTRATION_CELLS:
                await execute_cell(cell, namespace)
            first_ids = {name: rule["id"] for name, rule in namespace["workshop_rules"].items()}
            for cell in REGISTRATION_CELLS:
                await execute_cell(cell, namespace)
            self.assertEqual(first_ids, {name: rule["id"] for name, rule in namespace["workshop_rules"].items()})
            self.assertEqual(set(first_ids), RULE_NAMES)
            retained = [r for r in client.rules if r["id"] != "old-skill-rule"]
            self.assertEqual(len(retained), 3)
            for rule in retained:
                self.assertEqual(rule["filter"], namespace["root_filter"])
                self.assertEqual(rule["session_id"], "project")
                structured = rule["evaluators"][0]["structured"]
                self.assertEqual(structured["schema"]["title"], rule["display_name"].removeprefix("module06-").replace("-", "_"))
                self.assertEqual(rule.get("group_by") == "thread_id", rule["display_name"] == "module06-session-outcome")
                self.assertNotIn("code_evaluators", rule)
            await execute_cell("m06-73", namespace)
        self.assertTrue(client.rules[0]["is_enabled"])
        self.assertTrue(all(not rule["is_enabled"] for rule in retained))
        self.assertEqual(namespace["paused"], 3)

    async def test_partial_registration_can_pause_its_exact_ids(self):
        namespace = workshop_namespace()
        with redirect_stdout(io.StringIO()):
            for cell in PROMPT_CELLS + ("m06-31",):
                await execute_cell(cell, namespace)
            with patch.object(rules, "ensure_llm_evaluator", side_effect=ValueError("provider unavailable")):
                with self.assertRaisesRegex(ValueError, "provider unavailable"):
                    await execute_cell("m06-34", namespace)
            await execute_cell("m06-73", namespace)
        self.assertEqual(namespace["paused"], 1)
        self.assertEqual(set(namespace["workshop_rules"]), {"module06-output-quality"})
        self.assertFalse(namespace["client"].rules[0]["is_enabled"])

    async def test_replay_uploads_after_three_retained_rules(self):
        namespace = workshop_namespace()
        namespace.update(activity_source="replay", replay=SimpleNamespace(upload_stage=AsyncMock(return_value=["usage"])),
                         replay_attempt=object())
        with redirect_stdout(io.StringIO()):
            for cell in PROMPT_CELLS + REGISTRATION_CELLS + ("m06-replay-usage",):
                await execute_cell(cell, namespace)
        namespace["replay"].upload_stage.assert_awaited_once_with(
            namespace["client"], namespace["project"], namespace["replay_attempt"], "usage")
        self.assertEqual(namespace["usage_records"], ["usage"])

    async def test_replay_rejects_missing_required_rule_even_with_three_other_entries(self):
        for missing in RULE_NAMES:
            namespace = workshop_namespace()
            namespace.update(activity_source="replay", replay=Mock(upload_stage=AsyncMock()), replay_attempt=object(),
                             workshop_rules={name: {"id": name} for name in (RULE_NAMES - {missing}) | {"unrelated"}})
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, missing):
                await execute_cell("m06-replay-usage", namespace)
            namespace["replay"].upload_stage.assert_not_awaited()

    async def test_analysis_and_all_chart_specs_work_without_skill_feedback(self):
        namespace = workshop_namespace()
        root = {"id": "root", "run_type": "chain", "trace_total_cost": 0.5}
        skill = {"id": "skill", "run_type": "tool", "name": "Skill", "inputs": {"skill": "workshop:fix-bug"}}
        namespace.update(traces={"root": [root, skill]}, all_runs=[root, skill], roots=[root], since="unused")
        with patch.object(analytics, "read_feedback", return_value=[{"run_id": "root", "key": "output_quality", "score": 1}]) as feedback, \
                patch.object(analytics, "display_table"), patch.object(analytics, "ranked_bars"), \
                redirect_stdout(io.StringIO()):
            for cell in ("m06-52", "m06-56", "m06-57", "m06-58", "m06-60"):
                await execute_cell(cell, namespace)
        self.assertEqual(namespace["invocations"], {"workshop:fix-bug": 1})
        self.assertEqual(namespace["metrics"][0]["mean quality"], 1)
        self.assertEqual(namespace["metrics"][0]["total cost ($)"], 0.5)
        self.assertEqual([s["metric"] for s in namespace["chart_specs"]], ["run_count", "total_cost", "feedback_score_avg"])
        feedback.assert_called_once_with(namespace["client"], [root], ["output_quality"])


if __name__ == "__main__":
    unittest.main()
