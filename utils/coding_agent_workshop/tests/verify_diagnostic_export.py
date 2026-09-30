"""Fresh-kernel verification of the actual notebook failure cells and HTML output.

Run: .venv/bin/python -m utils.coding_agent_workshop.tests.verify_diagnostic_export /tmp/report-directory
All network I/O uses the controlled offline FailureFixture.
"""

import argparse
import ast
import json
from html.parser import HTMLParser
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbconvert import HTMLExporter

from utils.coding_agent_workshop.tests.test_failure_output import REPO, notebook_cells


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = notebook_cells()
    original = nbformat.read(REPO / "modules/06_coding_agent_analytics.ipynb", as_version=4)
    nbformat.validate(original)
    for cell in original.cells:
        if cell.cell_type == "code":
            compile(cell.source, cell.id, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            assert not cell.outputs and cell.execution_count is None

    setup = """from utils.coding_agent_workshop.tests.test_failure_output import FailureFixture, REQUEST_ID
from utils import langsmith_rules as actual_rules
fixture = FailureFixture()
patches = fixture.patches()
patches.__enter__()
globals().update(fixture.namespace())
"""
    notebook = nbformat.v4.new_notebook(cells=[
        nbformat.v4.new_markdown_cell("# Diagnostic and feedback fallback verification\n\nSynthetic offline responses; not a BMS deployment test."),
        nbformat.v4.new_code_cell(setup),
        nbformat.v4.new_code_cell(source["m06-17"], id="skill-no-match"),
        nbformat.v4.new_code_cell(source["m06-25"], id="blocked-label-registration"),
        nbformat.v4.new_code_cell(source["m06-38"], id="blocked-selection-registration"),
        nbformat.v4.new_code_cell(source["m06-57"], id="missing-costs"),
        nbformat.v4.new_code_cell('fixture.query_error = actual_rules.LangSmithRequestError("POST", "/api/v2/runs/query", status=403, category="permissions", request_id=REQUEST_ID)\n' + source["m06-17"], id="skill-http-error"),
        nbformat.v4.new_code_cell('''assert not rules.mock_calls
fixture.query_error = None
fixture.structural_matches = True
rules.ensure_code_evaluator.return_value = {"id": "code-rule", "name": "module06-skill-name", "url": "https://example.test/evaluators"}
rules.ensure_llm_evaluator.return_value = {"id": "judge-rule", "name": "module06-skill-selection", "url": "https://example.test/evaluators"}
'''),
        nbformat.v4.new_code_cell(source["m06-17"], id="feedback-fallback"),
        nbformat.v4.new_code_cell(source["m06-23"], id="standalone-labeler"),
        nbformat.v4.new_code_cell(source["m06-25"], id="labeler-registration"),
        nbformat.v4.new_code_cell('''assert skill_filter_validation is None
assert rules.ensure_llm_evaluator.call_count == 0
fixture.llm["start_time"] = datetime.now(timezone.utc)
fixture.llm["outputs"]["messages"][0]["content"][1]["args"]["skill"] = "workshop:fix-bug"
fixture.feedback_matches = True
fixture.client.list_feedback = lambda **kwargs: [{"run_id": fixture.llm["id"], "key": "skill_name", "value": name} for name in perform_eval(fixture.llm)["skill_name"]]
''', id="simulate-fresh-label"),
        nbformat.v4.new_code_cell(source["m06-38"], id="feedback-judge-registration"),
        nbformat.v4.new_code_cell('''assert rules.ensure_code_evaluator.call_count == 1
assert rules.ensure_llm_evaluator.call_count == 1
assert "output_key" not in rules.ensure_llm_evaluator.call_args.kwargs["filter"]
assert "feedback_key" in rules.ensure_llm_evaluator.call_args.kwargs["filter"]
patches.close()
print("Offline export verification completed; registration calls mocked, no resource writes.")
'''),
    ], metadata={"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}})
    NotebookClient(notebook, timeout=180, allow_errors=True,
                   resources={"metadata": {"path": str(REPO)}}).execute()
    errors = [(cell.id, output.ename) for cell in notebook.cells for output in cell.get("outputs", [])
              if output.output_type == "error"]
    assert errors == [("skill-no-match", "SkillFilterUnavailable"),
                      ("blocked-label-registration", "ValueError"),
                      ("blocked-selection-registration", "ValueError"),
                      ("skill-http-error", "ValueError")], errors
    streams = {cell.id: "".join(output.text for output in cell.get("outputs", []) if output.output_type == "stream")
               for cell in notebook.cells}
    for cell_id in ("skill-no-match", "missing-costs", "skill-http-error"):
        for expected in ("DIAGNOSTICS BEGIN", "full Skill filter", "costs: helper root", "DIAGNOSTICS END"):
            assert expected in streams[cell_id], (cell_id, expected)
        assert "PRIVATE-" not in streams[cell_id]
    assert "original_error" in streams["skill-http-error"]
    assert '"status": 403' in streams["skill-http-error"]
    assert "Skill evaluation mode: feedback" in streams["feedback-fallback"]
    assert "NEW prompt" in streams["labeler-registration"]
    assert "Verified fresh Skill labels" in streams["feedback-judge-registration"]
    html, _ = HTMLExporter().from_notebook_node(notebook)
    text = Text()
    text.feed(html)
    rendered = "".join(text.parts)
    for expected in ("requested_filter", "output key", "output value", "full Skill filter", "sdk_matched",
                     "original_error", "missing-turn-costs", "DIAGNOSTICS END"):
        assert expected in rendered, expected
    assert "PRIVATE-" not in rendered
    notebook_path = args.output_dir / "failure-output.ipynb"
    html_path = args.output_dir / "failure-output.html"
    nbformat.write(notebook, notebook_path)
    html_path.write_text(html)
    print(json.dumps({"result": "passed", "expected_errors": errors,
                      "html": str(html_path), "notebook": str(notebook_path)}, indent=2))


if __name__ == "__main__":
    main()
