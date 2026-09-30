"""Deployment regressions identified in the BMS dry run."""

import io
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import requests
from langsmith.utils import LangSmithError

from utils import coding_agent_analytics as analytics
from utils import langsmith_rules as rules


class BMSConfigurationTests(unittest.TestCase):
    def test_self_hosted_urls_and_api_prefix_are_valid(self):
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-only-key"}, clear=True), redirect_stdout(io.StringIO()):
            analytics.check_settings("https://langsmith-dev.webdev.bms.com/api", "https://langsmith-dev.webdev.bms.com/")
            for api, web in (("example.test", "https://example.test"),
                             ("https://example.test/api", "https://smith.langchain.com"),
                             ("https://user:password@example.test", "https://example.test"),
                             ("https://example.test?key=secret", "https://example.test")):
                with self.subTest(api=api), self.assertRaises(ValueError):
                    analytics.check_settings(api, web)
        self.assertFalse(analytics.is_cloud_url("https://smith.langchain.com.example.test"))

    def test_azure_uses_existing_settings_and_hosted_secret_reference(self):
        env = {"AZURE_OPENAI_ENDPOINT": "https://apim.example.test/azure/",
               "AZURE_OPENAI_API_VERSION": "2024-10-21",
               "AZURE_OPENAI_DEPLOYMENT_NAME": "workshop-deployment"}
        with patch.dict(os.environ, env, clear=True):
            config = rules.judge_model_config(provider="azure")
            kwargs = config["model"]["kwargs"]
            self.assertEqual(kwargs["deployment_name"], "workshop-deployment")
            self.assertEqual(kwargs["openai_api_version"], env["AZURE_OPENAI_API_VERSION"])
            self.assertEqual(kwargs["azure_endpoint"], env["AZURE_OPENAI_ENDPOINT"].rstrip("/"))
            self.assertEqual(kwargs["openai_api_key"]["id"], ["AZURE_OPENAI_API_KEY"])
            self.assertNotIn("model", kwargs)  # Deployment aliases are not model identities.
            self.assertNotIn("temperature", kwargs)
            self.assertEqual(rules.judge_model_config(provider="azure", model_name="gpt-5.4")["model"]["kwargs"]["model"], "gpt-5.4")
        for missing in env:
            with self.subTest(missing=missing), patch.dict(os.environ, {k: v for k, v in env.items() if k != missing}, clear=True):
                with self.assertRaisesRegex(ValueError, missing):
                    rules.judge_model_config(provider="azure")

    def test_explicit_openai_does_not_inherit_local_gateway(self):
        with patch.dict(os.environ, {"LANGSMITH_API_KEY_GATEWAY": "test-only-gateway"}, clear=True):
            kwargs = rules.judge_model_config(provider="openai")["model"]["kwargs"]
            self.assertEqual(kwargs["api_key"]["id"], ["OPENAI_API_KEY"])
            self.assertNotIn("base_url", kwargs)
            self.assertIn("base_url", rules.judge_model_config()["model"]["kwargs"])

    def test_azure_constructor_round_trip_uses_deployment_and_secret(self):
        from langchain_core.load import load
        from langchain_openai import AzureChatOpenAI

        env = {"AZURE_OPENAI_ENDPOINT": "https://apim.example.test/azure",
               "AZURE_OPENAI_API_VERSION": "2024-10-21",
               "AZURE_OPENAI_DEPLOYMENT_NAME": "workshop-deployment"}
        with patch.dict(os.environ, env, clear=True):
            config = rules.judge_model_config(provider="azure")
            model = load(config["model"], allowed_objects=[AzureChatOpenAI],
                         secrets_map={"AZURE_OPENAI_API_KEY": "test-only-fake-key"}, secrets_from_env=False)
        self.assertEqual(model.deployment_name, "workshop-deployment")
        self.assertEqual(str(model.root_client.base_url),
                         "https://apim.example.test/azure/openai/deployments/workshop-deployment/")
        self.assertEqual(model.openai_api_version, env["AZURE_OPENAI_API_VERSION"])
        self.assertNotIn("test-only-fake-key", repr(model))

    def test_error_chain_retains_status_without_disclosing_body(self):
        cases = {400: "validation", 401: "authentication", 403: "permissions", 404: "not-found",
                 422: "validation", 429: "rate-limit", 500: "server"}
        for status, expected in cases.items():
            response = requests.Response()
            response.status_code = status
            response._content = b'{"detail":"test-only-private-credential"}'
            response.headers["x-request-id"] = "01234567-abcd-0000-0000-0123456789ab"

            def fail(*args, **kwargs):
                try:
                    raise requests.HTTPError("private response", response=response)
                except requests.HTTPError as original:
                    raise LangSmithError("private response") from original

            with self.subTest(status=status), self.assertRaises(rules.LangSmithRequestError) as caught:
                rules.api_request(SimpleNamespace(request_with_retries=fail), "POST", "/runs/rules")
            self.assertEqual(caught.exception.status_code, status)
            self.assertEqual(caught.exception.category, expected)
            self.assertEqual(caught.exception.request_id, response.headers["x-request-id"])
            self.assertNotIn("private", str(caught.exception))

    def test_missing_secret_error_is_actionable_without_secret_value(self):
        response = requests.Response()
        response.status_code = 400
        response._content = b'{"detail":"Missing secret AZURE_OPENAI_API_KEY: test-only-private-value"}'
        response.headers["x-request-id"] = "test-only-private-value"
        client = SimpleNamespace(request_with_retries=lambda *args, **kwargs: response)
        with self.assertRaises(rules.LangSmithRequestError) as caught:
            rules.api_request(client, "POST", "/runs/rules")
        self.assertEqual(caught.exception.category, "provider-secret")
        self.assertIsNone(caught.exception.request_id)
        self.assertNotIn("test-only-private-value", str(caught.exception))

    def test_project_suffix_is_stable_and_distinguishes_participants(self):
        self.assertEqual(analytics.participant_project("workshop", "Attendee 01"), "workshop-attendee-01")
        self.assertEqual(analytics.participant_project("workshop-attendee-01", "Attendee 01"), "workshop-attendee-01")
        self.assertNotEqual(analytics.participant_project("workshop", "01"), analytics.participant_project("workshop", "02"))
        with self.assertRaises(ValueError):
            analytics.participant_project("workshop", "---")

    def test_thread_filter_preserves_alias_and_rejects_missing_id(self):
        for alias in ("thread_id", "session_id", "conversation_id"):
            run = {"metadata": {alias: "session-a"}}
            self.assertIn(f'"{alias}"', analytics.thread_filter(run))
            self.assertEqual(analytics.thread_id(run), "session-a")
        with self.assertRaises(ValueError):
            analytics.thread_filter({})


class QueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_turn_cost_comes_from_trace_aggregate_not_root_cost(self):
        async def runs(**kwargs):
            yield {"id": "root", "run_type": "CHAIN", "total_cost": 0}
            yield {"id": "unknown", "run_type": "CHAIN", "total_cost": 0}

        async def traces(**kwargs):
            self.assertEqual(kwargs["project_id"], "project")
            yield SimpleNamespace(root_run=SimpleNamespace(id="root"),
                                  trace_aggregates=SimpleNamespace(total_cost=2.17))

        client = SimpleNamespace(runs=SimpleNamespace(query=runs), traces=SimpleNamespace(query=traces))
        roots = await analytics.query_turns(client, SimpleNamespace(id="project"), since="2026-09-25T00:00:00Z")
        self.assertEqual(analytics.turn_cost(roots[0]), 2.17)
        self.assertIsNone(analytics.turn_cost(roots[1]))

    async def test_skill_rule_requires_server_match_not_just_payload(self):
        from unittest.mock import AsyncMock
        llm = {"id": "skill-llm", "run_type": "llm", "outputs": {"messages": [
            {"content": [{"type": "tool_call", "name": "Skill", "args": {}}]}]}}
        with patch.object(analytics, "query_runs", new_callable=AsyncMock, return_value=[]), \
                patch("utils.coding_agent_diagnostics.print_diagnostics", new_callable=AsyncMock) as report:
            with self.assertRaisesRegex(ValueError, "Automatic diagnostics"):
                await analytics.verify_skill_filter(None, None, llm, "predicate", since="date")
        report.assert_awaited_once()
        self.assertEqual(report.call_args.kwargs["trigger"], "skill-filter-no-match")

    async def test_query_consumes_all_pages_and_preserves_payloads(self):
        calls = []

        def query(**kwargs):
            calls.append(kwargs)

            async def pages():
                for index in range(205):
                    yield {"id": str(index), "run_type": "TOOL", "metadata": {"ls_tool_name": "mcp__test"},
                           "outputs": {"result": index}, "total_cost": None}
            return pages()

        client = SimpleNamespace(runs=SimpleNamespace(query=query))
        rows = await analytics.query_runs(client, SimpleNamespace(id="project-a"), since="2026-09-25T00:00:00Z")
        self.assertEqual(len(rows), 205)
        self.assertEqual(rows[-1]["outputs"], {"result": 204})
        self.assertEqual(analytics.mcp_counts(rows), {"mcp__test": 205})
        self.assertIsNone(rows[0]["total_cost"])
        self.assertEqual(calls[0]["project_ids"], ["project-a"])
        self.assertEqual(calls[0]["page_size"], 100)
        self.assertIn("OUTPUTS", calls[0]["selects"])
        with self.assertRaisesRegex(ValueError, "More than 100"):
            await analytics.query_runs(client, SimpleNamespace(id="project-a"), since="2026-09-25T00:00:00Z", max_runs=100)


if __name__ == "__main__":
    unittest.main()
