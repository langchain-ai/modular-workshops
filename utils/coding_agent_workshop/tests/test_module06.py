"""Offline checks for the workshop's meaningful failure modes.

Trace fixtures below are synthetic contracts based on the official tracing
plugin's serializer, not captured user sessions. The live rehearsal is separate.
"""

import ast
import asyncio
import copy
import importlib.util
import io
import json
import linecache
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from utils import coding_agent_analytics as analytics
from utils import langsmith_rules as rules
from utils import launch_claude as launcher


def load_evaluator():
    notebook = json.loads((ROOT / "modules/06_coding_agent_analytics.ipynb").read_text())
    source = "".join(next(cell["source"] for cell in notebook["cells"] if cell["id"] == "m06-23"))
    filename = "<module06-evaluator-cell>"
    linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)
    namespace = {}
    exec(compile(source, filename, "exec"), namespace)
    return namespace["perform_eval"]


def llm_output(calls):
    return {"outputs": {"messages": [{"role": "assistant", "content": calls}]}}


def skill_call(name, call_id="a"):
    return {"type": "tool_call", "name": "Skill", "args": {"skill": name}, "id": call_id}


class ConfigurationTests(unittest.TestCase):
    def test_prepared_checkpoint_skips_all_persistent_setup_and_cleanup(self):
        notebook = json.loads((ROOT / "modules/06_coding_agent_analytics.ipynb").read_text())
        cells = {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}
        project = SimpleNamespace(id="prepared", tenant_id="workspace")
        client = Mock()
        client.read_project.return_value = project
        helpers = Mock()
        helpers.project_url.return_value = "https://example.test/project"
        namespace = {"activity_source": "prepared", "project_name": "presenter", "client": client,
                     "analytics": helpers, "rules": Mock(), "web_url": "https://example.test", "os": os,
                     "plugin_root": ROOT, "root": {}, "replay": Mock()}
        with redirect_stdout(io.StringIO()):
            for cell_id in ("m06-06", "m06-07", "m06-09", "m06-replay-smoke", "m06-27",
                            "m06-31", "m06-34", "m06-40", "m06-42", "m06-replay-usage",
                            "m06-61", "m06-63", "m06-73"):
                result = eval(compile(cells[cell_id], cell_id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT), namespace)
                if asyncio.iscoroutine(result):
                    asyncio.run(result)
        self.assertEqual(len(client.mock_calls), 1)
        self.assertEqual(len(helpers.mock_calls), 1)
        self.assertFalse(namespace["rules"].mock_calls)
        self.assertFalse(namespace["replay"].mock_calls)

    def test_notebook_reuses_existing_settings_from_both_working_directories(self):
        notebook = json.loads((ROOT / "modules/06_coding_agent_analytics.ipynb").read_text())
        cells = {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}
        env = {"LANGSMITH_API_KEY": "test-only-key", "LANGSMITH_PROJECT": "existing-workshop",
               "LANGSMITH_ENDPOINT": "https://api.smith.langchain.com", "WORKSPACE_ID": "existing-workspace",
               "CODING_AGENT_PROJECT": "obsolete-project", "WORKSHOP_JUDGE_MODEL": "obsolete-model",
               "WORKSHOP_JUDGE_TEMPLATE_RULE_ID": "obsolete-template", "WORKSHOP_CHART_FORMAT": "obsolete"}
        for directory in (ROOT, ROOT / "modules"):
            for standard_workspace in (None, "standard-workspace"):
                selected_env = dict(env)
                if standard_workspace:
                    selected_env["LANGSMITH_WORKSPACE_ID"] = standard_workspace
                with self.subTest(directory=directory, workspace=standard_workspace), \
                        patch.dict(os.environ, selected_env, clear=True), \
                        patch("pathlib.Path.cwd", return_value=directory), \
                        patch("dotenv.load_dotenv") as load, patch("langsmith.Client") as client, \
                        patch.object(analytics, "show_runs"), patch.object(analytics, "query_turns", new_callable=AsyncMock) as query, \
                        patch("getpass.getuser", return_value="attendee"), redirect_stdout(io.StringIO()) as output:
                    namespace = {"project": SimpleNamespace(id="project")}
                    for cell_id in ("m06-03", "m06-mode", "m06-04", "m06-11", "m06-27"):
                        result = eval(compile(cells[cell_id], cell_id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT), namespace)
                        if asyncio.iscoroutine(result):
                            asyncio.run(result)
                    load.assert_called_once_with(ROOT / ".env", override=True)
                    self.assertEqual(namespace["project_name"], "existing-workshop-attendee")
                    self.assertEqual(namespace["chart_format"], "v2")
                    self.assertEqual(client.call_args.kwargs["workspace_id"], standard_workspace or "existing-workspace")
                    self.assertEqual(namespace["judge_model"], rules.judge_model_config(api_key_env="OPENAI_API_KEY"))
                    query_args = query.call_args.kwargs
                    self.assertEqual(query_args["filter"], namespace["agent_filter"])
                    self.assertIn("claude-code", namespace["root_filter"])
                    self.assertNotIn(env["LANGSMITH_API_KEY"], output.getvalue())

    def test_module04_and_module06_share_judge_defaults_and_secret_references(self):
        cases = [({}, "OPENAI_API_KEY"),
                 ({"LC_GATEWAY_KEY": "test-only-old-gateway"}, "LC_GATEWAY_KEY"),
                 ({"LANGSMITH_API_KEY_GATEWAY": "test-only-gateway", "LC_GATEWAY_KEY": "test-only-old-gateway"},
                  "LANGSMITH_API_KEY_GATEWAY")]
        client = SimpleNamespace(api_key="test-only-langsmith", api_url="https://example.test",
                                 read_project=lambda **kwargs: SimpleNamespace(id="project"))
        for env, expected_secret in cases:
            env = {"OPENAI_API_KEY": "test-only-openai", **env}
            with self.subTest(secret=expected_secret), patch.dict(os.environ, env, clear=True), \
                    patch.object(rules.requests, "get") as get, patch.object(rules.requests, "post") as post:
                get.return_value.json.return_value = []
                post.return_value.json.return_value = {"tenant_id": "workspace", "id": "rule"}
                rules.create_run_rule(client, project_name="project", display_name="module04",
                                      llm_judge_prompt="Assess quality.", llm_judge_schema={})
                module04 = post.call_args.kwargs["json"]["evaluators"][0]["structured"]["model"]
                self.assertEqual(module04, rules.judge_model_config()["model"])
                self.assertEqual(module04["kwargs"]["model"], rules.DEFAULT_JUDGE_MODEL)
                self.assertEqual(module04["kwargs"]["api_key"]["id"], [expected_secret])
                self.assertEqual("base_url" in module04["kwargs"], expected_secret != "OPENAI_API_KEY")
                for value in env.values():
                    self.assertNotIn(value, json.dumps(module04))

    def test_launch_command_is_quoted_and_contains_only_nonsecret_settings(self):
        project_name = "workshop ' with spaces; $(do-not-execute)"
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-only-key"}, clear=True), \
                redirect_stdout(io.StringIO()) as output:
            analytics.launch_instructions(ROOT, ROOT / "sample copy", ROOT / "plugin", project_name,
                                          "https://example.test/api", "selected-workspace")
        command = shlex.split(output.getvalue().splitlines()[-1])
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[command.index("--env-file") + 1], str(ROOT / ".env"))
        self.assertEqual(command[command.index("--project-name") + 1], project_name)
        self.assertEqual(command[command.index("--workspace-id") + 1], "selected-workspace")
        self.assertNotIn("test-only-key", output.getvalue())

    def test_hosted_openai_choice_preserves_local_gateway_configuration(self):
        env = {"LANGSMITH_API_KEY_GATEWAY": "test-only-gateway"}
        with patch.dict(os.environ, env, clear=True):
            model = rules.judge_model_config(api_key_env="OPENAI_API_KEY")["model"]
            self.assertEqual(model["kwargs"]["api_key"]["id"], ["OPENAI_API_KEY"])
            self.assertNotIn("base_url", model["kwargs"])
            self.assertEqual(os.environ["LANGSMITH_API_KEY_GATEWAY"], "test-only-gateway")
            self.assertEqual(rules.judge_model_config()["model"]["kwargs"]["api_key"]["id"],
                             ["LANGSMITH_API_KEY_GATEWAY"])

    def test_launcher_loads_shared_env_and_overrides_stale_terminal_selection(self):
        def load_shared_env(*args, **kwargs):
            os.environ["LANGSMITH_API_KEY"] = "test-only-loaded-key"
        inherited = {"LANGSMITH_API_KEY": "test-only-old-key", "CC_LANGSMITH_API_KEY": "test-only-old-key",
                     "LANGSMITH_PROJECT": "old", "CC_LANGSMITH_PROJECT": "old",
                     "LANGSMITH_WORKSPACE_ID": "old", "WORKSPACE_ID": "old"}
        for workspace_id in (None, "selected-workspace"):
            with self.subTest(workspace=workspace_id), patch.dict(os.environ, inherited, clear=True), \
                    patch.object(launcher, "load_dotenv", side_effect=load_shared_env) as load, \
                    patch.object(launcher, "check_saved_tracing_keys"), \
                    patch.object(launcher.shutil, "which", return_value="/test/claude"), \
                    patch.object(launcher.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
                result = launcher.launch_claude(
                    env_file=ROOT / ".env", workspace=ROOT / "utils/coding_agent_workshop/sample_repo",
                    plugin_root=ROOT / "utils/coding_agent_workshop/plugin", api_url="https://example.test/api",
                    project_name="selected-project", workspace_id=workspace_id)
                load.assert_called_once_with(ROOT / ".env", override=True)
                self.assertEqual(result, 0)
                env = run.call_args.kwargs["env"]
                self.assertEqual(env["LANGSMITH_PROJECT"], "selected-project")
                self.assertEqual(env["CC_LANGSMITH_PROJECT"], "selected-project")
                self.assertEqual(env["LANGSMITH_ENDPOINT"], "https://example.test/api")
                self.assertEqual(env.get("LANGSMITH_WORKSPACE_ID"), workspace_id)
                self.assertEqual(env.get("WORKSPACE_ID"), workspace_id)
                self.assertEqual(env["CC_LANGSMITH_API_KEY"], "test-only-loaded-key")
                self.assertEqual(env["TRACE_TO_LANGSMITH"], "true")
                self.assertNotIn("test-only-loaded-key", str(run.call_args.args))
                self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_cli_uses_notebook_connection_and_workspace(self):
        for workspace_id in (None, "selected-workspace"):
            with self.subTest(workspace=workspace_id), \
                    patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-only-key", "LANGSMITH_WORKSPACE_ID": "old"}, clear=True), \
                    patch.object(analytics.shutil, "which", return_value="/test/langsmith"), \
                    patch.object(analytics.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="[]")) as run, \
                    redirect_stdout(io.StringIO()):
                analytics.run_cli(["trace", "list"], "https://example.test/api", "selected-project", workspace_id)
                env = run.call_args.kwargs["env"]
                self.assertEqual(env["LANGSMITH_PROJECT"], "selected-project")
                self.assertEqual(env["LANGSMITH_ENDPOINT"], "https://example.test/api")
                self.assertEqual(env.get("LANGSMITH_WORKSPACE_ID"), workspace_id)
                self.assertEqual(env["LANGSMITH_API_KEY"], "test-only-key")
                self.assertNotIn("test-only-key", str(run.call_args.args))

    def test_launcher_overrides_saved_tracing_settings_without_secret_arguments(self):
        def invoke(command, **kwargs):
            settings = json.loads(command[command.index("--settings") + 1])
            self.assertNotIn("CC_LANGSMITH_API_KEY", settings["env"])
            self.assertEqual(kwargs["env"]["CC_LANGSMITH_API_KEY"], "test-only-key")
            self.assertEqual(settings["env"]["CC_LANGSMITH_PROJECT"], "selected-project")
            self.assertEqual(settings["env"]["LANGSMITH_WORKSPACE_ID"], "selected-workspace")
            self.assertNotIn("test-only-key", str(command))
            self.assertFalse(kwargs["shell"])
            return SimpleNamespace(returncode=0)
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-only-key"}, clear=True), \
                patch.object(launcher, "load_dotenv"), \
                patch.object(launcher, "check_saved_tracing_keys"), \
                patch.object(launcher.shutil, "which", return_value="/test/claude"), \
                patch.object(launcher.subprocess, "run", side_effect=invoke):
            launcher.launch_claude(env_file=ROOT / ".env", workspace=ROOT,
                                  plugin_root=ROOT / "utils/coding_agent_workshop/plugin",
                                  api_url="https://example.test", project_name="selected-project",
                                  workspace_id="selected-workspace")

    def test_conflicting_saved_credential_fails_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": temp}):
            settings_path = Path(temp) / "settings.json"
            settings_path.write_text(json.dumps({"env": {"CC_LANGSMITH_API_KEY": "test-only-old-key"}}))
            with self.assertRaises(ValueError) as caught:
                launcher.check_saved_tracing_keys(Path(temp) / "sample", "test-only-new-key")
            self.assertIn("CC_LANGSMITH_API_KEY", str(caught.exception))
            self.assertNotIn("test-only-old-key", str(caught.exception))
            self.assertNotIn("test-only-new-key", str(caught.exception))
            launcher.check_saved_tracing_keys(Path(temp) / "sample", "test-only-old-key")

    def test_trace_loader_propagates_shared_project_scope(self):
        root = SimpleNamespace(id="root", end_time=datetime.now(timezone.utc))
        client = SimpleNamespace()
        agent_filter = 'and(eq(metadata_key, "ls_integration"), eq(metadata_value, "claude-code"))'
        with patch.object(analytics, "read_trace", return_value=[root]), \
                patch.object(analytics, "query_turns", return_value=[root]) as query, redirect_stdout(io.StringIO()):
            asyncio.run(analytics.load_traces(client, "shared-project", datetime.now(timezone.utc), filter=agent_filter))
        self.assertEqual(query.call_args.kwargs["filter"], agent_filter)

    def test_existing_project_thread_settings_are_reused(self):
        root = {"inputs": {"messages": []}, "outputs": {"messages": []},
                "extra": {"metadata": {"thread_id": "thread"}}}
        for existing in ({"unrelated": "keep"}, {"unrelated": "keep", "thread_idle_seconds": 600}):
            client = SimpleNamespace(read_project=Mock(return_value=SimpleNamespace(extra=existing)), update_project=Mock())
            with self.subTest(settings=existing), redirect_stdout(io.StringIO()) as output:
                analytics.configure_threads(client, SimpleNamespace(id="project"), root)
            if "thread_idle_seconds" in existing:
                client.update_project.assert_not_called()
                self.assertIn("600 seconds", output.getvalue())
            else:
                client.update_project.assert_called_once_with(
                    "project", project_extra={"unrelated": "keep", "thread_idle_seconds": 120})


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.evaluate = load_evaluator()

    def test_multiple_and_repeated_invocations_are_preserved(self):
        run = llm_output([skill_call("workshop:fix-bug", "a"), skill_call("workshop:fix-bug", "b"),
                          skill_call("workshop:review-change", "c")])
        self.assertEqual(self.evaluate(run), {"skill_name": ["workshop:fix-bug", "workshop:fix-bug", "workshop:review-change"]})

    def test_text_and_invalid_arguments_do_not_invent_a_skill(self):
        run = llm_output([
            {"type": "text", "text": "I will use Skill", "name": "Skill", "args": {"skill": "fake"}},
            {"type": "tool_call", "name": "Skill", "args": "not json"},
            {"type": "tool_call", "name": "Skill", "args": {"skill": 123}},
        ])
        self.assertEqual(self.evaluate(run), {"skill_name": []})

    def test_normalized_message_format_and_json_arguments(self):
        run = {"outputs": {"messages": [{"content": "Calling a skill", "tool_calls": [
            {"name": "Skill", "args": '{"skill":"workshop:fix-bug"}', "id": "x"}]}]}}
        self.assertEqual(self.evaluate(run), {"skill_name": ["workshop:fix-bug"]})
        self.assertEqual(analytics.observed_call_path(run), "messages.tool_calls.name")

    def test_native_tool_span_wrapper_and_metadata(self):
        run = {"id": "tool", "run_type": "tool", "name": "Skill", "inputs": {"input": {"skill": "workshop:fix-bug"}}}
        self.assertEqual(analytics.skill_name(run), "workshop:fix-bug")
        run["extra"] = {"metadata": {"ls_skill_name": "plugin:other"}}
        self.assertEqual(analytics.skill_name(run), "plugin:other")
        run["run_type"] = "llm"
        self.assertIsNone(analytics.skill_name(run))


class MetricsTests(unittest.TestCase):
    def test_cost_counts_roots_once_and_missing_scores_are_excluded(self):
        traces = {
            "r1": [{"id": "r1", "total_cost": 2},
                   {"id": "a", "run_type": "tool", "name": "Skill", "total_cost": 999,
                    "extra": {"metadata": {"ls_skill_name": "fix"}}}],
            "r2": [{"id": "r2", "total_cost": None},
                   {"id": "b", "run_type": "tool", "name": "Skill", "extra": {"metadata": {"ls_skill_name": "fix"}}}],
            "r3": [{"id": "r3", "total_cost": 0}],
        }
        rows = {row["skill group"]: row for row in analytics.turn_metrics(traces, {"r1": 0.8})}
        self.assertEqual(rows["fix"]["total cost ($)"], 2)
        self.assertEqual(rows["fix"]["costed turns"], 1)
        self.assertEqual(rows["fix"]["turns"], 2)
        self.assertEqual(rows["fix"]["mean quality"], 0.8)
        self.assertEqual(rows["fix"]["scored turns"], 1)
        self.assertEqual(rows["no_skill"]["total cost ($)"], 0)
        self.assertIsNone(rows["no_skill"]["mean quality"])

    def test_repeated_skill_and_multiple_skills_are_distinct_cases(self):
        runs = [{"id": str(i), "run_type": "tool", "name": "Skill", "extra": {"metadata": {"ls_skill_name": name}}}
                for i, name in enumerate(["fix", "fix", "review"])]
        self.assertEqual(analytics.cohort(runs[:2]), ("fix", ["fix"]))
        self.assertEqual(analytics.cohort(runs), ("multiple_skills", ["fix", "review"]))
        self.assertEqual(analytics.skill_counts(runs)["fix"], 2)

    def test_latest_quality_is_one_score_per_root(self):
        feedback = [{"run_id": "r", "key": "output_quality", "score": score, "created_at": time}
                    for score, time in [(0.2, "2026-01-01"), (0.8, "2026-01-02")]]
        self.assertEqual(analytics.latest_scores(feedback, "output_quality"), {"r": 0.8})

    def test_cohort_filters_partition_roots_without_trace_writes(self):
        skill = {"run_type": "tool", "name": "Skill", "extra": {"metadata": {"ls_skill_name": "fix"}}}
        traces = {"a": [skill], "b": [skill], "c": []}
        before = copy.deepcopy(traces)
        with patch.object(analytics, "display_table"):
            groups = analytics.cohort_filters(traces)
        self.assertEqual(traces, before)
        self.assertEqual(groups, [
            {"name": "fix", "filter": 'and(eq(is_root, true), in(id, ["a", "b"]))'},
            {"name": "no_skill", "filter": 'and(eq(is_root, true), in(id, ["c"]))'},
        ])

    def test_trace_limit_is_an_error_not_a_partial_count(self):
        async def rows(**kwargs):
            for index in range(4):
                yield {"id": str(index)}
        client = SimpleNamespace(runs=SimpleNamespace(query=rows))
        root = {"id": "0", "trace_id": "0", "start_time": datetime.now(timezone.utc)}
        with self.assertRaisesRegex(ValueError, "More than"):
            asyncio.run(analytics.read_trace(client, SimpleNamespace(id="project"), root, max_runs=3))

    def test_trace_can_exceed_the_servers_page_size(self):
        async def rows(**kwargs):
            self.assertEqual(kwargs["page_size"], 100)
            for index in range(101):
                yield {"id": str(index)}
        client = SimpleNamespace(runs=SimpleNamespace(query=rows))
        root = {"id": "0", "trace_id": "0", "start_time": datetime.now(timezone.utc)}
        runs = asyncio.run(analytics.read_trace(client, SimpleNamespace(id="project"), root, max_runs=120))
        self.assertEqual(len(runs), 101)


class MCPTests(unittest.TestCase):
    def request(self, messages):
        result = subprocess.run([sys.executable, str(ROOT / "utils/coding_agent_workshop/plugin/server.py")],
                                input="".join(json.dumps(m) + "\n" for m in messages),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_stdio_lifecycle_and_fixed_fixture(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "get_acceptance_criteria", "arguments": {"issue_id": "TASK-002"}}},
        ]
        replies = self.request(messages)
        self.assertEqual(len(replies), 3)
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(len(replies[1]["result"]["tools"]), 2)
        fixture = json.loads(replies[2]["result"]["content"][0]["text"])
        self.assertEqual(fixture["issue_id"], "TASK-002")

    def test_invalid_tool_and_traversal_input_do_not_crash_or_read_files(self):
        replies = self.request([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": [], "arguments": {}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "get_issue", "arguments": {"issue_id": "../../.env"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "unknown"},
        ])
        self.assertTrue(replies[0]["result"]["isError"])
        self.assertTrue(replies[1]["result"]["isError"])
        self.assertEqual(replies[2]["error"]["code"], -32601)


