"""One-shot: provision the LLM-gateway Model Configuration in a LangSmith workspace.

LangSmith's own features — Playground, Evaluators, Fleet, Chat, Insights — call models
on LangSmith's infrastructure, not yours, so they never see this repo's `.env`. They read
a workspace **Model Configuration** instead: a saved provider + model + credential
reference that admins manage under Settings → Model configurations.

This script creates one pointing at the LangSmith LLM Gateway and makes it the default for
every feature, so a workshop workspace is ready without any UI clicking.

The LangSmith Python SDK doesn't expose model configurations, so we call the REST API
directly. A model configuration is stored as a `playground-settings` row — the evaluator
API calls the same value a "Model Configuration ID".

Run once per workspace, from anywhere:

    uv run python scripts/setup_model_config.py
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from langsmith import Client

# --------------------------------------------------------------------------- #
# What we provision
# --------------------------------------------------------------------------- #

MODEL = "gpt-5.4-mini"
CONFIG_NAME = f"llm-gateway-{MODEL}"
CONFIG_DESCRIPTION = "Routes LangSmith features through the LangSmith LLM Gateway."
GATEWAY_BASE_URL = "https://gateway.smith.langchain.com/openai/v1"

# Name of the workspace secret the configuration references. LangSmith resolves it
# server-side at call time; the value never travels with a request.
SECRET_NAME = "OPENAI_API_KEY"

# Every feature that consumes a model configuration, as LangSmith names them
# (`agent-builder` is Fleet, `polly` is Chat). This list is exhaustive, and LangSmith
# does not validate the name — a typo silently stores a default nothing reads.
FEATURES = (
    "playground",
    "evaluators",
    "agent-builder",
    "polly",
    "insights-heavy",
    "insights-light",
)

AVAILABILITY_FLAGS = {
    "available_in_playground": True,
    "available_in_evaluators": True,
    "available_in_agent_builder": True,
    "available_in_polly": True,
    "available_in_insights_heavy": True,
    "available_in_insights_light": True,
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _api(client: Client) -> str:
    """Versioned API base.

    `client.api_url` is the bare host. LangSmith's Python routes answer without a
    prefix, but the platform routes (`/platform/...`) only exist under `/api/v1`,
    so spell the prefix out for every call.
    """
    return f"{client.api_url}/api/v1"


def _headers(client: Client) -> dict[str, str]:
    """Auth headers for the LangSmith API.

    A personal access token can reach every workspace its owner belongs to, so the
    target is whichever workspace the key resolves to unless `WORKSPACE_ID` pins it.
    `.env.example` ships the literal placeholder `<workspace-id>`, and sending that
    is a 401 — so only forward a value that parses as a UUID.
    """
    headers = {
        "x-api-key": client.api_key,
        "content-type": "application/json",
        "accept": "application/json",
    }
    workspace_id = os.environ.get("WORKSPACE_ID", "")
    try:
        uuid.UUID(workspace_id)
    except ValueError:
        return headers
    headers["X-Tenant-Id"] = workspace_id
    return headers


def _model_settings() -> dict:
    """The serialized ChatOpenAI constructor LangSmith stores as the configuration."""
    return {
        "lc": 1,
        "type": "constructor",
        "id": ["langchain", "chat_models", "openai", "ChatOpenAI"],
        "kwargs": {
            "model": MODEL,
            "base_url": GATEWAY_BASE_URL,
            "extra_headers": {},
            "openai_api_key": {"lc": 1, "type": "secret", "id": [SECRET_NAME]},
            "use_responses_api": True,
        },
    }


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #

def check_gateway(gateway_key: str) -> None:
    """Fail before writing anything if the gateway key is bad."""
    response = requests.get(
        f"{GATEWAY_BASE_URL}/models",
        headers={"Authorization": f"Bearer {gateway_key}"},
        timeout=30,
    )
    response.raise_for_status()


def resolve_workspace(client: Client) -> dict:
    """Report which workspace we're about to write to, so a mistake is visible."""
    response = requests.get(
        f"{_api(client)}/settings", headers=_headers(client), timeout=30,
    )
    response.raise_for_status()
    return response.json()


