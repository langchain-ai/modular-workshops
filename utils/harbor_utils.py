"""Non-core helpers for Module 4's Environment Evals section.

Kept out of the notebook so the cells stay about the concepts -- seeding a scratch
workspace and printing a directory tree aren't part of what Harbor or the agent do.
"""

import shutil
from pathlib import Path


def seed_workspace(environment_dir: Path, workspace: Path) -> Path:
    """Recreate `workspace` with the task's seed files and an empty `report/`.

    Mirrors what the task's Dockerfile COPYs into the container -- run this locally
    to exercise the same agent without building anything.
    """
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    shutil.copytree(environment_dir / "info", workspace / "info")
    (workspace / "report").mkdir()
    return workspace


def print_tree(root: Path) -> None:
    """Print a directory tree, skipping __pycache__ and hidden dirs."""
    root = Path(root)
    print(f"{root.name}/")
    for path in sorted(root.rglob("*")):
        if any(part.startswith((".", "__pycache__")) for part in path.parts):
            continue
        depth = len(path.relative_to(root).parts) - 1
        print(f"{'  ' * (depth + 1)}{path.name}{'/' if path.is_dir() else ''}")
