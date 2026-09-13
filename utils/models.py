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

# --- AWS Bedrock ---
# Bedrock authenticates via the AWS credential chain, not a single key. Uncomment
# these two lines *and* replace the `model = ...` line below with:
#     model = init_chat_model(**MODEL_SPEC)
# MODEL_SPEC = {"model": "bedrock_converse:anthropic.claude-sonnet-4-20250514-v1:0"}
# API_KEY_ENV = None

model = init_chat_model(**MODEL_SPEC, api_key=os.environ[API_KEY_ENV])
