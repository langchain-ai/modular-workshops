"""A small read-only stdio MCP server backed by two fixed workshop issues.

Only the MCP methods needed for this exercise are implemented. Messages are
newline-delimited JSON; stdout is reserved for the protocol. No dependencies.
"""

import json
import sys
from pathlib import Path

ISSUES = json.loads(Path(__file__).with_name("fixtures").joinpath("issues.json").read_text())
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_MESSAGE_BYTES = 1024 * 1024
INPUT_SCHEMA = {
    "type": "object",
    "properties": {"issue_id": {"type": "string", "enum": list(ISSUES)}},
    "required": ["issue_id"],
    "additionalProperties": False,
}
TOOLS = [
    {"name": "get_issue", "description": "Read a workshop issue's title and description.",
     "inputSchema": INPUT_SCHEMA},
    {"name": "get_acceptance_criteria", "description": "Read a workshop issue's acceptance criteria.",
     "inputSchema": INPUT_SCHEMA},
]


def tool_result(name, arguments):
    """Return only fixed fixture records selected by a validated issue ID."""
    if not isinstance(name, str) or name not in {tool["name"] for tool in TOOLS}:
        return {"isError": True, "content": [{"type": "text", "text": "Unknown tool."}]}
    if not isinstance(arguments, dict) or set(arguments) != {"issue_id"}:
        return {"isError": True, "content": [{"type": "text", "text": "Supply only issue_id."}]}
    issue_id = arguments["issue_id"]
    if not isinstance(issue_id, str) or issue_id not in ISSUES:
        return {"isError": True, "content": [{"type": "text", "text": "Use TASK-001 or TASK-002."}]}

    issue = ISSUES[issue_id]
    keys = ("title", "description") if name == "get_issue" else ("acceptance_criteria",)
    result = {"issue_id": issue_id, **{key: issue[key] for key in keys}}
    return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": False}


def handle_message(message):
    """Dispatch the minimal MCP lifecycle and tool methods."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return error_response(None, -32600, "Invalid JSON-RPC request.")
    request_id = message.get("id")
    if "id" not in message:
        return None  # Notifications, including notifications/initialized, have no reply.
    params = message.get("params", {})
    if not isinstance(params, dict):
        return error_response(request_id, -32602, "Parameters must be an object.")

    method = message.get("method")
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "workshop-issues", "version": "1.0.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = tool_result(params.get("name"), params.get("arguments"))
    else:
        return error_response(request_id, -32601, "Method not found.")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main():
    while line := sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1):
        if len(line) > MAX_MESSAGE_BYTES:
            response = error_response(None, -32600, "Message is too large.")
            print(json.dumps(response), flush=True)
            return
        try:
            response = handle_message(json.loads(line))
        except (ValueError, UnicodeDecodeError):
            response = error_response(None, -32700, "Invalid JSON.")
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
