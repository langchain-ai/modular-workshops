"""Fresh-kernel verification of the final notebook flow and attendee outputs.

Run: .venv/bin/python -m utils.coding_agent_workshop.tests.verify_workshop_export /tmp/report-directory
All network I/O uses controlled offline fixtures; no hosted resources are written.
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
from utils.coding_agent_workshop.tests.test_workshop_flow import PROMPT_CELLS, REGISTRATION_CELLS


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

    setup = '''import copy
from unittest.mock import patch
from utils.coding_agent_workshop.tests.test_failure_output import FailureFixture
from utils.coding_agent_workshop.tests.test_workshop_flow import workshop_namespace, RULE_NAMES
fixture = FailureFixture()
async def executions(*args, **kwargs):
    assert kwargs["filter"] == 'and(eq(run_type, "tool"), eq(name, "Skill"))'
    return [{"id": "skill-tool", "name": "Skill", "run_type": "tool",
             "inputs": {"skill": "workshop:fix-bug"}}]
fixture.primary = executions
patches = fixture.patches()
patches.__enter__()
globals().update(fixture.namespace())
trace_runs = [copy.deepcopy(fixture.llm)]
trace_runs[0]["outputs"]["messages"][0]["content"][1]["args"] = {"skill": "workshop:fix-bug"}
'''
    cells = [nbformat.v4.new_markdown_cell(
        "# Module 6 retained-flow verification\n\nSynthetic offline responses; not a BMS deployment test."),
        nbformat.v4.new_code_cell(setup)]
    for cell_id in ("m06-15", "m06-skill-executions", "m06-17", "m06-23", "m06-24", "m06-57"):
        cells.append(nbformat.v4.new_code_cell(source[cell_id], id=cell_id))
    cells.append(nbformat.v4.new_code_cell('''assert len(skill_runs) == 1
assert skill_turns == [fixture.root]
assert labels == {"skill_name": ["workshop:fix-bug"]}
assert not rules.mock_calls
assert not fixture.calls
assert metrics[0]["total cost ($)"] is None
assert metrics[0]["costed turns"] == 0
patches.close()
globals().update(workshop_namespace())
chart_format = "legacy"
project_link = analytics.project_url(project, web_url)
dashboard_patch = patch.object(analytics, "set_project_dashboard")
set_dashboard = dashboard_patch.start()
'''))
    for cell_id in PROMPT_CELLS + REGISTRATION_CELLS:
        cells.append(nbformat.v4.new_code_cell(source[cell_id], id=cell_id))
    cells.append(nbformat.v4.new_code_cell('''assert set(workshop_rules) == RULE_NAMES
assert len(client.rules) == 3
assert all(rule["filter"] == root_filter for rule in client.rules)
''', id="three-rules"))
    for cell_id in ("m06-56", "m06-60", "m06-61", "m06-63", "m06-73"):
        cells.append(nbformat.v4.new_code_cell(source[cell_id], id=cell_id))
    cells.append(nbformat.v4.new_code_cell('''assert paused == 3
assert all(not rule["is_enabled"] for rule in client.rules)
assert len(client.charts) == 3
set_dashboard.assert_called_once_with(client, project, dashboard)
dashboard_patch.stop()
print("Offline export verification completed; all network I/O mocked, no resource writes.")
'''))
    notebook = nbformat.v4.new_notebook(cells=cells, metadata={
        "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}})
    NotebookClient(notebook, timeout=180, allow_errors=False,
                   resources={"metadata": {"path": str(REPO)}}).execute()
    streams = {cell.id: "".join(output.text for output in cell.get("outputs", []) if output.output_type == "stream")
               for cell in notebook.cells}
    for stream in streams.values():
        assert "DIAGNOSTICS" not in stream
        assert "Observed output key" not in stream
    assert "Total turn cost by skill group: no measured values yet." in streams["m06-57"]
    assert "Paused 3 workshop evaluators." in streams["m06-73"]
    assert "Saved 3 charts. Open the dashboard:" in streams["m06-63"]
    assert not streams["m06-61"]
    assert all(output.output_type == "stream" for cell in notebook.cells if cell.id == "m06-63"
               for output in cell.get("outputs", [])), "Chart ID table should not be displayed"
    html, _ = HTMLExporter().from_notebook_node(notebook)
    text = Text()
    text.feed(html)
    rendered = "".join(text.parts)
    for expected in ("Parent turns:", "workshop:fix-bug", "Quality evaluator:", "Completion evaluator:",
                     "Session evaluator:", "costed turns", "Saved 3 charts. Open the dashboard:"):
        assert expected in rendered, expected
    assert "PRIVATE-" not in rendered
    notebook_path = args.output_dir / "workshop-flow.ipynb"
    html_path = args.output_dir / "workshop-flow.html"
    nbformat.write(notebook, notebook_path)
    html_path.write_text(html)
    print(json.dumps({"result": "passed", "errors": [], "code_cells_validated": sum(c.cell_type == "code" for c in original.cells),
                      "html": str(html_path), "notebook": str(notebook_path)}, indent=2))


if __name__ == "__main__":
    main()
