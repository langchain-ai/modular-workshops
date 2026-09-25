"""A small task tracker with a seeded overdue-task bug for Module 6."""

import argparse
import json
from datetime import date
from pathlib import Path


def overdue_tasks(tasks: list[dict], today: date) -> list[dict]:
    """Return the tasks that need attention before today's work begins."""
    # TASK-001: this condition does not yet match the acceptance criteria.
    return [task for task in tasks if date.fromisoformat(task["due"]) <= today]


def main():
    parser = argparse.ArgumentParser(description="List overdue tasks.")
    parser.add_argument("--today", type=date.fromisoformat, required=True)
    parser.add_argument("--tasks", type=Path, default=Path(__file__).with_name("tasks.json"))
    args = parser.parse_args()
    tasks = json.loads(args.tasks.read_text())
    print(json.dumps(overdue_tasks(tasks, args.today), indent=2))


if __name__ == "__main__":
    main()
