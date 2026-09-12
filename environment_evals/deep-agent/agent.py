"""Research deep agent used as the agent-under-test for the Harbor environment eval.

Harbor's `--agent langgraph` loads the `deep_agent` graph declared in `langgraph.json`
and calls `make_graph(config)` once per trial.

Harbor stages only this directory into the container, so `utils/models.py` isn't
importable here. Rather than duplicate the model config, it arrives through Harbor's own
config channel: `--model` becomes `configurable["model"]` and `--ak model_kwargs=...`
becomes `configurable["model_kwargs"]`. Module 4 builds both from `utils.models.MODEL_SPEC`,
so this file stays model-agnostic and there is nothing to keep in sync.

The agent runs *inside* the Harbor sandbox. `LocalShellBackend` gives it real shell +
filesystem access rooted at `/app`, where the verifier later reads the report and re-runs
the agent's own `sources.py`.

`virtual_mode=False`, deliberately: with virtual mode on, the file tools present a virtual
root (`/info/...`) that doesn't match what the shell -- or the verifier's later subprocess --
actually sees (`/app/info/...`). An agent that writes a *script* using the virtual path
produces one that crashes when re-run. Literal paths keep both views consistent.
"""

from __future__ import annotations

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain.chat_models import init_chat_model


_SYSTEM_PROMPT = """You are a research assistant that writes short reports from a local markdown knowledge base.

Your working directory has two folders:
  - `info/`   : source material. One markdown file per topic (e.g. `info/noise_pollution.md`).
  - `report/` : the folder where you MUST save every report you generate.

Workflow:
  1. List the files in `info/` and choose the single file whose topic best matches the request.
  2. Read that file in full.
  3. Write the report as a markdown file into `report/`, named after the topic.

FORMAT REQUIREMENT — the body of every report MUST be exactly THREE paragraphs. Not two,
not four. After the three paragraphs you MUST include a final section whose heading is
`## Sources`, listing the reference URLs found in the source file. The Sources section does
not count as a paragraph.

If the request asks for a figure derived from the source material, put the calculation in a
Python script at the workspace root, run it, and report the number it prints. Use plain
relative paths inside that script (e.g. `info/topic.md`) so it still runs on its own.

The task instruction tells you what else the report must contain. Follow it exactly.
When you have written the report, stop.
"""


def make_graph(config):
    """Build the research agent. Called once per trial by Harbor's langgraph agent."""
    cfg = config["configurable"]
    return create_deep_agent(
        model=init_chat_model(cfg["model"], **cfg.get("model_kwargs", {})),
        system_prompt=_SYSTEM_PROMPT,
        backend=LocalShellBackend(root_dir="/app", virtual_mode=False),
    )
