"""Integrity and recovery checks for the sanitized recorded session."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from utils import coding_agent_analytics as analytics
from utils import coding_agent_replay as replay


class ReplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = SimpleNamespace(api_url="https://example.test/api")
        self.project = SimpleNamespace(id="project-a", tenant_id="workspace-a")
        self.attempt = replay.prepare_replay(self.client, self.project, self.temp.name)

    def test_recording_has_expected_tools_cost_and_no_private_metadata(self):
        fixture = replay.load_fixture()
        runs = fixture["runs"]
        self.assertEqual(len(runs), 78)
        self.assertEqual(sum(not run["parent_run_id"] for run in runs), 5)
        self.assertEqual(sum(analytics.skill_counts(runs).values()), 5)
        self.assertEqual(analytics.mcp_counts(runs), {
            "mcp__plugin_workshop_issues__get_issue": 5,
            "mcp__plugin_workshop_issues__get_acceptance_criteria": 5,
        })
        self.assertAlmostEqual(sum(float(run.get("total_cost") or 0) for run in runs), 2.17243025)
        text = json.dumps(fixture)
        for forbidden in ("/Users/", "/var/folders/", "LANGSMITH_", "local_username", "anthropic_user_id",
                          "feedback_stats", "api_key", "authorization"):
            self.assertNotIn(forbidden, text)

    def test_remapping_preserves_tree_durations_and_one_thread(self):
        records = replay.replay_records(self.attempt, "smoke") + replay.replay_records(self.attempt, "usage")
        fixture = replay.load_fixture()["runs"]
        self.assertTrue(set(run["id"] for run in records).isdisjoint(run["id"] for run in fixture))
        by_id = {run["id"]: run for run in records}
        for old, new in zip(fixture, records):
            self.assertEqual(replay.timestamp(old["end_time"]) - replay.timestamp(old["start_time"]),
                             replay.timestamp(new["end_time"]) - replay.timestamp(new["start_time"]))
            if new["parent_run_id"]:
                self.assertTrue(new["dotted_order"].startswith(by_id[new["parent_run_id"]]["dotted_order"] + "."))
                self.assertEqual(new["trace_id"], by_id[new["parent_run_id"]]["trace_id"])
            self.assertLess(replay.timestamp(new["end_time"]), datetime.now(timezone.utc))
        self.assertEqual(len({analytics.thread_id(run) for run in records}), 1)

    def test_restart_reuses_ids_but_other_projects_get_new_ids(self):
        resumed = replay.prepare_replay(self.client, self.project, self.temp.name)
        other = replay.prepare_replay(self.client, SimpleNamespace(id="project-b", tenant_id="workspace-a"), self.temp.name)
        self.assertEqual(replay.replay_records(self.attempt, "smoke"), replay.replay_records(resumed, "smoke"))
        self.assertNotEqual(self.attempt["state"]["attempt_id"], other["state"]["attempt_id"])

    async def test_successful_stage_is_not_uploaded_twice_and_roots_complete_last(self):
        calls = []
        with patch.object(replay, "query_runs", new_callable=AsyncMock, return_value=[]), \
                patch.object(replay, "api_request", side_effect=lambda *args, **kwargs: calls.append((args[1:3], kwargs))):
            await replay.upload_stage(self.client, self.project, self.attempt, "smoke")
            count = len(calls)
            await replay.upload_stage(self.client, self.project, self.attempt, "smoke")
        self.assertEqual(len(calls), count)
        self.assertEqual(calls[0][0], ("POST", "/runs"))
        self.assertNotIn("end_time", calls[0][1]["json"])
        self.assertEqual(calls[-1][0][0], "PATCH")
        self.assertIn("end_time", calls[-1][1]["json"])

    async def test_partial_failure_resumes_with_original_ids(self):
        written = {}
        fail = True

        def request(client, method, path, *, json):
            nonlocal fail
            if len(written) == 4 and fail:
                fail = False
                raise RuntimeError("test-only interruption")
            if method == "POST":
                self.assertNotIn(json["id"], written)
                written[json["id"]] = dict(json)
            else:
                written[path.rsplit("/", 1)[-1]].update(json)

        async def query(*args, **kwargs):
            return list(written.values())

        with patch.object(replay, "query_runs", side_effect=query), patch.object(replay, "api_request", side_effect=request):
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                await replay.upload_stage(self.client, self.project, self.attempt, "smoke")
            resumed = replay.prepare_replay(self.client, self.project, self.temp.name)
            await replay.upload_stage(self.client, self.project, resumed, "smoke")
        self.assertEqual(len(written), 14)
        self.assertTrue(all(run.get("end_time") for run in written.values()))

    async def test_target_and_stage_checks_precede_writes(self):
        with patch.object(replay, "api_request") as request:
            with self.assertRaisesRegex(ValueError, "target changed"):
                await replay.upload_stage(self.client, SimpleNamespace(id="other", tenant_id="workspace-a"), self.attempt, "smoke")
            with self.assertRaisesRegex(ValueError, "smoke stage"):
                await replay.upload_stage(self.client, self.project, self.attempt, "usage")
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
