"""Centralized model initialization.

The notebooks all import `model` from here, so swapping providers only requires
editing this file. Pick exactly one `MODEL_SPEC` / `API_KEY_ENV` pair below;
`model` is built from whichever is uncommented.

`MODEL_SPEC` is data rather than a constructed client because Module 4's Harbor
section runs its agent in a container that can't import this file — it passes the
spec through Harbor's own config channel instead of duplicating the values.
"""

import os
from dotenv import load_dotenv
load_dotenv(dotenv_path="../.env", override=True)

from langchain.chat_models import init_chat_model

# --- OpenAI, direct ---
MODEL_SPEC = {"model": "openai:gpt-5.6-luna", "use_responses_api": True}
API_KEY_ENV = "OPENAI_API_KEY"

# --- OpenAI via the LangSmith LLM Gateway (Module 3 §1.4) ---
# Routes every model call through the Gateway so workspace policies
# (PII / secrets / allow-lists / cost caps) are enforced.
# MODEL_SPEC = {
#     "model": "openai:gpt-5.6-luna",
#     "base_url": "https://gateway.smith.langchain.com/openai",
#     "use_responses_api": True,
# }
# API_KEY_ENV = "LANGSMITH_API_KEY_GATEWAY"

# --- Anthropic ---
# MODEL_SPEC = {"model": "anthropic:claude-sonnet-5"}
# API_KEY_ENV = "ANTHROPIC_API_KEY"

# --- Azure OpenAI ---
# MODEL_SPEC = {"model": "azure_openai:gpt-5.6-terra", "azure_deployment": "gpt-5.6-terra"}
# API_KEY_ENV = "AZURE_OPENAI_API_KEY"

# --- Google Vertex AI ---
# Authenticates through Application Default Credentials (ADC), so no API key is
# passed to the model. For local development, configure ADC with:
#     gcloud auth application-default login
# MODEL_SPEC = {
#     "model": os.getenv("VERTEX_AI_MODEL", "gemini-2.5-flash"),
#     "model_provider": "google_vertexai",
#     "project": os.environ["GCP_PROJECT_ID"],
#     "location": os.getenv("GCP_REGION", "us-central1"),
#     "temperature": float(os.getenv("VERTEX_AI_TEMPERATURE", "0.0")),
#     "thinking_budget": int(os.getenv("THINKING_BUDGET", "-1")),
#     "include_thoughts": os.getenv("INCLUDE_THOUGHTS", "true").lower() == "true",
# }
# if max_output_tokens := os.getenv("MAX_OUTPUT_TOKENS"):
#     MODEL_SPEC["max_tokens"] = int(max_output_tokens)
# API_KEY_ENV = None

# --- AWS Bedrock ---
# Bedrock authenticates via the AWS credential chain, not a single key.
# MODEL_SPEC = {"model": "bedrock_converse:anthropic.claude-sonnet-4-20250514-v1:0"}
# API_KEY_ENV = None

model_kwargs = {"api_key": os.environ[API_KEY_ENV]} if API_KEY_ENV else {}
model = init_chat_model(**MODEL_SPEC, **model_kwargs)
