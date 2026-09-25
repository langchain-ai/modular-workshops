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
from typing import Optional, Sequence, Union
from uuid import UUID

import requests
from langsmith import Client


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


# Module 6 uses the SDK's authenticated transport, including workspace headers.
# These additive helpers preserve the calling conventions of Modules 4 and 5.
def api_request(client: Client, method: str, path: str, **kwargs):
    """Call a LangSmith endpoint without exposing response bodies in errors."""
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Use an API-relative path.")
    try:
        response = client.request_with_retries(
            method, path, stop_after_attempt=1,
            request_kwargs={"timeout": 30, "allow_redirects": False, **kwargs},
        )
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"HTTP {response.status_code}")
        return response.json() if response.content else None
    except Exception as exc:
        raise RuntimeError(
            f"{method} {path} failed ({type(exc).__name__}). "
            "Check endpoint, workspace permissions, and deployment support."
        ) from None


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
    url = f"{web_url.rstrip('/')}/o/{project.tenant_id}/projects/p/{project.id}?tab=2"
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


def judge_model_config(client: Optional[Client] = None, *, model_name: str = DEFAULT_JUDGE_MODEL,
                       api_key_env: Optional[str] = None, template_rule_id=None):
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
    model = _llm_judge_evaluator("", {}, model_name=model_name, api_key_env=api_key_env)["structured"]["model"]
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
