"""Helpers for managing LangSmith run rules from code.

LangSmith supports two related automations on a tracing project:

1. **Online evaluators** — score each new run with an LLM-as-judge and attach
   the score as feedback.
2. **Annotation queue automations** — route runs matching a filter into a
   queue for a human to review.

Both are configured as "rules" against a project. The LangSmith Python SDK
doesn't expose a high-level API for them, so we call the REST endpoint
directly. `create_run_rule` returns a deep link to the rule's page in the UI.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Sequence, Union
from uuid import UUID

import requests
from langsmith import Client
from langsmith.utils import LangSmithError


# Shared by Module 4's online evaluator and Module 6's hosted judges.
DEFAULT_JUDGE_MODEL = "gpt-5.6-luna"


# --------------------------------------------------------------------------- #
# Annotation queues
# --------------------------------------------------------------------------- #

def get_or_create_annotation_queue(
    client: Client,
    name: str,
    description: str = "",
):
    """Return an existing annotation queue by name, or create one."""
    existing = list(client.list_annotation_queues(name=name))
    if existing:
        return existing[0]
    return client.create_annotation_queue(name=name, description=description)


# --------------------------------------------------------------------------- #
# Run rules
# --------------------------------------------------------------------------- #

def _llm_judge_evaluator(
    prompt: Union[str, Sequence[tuple[str, str]]],
    output_schema: dict,
    *,
    model_name: str = DEFAULT_JUDGE_MODEL,
    api_key_env: Optional[str] = None,
    temperature: float = 0,
    input_var: str = "input",
    output_var: str = "output",
) -> dict:
    """Build the `evaluators[]` payload for an LLM-as-judge online evaluator.

    `prompt` may be either:
      - a system prompt string (we'll add a default user template), or
      - a list of (role, content) tuples (full message list).

    `output_schema` is a JSON Schema dict with `title`, `description`,
    `properties`, and `required`. The LangSmith API requires those four fields.
    """
    if isinstance(prompt, str):
        messages = [
            ("system", prompt),
            ("human", f"Input: {{{{{input_var}}}}}\n\nOutput: {{{{{output_var}}}}}"),
        ]
    else:
        messages = list(prompt)

    # The judge runs on LangSmith's infrastructure, not in this process, so it never
    # sees your .env. Its credentials come from a secret stored in LangSmith →
    # Workspace settings → Secrets, referenced here by name only.
    #
    # Reuse the Gateway key name from Module 3 and utils/models.py. Keep the old
    # LC_GATEWAY_KEY name working for existing workshops. Values stay local.
    model_kwargs = {"model": model_name, "temperature": temperature}
    secret_name = api_key_env or next((name for name in ("LANGSMITH_API_KEY_GATEWAY", "LC_GATEWAY_KEY")
                                      if os.environ.get(name)), "OPENAI_API_KEY")
    if secret_name not in {"OPENAI_API_KEY", "LANGSMITH_API_KEY_GATEWAY", "LC_GATEWAY_KEY"}:
        raise ValueError("Choose OPENAI_API_KEY or one of the repository's Gateway secret names.")
    if secret_name != "OPENAI_API_KEY":
        model_kwargs["base_url"] = "https://gateway.smith.langchain.com/openai"
    model_kwargs["api_key"] = {"lc": 1, "type": "secret", "id": [secret_name]}

    return {
        "structured": {
            "prompt": [list(m) for m in messages],
            "model": {
                "lc": 1,
                "type": "constructor",
                "id": ["langchain", "chat_models", "openai", "ChatOpenAI"],
                "kwargs": model_kwargs,
            },
            "variable_mapping": {input_var: input_var, output_var: output_var},
            "schema": output_schema,
        }
    }


def create_run_rule(
    client: Client,
    *,
    project_name: str,
    display_name: str,
    filter: str = "",
    sampling_rate: float = 1.0,
    # If set: attach an LLM-as-judge online evaluator.
    llm_judge_prompt: Optional[Union[str, Sequence[tuple[str, str]]]] = None,
    llm_judge_schema: Optional[dict] = None,
    llm_judge_model: str = DEFAULT_JUDGE_MODEL,
    llm_judge_api_key_env: Optional[str] = None,
    # If set: route matching runs to this annotation queue.
    add_to_annotation_queue_id: Optional[Union[str, UUID]] = None,
) -> dict:
    """Create or replace a run rule on a tracing project.

    Returns a dict with `id`, `url` (deep link to the rule in the UI), and the
    raw `payload` LangSmith stored. Either `llm_judge_prompt` (+schema), or
    `add_to_annotation_queue_id`, or both, should be provided.
    """
    project = client.read_project(project_name=project_name)

    evaluators = []
    if llm_judge_prompt is not None:
        if llm_judge_schema is None:
            raise ValueError("llm_judge_schema is required when llm_judge_prompt is set")
        evaluators.append(
            _llm_judge_evaluator(
                llm_judge_prompt, llm_judge_schema, model_name=llm_judge_model,
                api_key_env=llm_judge_api_key_env,
            )
        )

    body = {
        "display_name": display_name,
        "session_id": str(project.id),
        "sampling_rate": sampling_rate,
        "filter": filter,
        "evaluators": evaluators,
    }
    if add_to_annotation_queue_id is not None:
        body["add_to_annotation_queue_id"] = str(add_to_annotation_queue_id)

    headers = {
        "x-api-key": client.api_key,
        "content-type": "application/json",
        "accept": "application/json",
    }

    # Idempotency: if a rule with this display_name already exists in the project,
    # delete it first. POST /runs/rules has no upsert semantics, so without this
    # rerunning a notebook cell accumulates duplicate rules.
    list_response = requests.get(
        f"{client.api_url}/runs/rules",
        params={"session_id": str(project.id)},
        headers={"x-api-key": client.api_key, "accept": "application/json"},
        timeout=30,
    )
    list_response.raise_for_status()
    for existing in list_response.json():
        if existing.get("display_name") == display_name:
            requests.delete(
                f"{client.api_url}/runs/rules/{existing['id']}",
                headers={"x-api-key": client.api_key, "accept": "application/json"},
                timeout=15,
            )

    response = requests.post(
        f"{client.api_url}/runs/rules", json=body, headers=headers, timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    tenant_id = payload["tenant_id"]
    rule_id = payload["id"]
    evaluator_id = payload.get("evaluator_id")

    # Evaluator rules (LLM-as-judge) and automation rules (queue routing, etc.)
    # have different UI pages in LangSmith.
    if evaluator_id:
        url = (
            f"https://smith.langchain.com/o/{tenant_id}/evaluators/{evaluator_id}"
            f"?ruleId={rule_id}&sourceKind=session&sourceId={project.id}"
        )
    else:
        url = (
            f"https://smith.langchain.com/o/{tenant_id}/projects/p/{project.id}"
            f"?runview=threads&tab=2"
        )

    return {"id": rule_id, "url": url, "payload": payload}


def delete_run_rule(client: Client, rule_id: Union[str, UUID]) -> None:
    """Delete a run rule by id."""
    headers = {"x-api-key": client.api_key, "accept": "application/json"}
    response = requests.delete(
        f"{client.api_url}/runs/rules/{rule_id}", headers=headers, timeout=15,
    )
    response.raise_for_status()


class LangSmithRequestError(RuntimeError):
    """Safe diagnostics for a rejected request; never includes a response body."""

    def __init__(self, method, path, *, status=None, category="request", request_id=None):
        self.status_code = status
        self.category = category
        self.request_id = request_id
        message = f"{method} {path} failed"
        message += f" (HTTP {status}, {category})" if status else f" ({category})"
        if request_id:
            message += f"; request ID: {request_id}"
        hints = {
            "authentication": "Check the API key and selected endpoint.",
            "permissions": "Check the key's workspace and the permission for this operation.",
            "provider-secret": "Check the provider secret in LangSmith workspace settings.",
            "model-configuration": "Check the hosted model's provider, deployment, endpoint and API version.",
            "validation": "Compare the request fields with this deployment's API schema.",
            "not-found": "Check the resource ID and API path on this deployment.",
            "chart-time-window": "Supply start_time and end_time when reading this dashboard's charts.",
            "rate-limit": "Allow the configured rate limit to recover before retrying.",
            "server": "Ask the deployment owner to inspect the request in server logs.",
            "timeout": "Check connectivity and server logs before retrying a create operation.",
            "connection": "Check network access and TLS from this machine to the API.",
        }
        super().__init__(message + ". " + hints.get(category, "Check server logs for this operation."))


def _request_error(method, path, exc, response=None):
    # The SDK wraps HTTPError; the original exception retains its Response.
    seen = set()
    exception_names = []
    current = exc
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        exception_names.append(type(current).__name__.lower())
        if response is None:
            response = getattr(current, "response", None)
        current = current.__cause__ or current.__context__
    status = response.status_code if response is not None else None
    category = {401: "authentication", 403: "permissions", 404: "not-found",
                400: "validation", 422: "validation", 429: "rate-limit"}.get(status, "request")
    if status and status >= 500:
        category = "server"
    if status is None:
        name = " ".join(exception_names)
        category = "timeout" if "timeout" in name else "connection" if "connection" in name else "request"
    request_id = None
    if response is not None:
        candidate = response.headers.get("x-request-id") or response.headers.get("x-correlation-id")
        if candidate and re.fullmatch(r"[a-fA-F0-9-]{8,80}", candidate):
            request_id = candidate
        # Classify a bounded body internally. Never print body text or exception messages.
        detail = response.content[:16384].decode("utf-8", errors="replace").lower()
        if status in (404, 422) and path.startswith("/charts/") and any(
                message in detail for message in ("start_time must be set.", "end_time must be set.")):
            category = "chart-time-window"
        elif status in (400, 422):
            if "secret" in detail and any(word in detail for word in ("missing", "not found", "not set", "not provided")):
                category = "provider-secret"
            elif any(word in detail for word in ("deserializ", "model", "deployment", "azure", "playground")):
                category = "model-configuration"
    return LangSmithRequestError(method, path, status=status, category=category, request_id=request_id)


# Module 6 uses the SDK's authenticated transport, including workspace headers.
def api_request(client: Client, method: str, path: str, **kwargs):
    """Retain HTTP status and a safe error category without exposing provider data."""
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Use an API-relative path.")
    response = None
    try:
        response = client.request_with_retries(
            method, path, stop_after_attempt=1,
            request_kwargs={"timeout": 30, "allow_redirects": False, **kwargs},
        )
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"HTTP {response.status_code}")
        return response.json() if response.content else None
    except (LangSmithError, requests.RequestException, RuntimeError, ValueError) as exc:
        raise _request_error(method, path, exc, response) from None


def _upsert_evaluator(client: Client, project, body: dict, web_url: str) -> dict:
    """Replace the intended project rule's configuration, retaining its ID."""
    rules = api_request(client, "GET", "/runs/rules", params={"session_id": str(project.id)})
    matches = [rule for rule in rules if rule["display_name"] == body["display_name"]]
    if len(matches) > 1:
        raise ValueError(f"Multiple rules named {body['display_name']!r}; resolve duplicates in the UI.")
    payload = {"session_id": str(project.id), "sampling_rate": 1.0, "is_enabled": True, **body}
    if matches:
        rule = api_request(client, "PATCH", f"/runs/rules/{matches[0]['id']}", json=payload)
    else:
        rule = api_request(client, "POST", "/runs/rules", json=payload)
    # The project Evaluators tab works across legacy and current evaluator pages.
    url = f"{web_url.rstrip('/')}/o/{project.tenant_id}/projects/p/{project.id}?tab=evaluators"
    return {"id": rule["id"], "name": body["display_name"], "url": url}


def ensure_code_evaluator(client: Client, project, *, name: str, evaluator, filter: str, web_url: str):
    """Upload a self-contained perform_eval(run) function from a notebook cell."""
    import inspect
    import textwrap

    if evaluator.__name__ != "perform_eval":
        raise ValueError("Hosted code must define perform_eval(run).")
    source = textwrap.dedent(inspect.getsource(evaluator))
    compile(source, "<workshop evaluator>", "exec")
    body = {"display_name": name, "filter": filter,
            "code_evaluators": [{"language": "python", "code": source}]}
    return _upsert_evaluator(client, project, body, web_url)


def judge_model_config(client: Optional[Client] = None, *, model_name: Optional[str] = None,
                       api_key_env: Optional[str] = None, template_rule_id=None,
                       provider: Optional[str] = None):
    """Reuse Module 4's defaults, or explicitly copy a working deployment rule.

    The result contains model fields for the structured evaluator and must not
    be printed. For a custom provider, supply a working evaluator's rule UUID.
    """
    import copy

    if template_rule_id:
        if client is None:
            raise ValueError("Pass a client when copying an existing evaluator rule.")
        rules = api_request(client, "GET", "/runs/rules", params={"id": str(template_rule_id)})
        matches = [rule for rule in rules if str(rule["id"]) == str(template_rule_id)]
        if len(matches) != 1:
            raise ValueError("The template rule ID did not resolve to one evaluator.")
        for evaluator in matches[0].get("evaluators") or []:
            structured = evaluator.get("structured") or {}
            model_config = structured.get("model")
            if isinstance(model_config, dict) and model_config:
                config = {"model": copy.deepcopy(model_config)}
                # Saved configurations can select organization secrets or OAuth.
                if structured.get("playground_settings_id"):
                    config["playground_settings_id"] = structured["playground_settings_id"]
                return config
        raise ValueError("Template needs an inline serialized model configuration.")
    if provider == "azure":
        from urllib.parse import urlsplit

        names = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_DEPLOYMENT_NAME")
        missing = [name for name in names if not os.getenv(name)]
        if missing:
            raise ValueError("Set the shared Azure settings: " + ", ".join(missing))
        endpoint, version, deployment = (os.environ[name] for name in names)
        parsed = urlsplit(endpoint)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Set AZURE_OPENAI_ENDPOINT to the provider URL without credentials or query parameters.")
        secret = api_key_env or "AZURE_OPENAI_API_KEY"
        if secret != "AZURE_OPENAI_API_KEY":
            raise ValueError("Use the Azure workspace secret or copy a working evaluator configuration.")
        # This constructor and field mapping are supported by self-hosted 0.16.65.
        # Omit temperature: Azure deployments differ in which values they accept.
        model = {
            "lc": 1, "type": "constructor",
            "id": ["langchain", "chat_models", "azure_openai", "AzureChatOpenAI"],
            "kwargs": {"azure_endpoint": endpoint.rstrip("/"),
                       "deployment_name": deployment, "openai_api_version": version,
                       "openai_api_key": {"lc": 1, "type": "secret", "id": [secret]}},
        }
        if model_name:
            model["kwargs"]["model"] = model_name
        return {"model": model}
    if provider not in (None, "openai", "gateway"):
        raise ValueError("Choose azure, openai, gateway, or a working template rule.")
    if api_key_env is None and provider == "openai":
        api_key_env = "OPENAI_API_KEY"
    if api_key_env is None and provider == "gateway":
        api_key_env = "LANGSMITH_API_KEY_GATEWAY"
    model = _llm_judge_evaluator("", {}, model_name=model_name or DEFAULT_JUDGE_MODEL,
                                 api_key_env=api_key_env)["structured"]["model"]
    return {"model": model}


def feedback_schema(key: str, description: str, *, categories=None) -> dict:
    """One named metric and one explanation, matching Module 4's schema pattern."""
    metric = ({"type": "string", "enum": list(categories)} if categories else
              {"type": "number", "minimum": 0, "maximum": 1})
    return {"title": key, "description": description, "type": "object",
            "properties": {key: {**metric, "description": description},
                           "comment": {"type": "string", "description": "One sentence of evidence."}},
            "required": [key, "comment"], "additionalProperties": False}


def ensure_llm_evaluator(client: Client, project, *, name: str, prompt: str, schema: dict,
                         model_config: dict, filter: str, web_url: str, thread: bool = False):
    """Upsert a hosted judge; thread judges receive all_messages after inactivity."""
    mapping = {"all_messages": "all_messages"} if thread else {"input": "input", "output": "output"}
    human = "Conversation: {{all_messages}}" if thread else "Input: {{input}}\nOutput: {{output}}"
    structured = {"prompt": [["system", prompt], ["human", human]], "template_format": "mustache",
                  "variable_mapping": mapping, "schema": schema, **model_config}
    body = {"display_name": name, "filter": filter, "evaluators": [{"structured": structured}]}
    if thread:
        body["group_by"] = "thread_id"
    return _upsert_evaluator(client, project, body, web_url)


def pause_evaluators(client: Client, project, rule_ids):
    """Pause only the recorded rule IDs that belong to this workshop project."""
    rules = api_request(client, "GET", "/runs/rules", params={"session_id": str(project.id)})
    by_id = {str(rule["id"]): rule for rule in rules}
    requested = {str(rule_id) for rule_id in rule_ids}
    if not requested <= by_id.keys():
        raise ValueError("A recorded rule is missing or belongs to a different project.")
    # PATCH requires the evaluator configuration as well as project/name/rate.
    fields = ("display_name", "filter", "evaluators", "code_evaluators", "group_by")
    for rule_id in sorted(requested):
        rule = by_id[rule_id]
        body = {key: rule[key] for key in fields if rule.get(key) is not None}
        if body.get("code_evaluators"):
            body["code_evaluators"] = [
                {"code": item["code"], "language": item["language"]}
                for item in body["code_evaluators"]
            ]
        body.update(session_id=str(project.id), sampling_rate=0.0, is_enabled=False)
        api_request(client, "PATCH", f"/runs/rules/{rule_id}", json=body)
    return len(requested)
