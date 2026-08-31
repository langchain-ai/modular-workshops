#!/bin/bash
# Reference ("oracle") solution: derives the correct answer the same way the verifier does,
# so `harbor run -a oracle` proves the verifier works before spending tokens on a model.
# Topic-agnostic -- reads TOPIC_FILE (see [solution.env] in task.toml).
set -euo pipefail
python3 - <<'PY'
import os, pathlib, re

topic = os.environ["TOPIC_FILE"]
text = (pathlib.Path("/app/info") / topic).read_text()
urls = re.findall(r"https?://[^\s)\]>]+", text)
n = len(set(urls))

# The info file is already a title + three body paragraphs + a Sources section, so the
# body is a correct report body. Append the count to the LAST paragraph rather than as a
# new block, so the report still has exactly three paragraphs.
body = text.split("## Sources")[0].rstrip()
body += f" This report draws on {n} distinct sources."

out = pathlib.Path("/app/report"); out.mkdir(parents=True, exist_ok=True)
name = topic.replace("_", "-").removesuffix(".md") + "-report.md"
(out / name).write_text(
    body + "\n\n## Sources\n" + "\n".join(f"- {u}" for u in sorted(set(urls))) + "\n"
)

pathlib.Path("/app/sources.py").write_text(
    "import pathlib, re\n"
    f'text = pathlib.Path("info/{topic}").read_text()\n'
    'print(len(set(re.findall(r"https?://[^\\s)\\]>]+", text))))\n'
)
print(f"wrote report/{name} and sources.py (distinct sources: {n})")
PY