class SampleApplicationTests(unittest.TestCase):
    def test_seed_has_expected_failures_and_reference_solution_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "sample"
            shutil.copytree(ROOT / "utils/coding_agent_workshop/sample_repo", workspace,
                            ignore=shutil.ignore_patterns("__pycache__"))
            command = [sys.executable, "-B", "-m", "unittest", "-v"]
            broken = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(broken.returncode, 0)
            self.assertIn("failures=2", broken.stderr)
            shutil.copyfile(ROOT / "utils/coding_agent_workshop/solutions/tracker.py", workspace / "tracker.py")
            fixed = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=10)
            self.assertEqual(fixed.returncode, 0, fixed.stderr)

    def test_reference_order_is_stable_and_input_is_unchanged(self):
        path = ROOT / "utils/coding_agent_workshop/solutions/tracker.py"
        spec = importlib.util.spec_from_file_location("module06_solution", path)
        solution = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(solution)
        tasks = [{"id": name, "due": due, "completed": False} for name, due in
                 [("new", "2026-01-14"), ("a", "2026-01-10"), ("b", "2026-01-10")]]
        before = copy.deepcopy(tasks)
        self.assertEqual([task["id"] for task in solution.overdue_tasks(tasks, date(2026, 1, 15))], ["a", "b", "new"])
        self.assertEqual(tasks, before)


