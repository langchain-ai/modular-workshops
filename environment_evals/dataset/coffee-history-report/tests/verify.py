"""Verifier shared by the four research-report tasks.

TOPIC_FILE selects the source file for the current task. Four checks cover report
structure and citations, one checks the report's source count, and two rerun the
agent's `sources.py`. The reward is the average of all seven checks.
"""

import json
import os
import pathlib
import re
import subprocess

WORKDIR = pathlib.Path(os.environ.get("HARBOR_WORKDIR", "/app")).resolve()
INFO = WORKDIR / "info"
REPORT = WORKDIR / "report"
TOPIC_FILE = os.environ.get("TOPIC_FILE", "")
URL_RE = re.compile(r"https?://[^\s)\]>]+")


def read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def resolve_under(root, child):
    """Resolve child and reject paths outside root."""
    root = root.resolve()
    path = (root / child).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes {root}: {child}") from exc
    return path


def report_files():
    """Return Markdown reports that resolve inside the working directory."""
    if not REPORT.is_dir():
        return []
    out = []
    for p in sorted(REPORT.glob("*.md")):
        rp = p.resolve()
        if WORKDIR in rp.parents:
            out.append(rp)
    return out


def split_body_and_sources(text):
    """Split a report into (body, sources_section) at the first 'Sources' heading."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().lstrip("#*").strip().rstrip(":*").strip().lower() == "sources":
            return "\n".join(lines[:i]), "\n".join(lines[i:])
    return text, ""


def paragraphs(body):
    """Prose paragraphs = blank-line-separated blocks that aren't pure markdown headings."""
    out = []
    for block in re.split(r"\n\s*\n", body.strip()):
        block = block.strip()
        if not block:
            continue
        if not any(ln.strip() for ln in block.splitlines() if not ln.strip().startswith("#")):
            continue
        out.append(block)
    return out


def knowledge_base_urls():
    urls = set()
    if INFO.is_dir():
        for f in INFO.glob("*.md"):
            urls |= set(URL_RE.findall(read(f)))
    return urls


NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
}


def states_count(text, n):
    """The report must state the count in a sentence that mentions sources.

    Accept the digit or its spelled-out form so formatting does not affect the score.
    """
    forms = [str(n)] + ([NUMBER_WORDS[n]] if n in NUMBER_WORDS else [])
    pattern = r"\b(" + "|".join(forms) + r")\b"
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        if "source" in sentence.lower() and re.search(pattern, sentence, re.I):
            return True
    return False


# --- read everything BEFORE the destructive step -------------------------------
files = report_files()
prose = read(files[0]) if files else ""
body, sources = split_body_and_sources(prose)

# Ground truth, derived independently of anything the agent produced.
topic_path = resolve_under(INFO, TOPIC_FILE) if TOPIC_FILE else None
true_count = len(set(URL_RE.findall(read(topic_path)))) if topic_path else 0

s = {
    "report_written": float(bool(files)),
    "three_paragraphs": float(len(paragraphs(body)) == 3),
    "sources_section": float(bool(sources.strip())),
    "grounded_in_kb": float(any(u in prose for u in knowledge_base_urls())),
    "report_ties_to_code": float(states_count(prose, true_count)),
}

# --- destructive: delete the prose, re-run the agent's own script from clean ----
for f in files:
    f.unlink(missing_ok=True)

try:
    p = subprocess.run(["python3", "sources.py"], cwd=str(WORKDIR),
                       capture_output=True, text=True, timeout=60)
    rc, out = p.returncode, p.stdout
except Exception:
    rc, out = 1, ""

s["script_reproduces"] = float(rc == 0)
s["count_correct"] = float(bool(re.search(rf"\b{true_count}\b", out)))

s["reward"] = round(sum(s.values()) / len(s), 4)

LOGS = pathlib.Path(os.environ.get("HARBOR_LOGS", "/logs/verifier"))
LOGS.mkdir(parents=True, exist_ok=True)
(LOGS / "reward.json").write_text(json.dumps(s, indent=2))
print(json.dumps(s, indent=2))
