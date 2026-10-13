"""Replay the reviewed sample session when live Claude setup is unavailable.

This uploads recorded activity, not new model execution. Costs are historical;
online feedback is newly calculated. No historical feedback is copied.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from utils.coding_agent_analytics import query_runs
from utils.langsmith_rules import api_request

FIXTURE = Path(__file__).parent / "coding_agent_workshop/fixtures/recorded_session.json"


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_fixture():
    """Read only our fixed, reviewed fixture and reject broken relationships."""
    if FIXTURE.stat().st_size > 2_000_000:
        raise ValueError("Replay fixture exceeds the size limit.")
    fixture = json.loads(FIXTURE.read_text())
    runs = fixture["runs"]
    if fixture["version"] != 1 or not 1 <= len(runs) <= 100:
        raise ValueError("Unsupported replay fixture.")
    by_id = {run["id"]: run for run in runs}
    if len(by_id) != len(runs):
        raise ValueError("Duplicate fixture run IDs.")
    for run in runs:
        UUID(run["id"])
        root = by_id[run["trace_id"]]
        if root["parent_run_id"] is not None or root["trace_id"] != root["id"]:
            raise ValueError("Invalid fixture root.")
        if timestamp(run["end_time"]) < timestamp(run["start_time"]):
            raise ValueError("Invalid fixture duration.")
        parent = run["parent_run_id"]
        visited = {run["id"]}
        while parent is not None:
            if parent in visited or parent not in by_id or by_id[parent]["trace_id"] != root["id"]:
                raise ValueError("Invalid fixture ancestry.")
            visited.add(parent)
            parent = by_id[parent]["parent_run_id"]
    return fixture


def _save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(path)


def prepare_replay(client, project, state_dir, *, now=None):
    """Resume one attempt per target; never reuse IDs across projects/workspaces."""
    fixture = load_fixture()
    target = {"api_url": client.api_url.rstrip("/"), "project_id": str(project.id),
              "workspace_id": str(project.tenant_id)}
    digest = hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()[:20]
    path = Path(state_dir).resolve() / f"{digest}.json"
    fingerprint = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    if path.exists():
        if path.stat().st_size > 100_000:
            raise ValueError("Replay state exceeds the size limit.")
        state = json.loads(path.read_text())
        if state["target"] != target or state["fixture_sha256"] != fingerprint:
            raise ValueError("Replay state belongs to another target or fixture.")
    else:
        now = now or datetime.now(timezone.utc)
        last_end = max(timestamp(run["end_time"]) for run in fixture["runs"])
        state = {"target": target, "fixture_sha256": fingerprint, "attempt_id": str(uuid4()),
                 "shift_seconds": (now - timedelta(seconds=5) - last_end).total_seconds(),
                 "completed_stages": [], "completed_runs": []}
        _save_state(path, state)
    return {"path": path, "state": state, "fixture": fixture}


def replay_records(attempt, stage):
    """Rewrite IDs/timestamps together while preserving content and durations."""
    if stage not in {"smoke", "usage"}:
        raise ValueError("Choose smoke or usage.")
    state, fixture = attempt["state"], attempt["fixture"]
    namespace = UUID(state["attempt_id"])
    shift = timedelta(seconds=state["shift_seconds"])
    ids = {run["id"]: str(uuid5(namespace, run["id"])) for run in fixture["runs"]}
    order = {}
    records = []
    # The source is stored in tree order, with parents before children.
    for original in fixture["runs"]:
        run = copy.deepcopy(original)
        run["id"], run["trace_id"] = ids[original["id"]], ids[original["trace_id"]]
        for key in ("start_time", "end_time"):
            run[key] = (timestamp(original[key]) + shift).isoformat()
        component = timestamp(run["start_time"]).strftime("%Y%m%dT%H%M%S%fZ") + run["id"]
        parent = original["parent_run_id"]
        order[original["id"]] = order[parent] + "." + component if parent else component
        run["dotted_order"] = order[original["id"]]
        run["parent_run_id"] = ids[parent] if parent else None
        run["session_id"] = state["target"]["project_id"]
        run["extra"]["metadata"].update(
            thread_id=str(uuid5(namespace, "recorded-thread")), replayed=True,
            replay_attempt_id=state["attempt_id"], replay_source="module06-recorded-session",
        )
        run["tags"] = ["module06-replay"]
        smoke = original["trace_id"] == fixture["smoke_root_id"]
        if smoke == (stage == "smoke"):
            records.append(run)
    return records


async def upload_stage(client, project, attempt, stage):
    """Resume a bounded upload, completing roots only after their children."""
    state = attempt["state"]
    target = {"api_url": client.api_url.rstrip("/"), "project_id": str(project.id),
              "workspace_id": str(project.tenant_id)}
    if target != state["target"]:
        raise ValueError("Replay target changed. Rerun setup before uploading.")
    if stage == "usage" and "smoke" not in state["completed_stages"]:
        raise ValueError("Upload the smoke stage before usage.")
    records = replay_records(attempt, stage)
    if stage in state["completed_stages"]:
        print(f"Recorded {stage} stage already uploaded; no duplicate turns created.")
        return records
    since = min(timestamp(run["start_time"]) for run in records) - timedelta(seconds=1)
    # Read back a possibly interrupted attempt before retrying any writes.
    existing = await query_runs(client, project, since=since, ids=[run["id"] for run in records])
    present = {str(run["id"]): run for run in existing}
    completed = set(state["completed_runs"])
    roots = [run for run in records if not run["parent_run_id"]]
    for run in records:
        if run["id"] in completed or present.get(run["id"], {}).get("end_time"):
            continue
        if run["id"] not in present:
            body = dict(run)
            if not run["parent_run_id"]:
                body.pop("end_time")
                body.pop("outputs")
            api_request(client, "POST", "/runs", json=body)
        if run["parent_run_id"]:
            if run["id"] in present:
                api_request(client, "PATCH", f"/runs/{run['id']}", json={
                    "end_time": run["end_time"], "outputs": run["outputs"],
                    "trace_id": run["trace_id"], "dotted_order": run["dotted_order"],
                })
            completed.add(run["id"])
            state["completed_runs"] = sorted(completed)
            _save_state(attempt["path"], state)
    for root in roots:
        if root["id"] not in completed and not present.get(root["id"], {}).get("end_time"):
            api_request(client, "PATCH", f"/runs/{root['id']}", json={
                "end_time": root["end_time"], "outputs": root["outputs"],
                "trace_id": root["trace_id"], "dotted_order": root["dotted_order"],
            })
        completed.add(root["id"])
    state["completed_runs"] = sorted(completed)
    state["completed_stages"].append(stage)
    _save_state(attempt["path"], state)
    print(f"Uploaded recorded {stage} stage: {len(roots)} turns, {len(records)} runs. Allow indexing time.")
    return records