class FakeClient:
    """An in-memory API to verify preservation, scopes, and request contracts."""
    def __init__(self):
        self.rules = []
        self.sections = []
        self.charts = []
        self.calls = []

    def request_with_retries(self, method, path, **kwargs):
        request = kwargs["request_kwargs"]
        self.calls.append((method, path, copy.deepcopy(request)))
        body = copy.deepcopy(request.get("json", {}))
        params = request.get("params", {})
        if path == "/runs/rules" and method == "GET":
            data = [rule for rule in self.rules
                    if all(str(rule.get(key)) == str(value) for key, value in params.items())]
        elif path == "/runs/rules" and method == "POST":
            data = {**body, "id": f"rule-{len(self.rules)}"}
            self.rules.append(data)
        elif path.startswith("/runs/rules/") and method == "PATCH":
            data = next(rule for rule in self.rules if rule["id"] == path.rsplit("/", 1)[1])
            data.update(body)
        elif path == "/charts/section" and method == "GET":
            data = self.sections
        elif path == "/charts/section" and method == "POST":
            data = {**body, "id": "section-1"}
            self.sections.append(data)
        elif path.startswith("/charts/section/"):
            data = {"charts": self.charts}
        elif path == "/charts/create":
            data = {**body, "id": f"chart-{len(self.charts)}"}
            for index, series in enumerate(data["series"]):
                series["id"] = f"series-{len(self.charts)}-{index}"
            self.charts.append(data)
        elif path.startswith("/charts/") and method == "PATCH":
            data = next(chart for chart in self.charts if chart["id"] == path.rsplit("/", 1)[1])
            data.update(body)
        else:
            raise AssertionError(f"Unexpected API operation: {method} {path}")
        return SimpleNamespace(status_code=200, content=b"{}", json=lambda: copy.deepcopy(data))


class ProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.project = SimpleNamespace(id="project", tenant_id="workspace", name="workshop-test")

    def test_rule_rerun_preserves_id_and_pause_is_scoped(self):
        evaluator = load_evaluator()
        kwargs = dict(name="module06-skill-name", evaluator=evaluator, filter='eq(run_type, "llm")', web_url="https://example.test")
        first = rules.ensure_code_evaluator(self.client, self.project, **kwargs)
        second = rules.ensure_code_evaluator(self.client, self.project, **kwargs)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.client.rules), 1)
        self.assertTrue(any(method == "PATCH" for method, _, _ in self.client.calls))
        self.assertFalse(any(method == "DELETE" for method, _, _ in self.client.calls))
        with self.assertRaises(ValueError):
            rules.pause_evaluators(self.client, self.project, ["foreign-rule"])
        self.client.rules[0]["code_evaluators"][0]["require_attachments"] = False
        self.assertEqual(rules.pause_evaluators(self.client, self.project, [first["id"]]), 1)
        self.assertFalse(self.client.rules[0]["is_enabled"])
        self.assertEqual(set(self.client.rules[0]["code_evaluators"][0]), {"code", "language"})

    def test_template_preserves_model_authentication_context(self):
        model = {"lc": 1, "type": "constructor", "id": ["test-provider"], "kwargs": {}}
        self.client.rules = [{"id": "template", "display_name": "template", "session_id": "project", "evaluators": [
            {"structured": {"model": model, "playground_settings_id": "preset"}}]}]
        config = rules.judge_model_config(self.client, template_rule_id="template")
        result = rules.ensure_llm_evaluator(
            self.client, self.project, name="judge", prompt="Assess the response.",
            schema=rules.feedback_schema("quality", "Quality"), model_config=config,
            filter="eq(is_root, true)", web_url="https://example.test",
        )
        stored = next(rule for rule in self.client.rules if rule["id"] == result["id"])
        structured = stored["evaluators"][0]["structured"]
        self.assertEqual(structured["model"], model)
        self.assertEqual(structured["playground_settings_id"], "preset")

    def test_legacy_charts_keep_series_ids_and_use_metadata_paths(self):
        spec = {"title": "Skill invocations", "metric": "run_count",
                "filter": 'eq(name, "Skill")', "group_by": "ls_skill_name"}
        dashboard = analytics.ensure_dashboard(self.client, self.project, "https://example.test")
        with patch.object(analytics, "display_table"):
            analytics.ensure_charts(self.client, self.project, dashboard, [spec])
            series_id = self.client.charts[0]["series"][0]["id"]
            analytics.ensure_charts(self.client, self.project, dashboard, [spec])
        self.assertEqual(len(self.client.charts), 1)
        series = self.client.charts[0]["series"][0]
        self.assertEqual(series["id"], series_id)
        self.assertEqual(series["group_by"]["path"], "ls_skill_name")
        self.assertNotIn("metric_definition", series)
        self.assertEqual(series["filters"]["session"], ["project"])

    def test_invocation_chart_uses_the_analyzed_trace_population(self):
        notebook = json.loads((ROOT / "modules/06_coding_agent_analytics.ipynb").read_text())
        source = "".join(next(cell["source"] for cell in notebook["cells"] if cell["id"] == "m06-60"))
        namespace = {"json": json, "analytics": analytics, "traces": {"root-b": [], "root-a": []},
                     "cohorts": [{"name": "fix", "filter": 'in(id, ["root-a", "root-b"])'}]}
        exec(compile(source, "m06-60", "exec"), namespace)
        spec = namespace["chart_specs"][0]
        self.assertEqual(spec["filter"],
                         'and(in(trace_id, ["root-a", "root-b"]), eq(run_type, "tool"), eq(name, "Skill"))')
        self.assertEqual(spec["group_by"], "ls_skill_name")
        self.assertEqual(spec["metric"], "run_count")

    def test_cohort_charts_include_all_groups_and_preserve_series_ids(self):
        cohorts = [{"name": f"skill-{i}", "filter": f'eq(id, "root-{i}")'} for i in range(4)]
        specs = analytics.cohort_chart_specs("Quality", "feedback_score_avg", cohorts, "output_quality")
        self.assertEqual([len(spec["cohorts"]) for spec in specs], [3, 1])
        dashboard = analytics.ensure_dashboard(self.client, self.project, "https://example.test")
        with patch.object(analytics, "display_table"):
            analytics.ensure_charts(self.client, self.project, dashboard, specs)
            previous = copy.deepcopy(self.client.charts)
            analytics.ensure_charts(self.client, self.project, dashboard, specs)
        self.assertEqual(self.client.charts, previous)
        for chart in self.client.charts:
            for series in chart["series"]:
                self.assertNotIn("group_by", series)
                self.assertEqual(series["feedback_key"], "output_quality")

    def test_api_errors_do_not_expose_response_text(self):
        def fail(*args, **kwargs):
            raise RuntimeError("sensitive-provider-detail")
        client = SimpleNamespace(request_with_retries=fail)
        with self.assertRaises(RuntimeError) as caught:
            rules.api_request(client, "GET", "/runs/rules")
        self.assertNotIn("sensitive-provider-detail", str(caught.exception))

    def test_partial_chart_conversion_is_an_error(self):
        spec = {"title": "Invocations", "metric": "run_count", "filter": 'eq(name, "Skill")'}
        response = {"charts": [{"series": [{"name": "Invocations", "skipped": True}]}]}
        with patch.object(analytics, "api_request", return_value=response):
            with self.assertRaisesRegex(ValueError, "every workshop chart series"):
                analytics.chart_series(self.client, self.project, spec, "v2")

    def test_project_dashboard_preserves_existing_selection_and_metadata(self):
        for metadata in ({"owner": "workshop"}, {"default_dashboard_id": "user-dashboard"}, {}):
            current = {"extra": {"metadata": metadata, "thread_idle_seconds": 300}}
            with self.subTest(current=current), patch.object(analytics, "api_request", return_value=current) as request:
                analytics.set_project_dashboard(self.client, self.project, {"id": "workshop-dashboard"})
                should_update = not metadata.get("default_dashboard_id")
                self.assertEqual(request.call_count, 2 if should_update else 1)
                if should_update:
                    self.assertEqual(request.call_args.kwargs["json"], {"extra": {"metadata": {
                        **metadata, "default_dashboard_id": "workshop-dashboard"}}})
                    self.assertNotIn("default_dashboard_id", metadata)


if __name__ == "__main__":
    unittest.main()