def ensure_secret(client: Client, gateway_key: str) -> str:
    """Set the workspace secret to the gateway key, unless it already exists."""
    response = requests.get(
        f"{_api(client)}/workspaces/current/secrets",
        headers=_headers(client),
        timeout=30,
    )
    response.raise_for_status()
    if any(secret["key"] == SECRET_NAME for secret in response.json()):
        return "already present — left alone"

    response = requests.post(
        f"{_api(client)}/workspaces/current/secrets",
        json=[{"key": SECRET_NAME, "value": gateway_key}],
        headers=_headers(client),
        timeout=30,
    )
    response.raise_for_status()
    return "set from LANGSMITH_API_KEY_GATEWAY"


def upsert_model_config(client: Client) -> tuple[str, str]:
    """Create the model configuration, or update it if this ran before.

    POST /playground-settings has no upsert semantics, so without the name lookup a
    re-run would accumulate duplicate configurations in the workspace.
    """
    response = requests.get(
        f"{_api(client)}/playground-settings",
        headers=_headers(client),
        timeout=30,
    )
    response.raise_for_status()
    existing = next(
        (row for row in response.json() if row.get("name") == CONFIG_NAME), None,
    )

    body = {
        "name": CONFIG_NAME,
        "description": CONFIG_DESCRIPTION,
        "settings": _model_settings(),
    }
    if existing:
        response = requests.patch(
            f"{_api(client)}/playground-settings/{existing['id']}",
            json=body,
            headers=_headers(client),
            timeout=30,
        )
        response.raise_for_status()
        return existing["id"], "updated"

    response = requests.post(
        f"{_api(client)}/playground-settings",
        json={**body, "scope": "workspace", "settings_type": "complex"},
        headers=_headers(client),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["id"], "created"


def enable_for_all_features(client: Client, config_id: str) -> None:
    """Make the configuration selectable in every feature.

    These flags are PATCH-only — the create endpoint ignores them, and Fleet, Chat and
    Insights default to off. A key without `workspaces:manage-model-configs` has them
    dropped server-side and still gets a 200, so check the response rather than the
    status code.
    """
    response = requests.patch(
        f"{_api(client)}/playground-settings/{config_id}",
        json=AVAILABILITY_FLAGS,
        headers=_headers(client),
        timeout=30,
    )
    response.raise_for_status()
    stored = response.json()
    ignored = [flag for flag in AVAILABILITY_FLAGS if not stored.get(flag)]
    if ignored:
        raise SystemExit(
            "LangSmith accepted the update but did not store "
            f"{', '.join(ignored)}. Setting feature access needs the workspace-admin "
            "role (the workspaces:manage-model-configs permission)."
        )


def set_as_default_everywhere(client: Client, config_id: str) -> None:
    """Preselect the configuration when a user opens each feature."""
    for feature in FEATURES:
        response = requests.put(
            f"{_api(client)}/platform/features/{feature}/default-model",
            json={"model": config_id},
            headers=_headers(client),
            timeout=30,
        )
        response.raise_for_status()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> None:
    # Load .env by absolute path: this script runs from the repo root, not `modules/`.
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=True)

    try:
        gateway_key = os.environ["LANGSMITH_API_KEY_GATEWAY"]
    except KeyError:
        raise SystemExit(
            "LANGSMITH_API_KEY_GATEWAY is not set. Copy .env.example to .env and set it "
            "to the same value as LANGSMITH_API_KEY."
        )
    if not gateway_key or gateway_key.startswith("<"):
        raise SystemExit(
            "LANGSMITH_API_KEY_GATEWAY is still the .env.example placeholder. Set it to "
            "the same value as LANGSMITH_API_KEY."
        )

    client = Client()

    check_gateway(gateway_key)
    print(f"gateway            {GATEWAY_BASE_URL} reachable, {MODEL} available")

    workspace = resolve_workspace(client)
    print(f"workspace          {workspace['display_name']} ({workspace['id']})")

    print(f"{SECRET_NAME:<18} {ensure_secret(client, gateway_key)}")

    config_id, action = upsert_model_config(client)
    print(f"model config       {CONFIG_NAME} {action} ({config_id})")

    enable_for_all_features(client, config_id)
    set_as_default_everywhere(client, config_id)
    print("feature access     enabled and set as default for "
          "Playground, Evaluators, Fleet, Chat, Insights (Thinking + Summarization)")

    print("\nVerify at https://smith.langchain.com/settings → Model configurations")


if __name__ == "__main__":
    main()
