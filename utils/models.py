"""Centralized model initialization.

The notebooks all import `model` from here, so swapping providers
(OpenAI / Anthropic / Azure / Bedrock) only requires editing this file.

The default is OpenAI, direct, on the Responses API. Module 3 §1.4 walks
through introducing the LangSmith LLM Gateway as the production-ready
alternative — to make the switch, comment out the default below and uncomment
the gateway block.
"""

import os
from dotenv import load_dotenv
load_dotenv(dotenv_path="../.env", override=True)

from langchain.chat_models import init_chat_model

# --- Default: OpenAI, direct ---
# model = init_chat_model("openai:gpt-5.6-terra", use_responses_api=True)

# --- OpenAI via the LangSmith LLM Gateway (Module 3 §1.4) ---
# Routes every model call through the LangSmith Gateway so that workspace
# policies (PII / secrets / allow-lists / cost caps) are enforced.
model = init_chat_model(
    model="gpt-5.4-mini",
    model_provider="openai",
    base_url="https://gateway.smith.langchain.com/openai",
    use_responses_api=True,
    api_key=os.environ["LANGSMITH_API_KEY_GATEWAY"],
)

# --- Anthropic ---
# model = init_chat_model("anthropic:claude-sonnet-5")

# --- Azure OpenAI ---
# from langchain_openai import AzureChatOpenAI
# model = AzureChatOpenAI(azure_deployment="gpt-5.6-terra", streaming=True)

# --- AWS Bedrock ---
# from langchain_aws import ChatBedrockConverse
# model = ChatBedrockConverse(
#     provider="anthropic",
#     model_id="anthropic.claude-sonnet-4-20250514-v1:0",
# )
