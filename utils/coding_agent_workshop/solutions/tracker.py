"""Presenter solution covering TASK-001 and TASK-002; keep outside the starter copy."""

import argparse
import json
from datetime import date
from pathlib import Path


def overdue_tasks(tasks: list[dict], today: date) -> list[dict]:
    """Return unfinished past-due tasks, oldest first, without changing the input."""
    overdue = [
        task for task in tasks
        if not task["completed"] and date.fromisoformat(task["due"]) < today
    ]
    return sorted(overdue, key=lambda task: task["due"])


def main():
    parser = argparse.ArgumentParser(description="List overdue tasks.")
    parser.add_argument("--today", type=date.fromisoformat, required=True)
    parser.add_argument("--tasks", type=Path, default=Path(__file__).with_name("tasks.json"))
    args = parser.parse_args()
    tasks = json.loads(args.tasks.read_text())
    print(json.dumps(overdue_tasks(tasks, args.today), indent=2))


if __name__ == "__main__":
    main()
