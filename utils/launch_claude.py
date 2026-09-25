"""Launch the workshop's Claude Code session with the notebook's configuration."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv


def check_saved_tracing_keys(workspace, api_key):
    """Reject saved credentials that would override the notebook's environment."""
    user_config = Path(os.getenv("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    paths = [user_config / "settings.json", Path(workspace) / ".claude/settings.json",
             Path(workspace) / ".claude/settings.local.json"]
    for path in paths:
        if not path.exists():
            continue
        try:
            settings_env = json.loads(path.read_text()).get("env", {})
        except (OSError, ValueError):
            raise ValueError(f"Could not read Claude settings at {path}.") from None
        for name in ("LANGSMITH_API_KEY", "CC_LANGSMITH_API_KEY"):
            if name in settings_env and settings_env[name] != api_key:
                raise ValueError(
                    f"{path} overrides {name}. Remove that saved override so the "
                    "workshop launcher can use LANGSMITH_API_KEY from the root .env."
                )


def launch_claude(*, env_file, workspace, plugin_root, api_url, project_name, workspace_id=None):
    """Load the shared .env; pass credentials through the child environment only."""
    load_dotenv(env_file, override=True)
    if not os.environ.get("LANGSMITH_API_KEY"):
        raise ValueError("Set LANGSMITH_API_KEY in the root .env or terminal environment.")
    check_saved_tracing_keys(workspace, os.environ["LANGSMITH_API_KEY"])
    executable = shutil.which("claude")
    if not executable:
        raise ValueError("Install Claude Code before launching the workshop session.")
    if not Path(workspace).is_dir() or not Path(plugin_root).is_dir():
        raise ValueError("Rerun the notebook's sample setup to select valid paths.")

    # Notebook selections take precedence over stale terminal/plugin settings.
    env = {**os.environ, "LANGSMITH_ENDPOINT": api_url, "LANGSMITH_PROJECT": project_name,
           "CC_LANGSMITH_PROJECT": project_name, "CC_LANGSMITH_API_KEY": os.environ["LANGSMITH_API_KEY"],
           "TRACE_TO_LANGSMITH": "true", "CC_LANGSMITH_DEFAULT_MUTED": "false"}
    for name in ("LANGSMITH_WORKSPACE_ID", "WORKSPACE_ID"):
        if workspace_id:
            env[name] = workspace_id
        else:
            env.pop(name, None)
    # Claude's saved env settings override inherited values. Set the nonsecret
    # connection fields for this invocation; credentials remain in the environment.
    names = ("LANGSMITH_ENDPOINT", "LANGSMITH_PROJECT", "CC_LANGSMITH_PROJECT",
             "TRACE_TO_LANGSMITH", "CC_LANGSMITH_DEFAULT_MUTED",
             "LANGSMITH_WORKSPACE_ID", "WORKSPACE_ID")
    settings = {"env": {name: env.get(name, "") for name in names}}
    command = [executable, "--plugin-dir", str(plugin_root), "--settings", json.dumps(settings)]
    result = subprocess.run(command, cwd=workspace, env=env, shell=False)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--workspace-id", default="")
    args = parser.parse_args()
    try:
        return launch_claude(**vars(args))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
