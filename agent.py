"""
MTracker AI Agent — Built with Pydantic AI.

The agent has NO tool implementations of its own. All 16 tools are defined
once, in ``mcp_server.py``. This module discovers them from the MCP server
registry, builds typed pydantic-ai ``Tool`` proxies for each one, and routes
every call through ``MTrackerMCPServer.call_tool(...)`` (in-process MCP).

CLI usage:
    python agent.py

Programmatic usage (from Flask):
    from agent import get_response
    reply = get_response("Hello", user_id="...", mcp_server=mcp_server)

API keys are read from environment variables:
  NVIDIA_API_KEY
"""

import inspect
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from dotenv import load_dotenv

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelRequest, SystemPromptPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import Tool

load_dotenv()


MODEL_ID = "google/diffusiongemma-26b-a4b-it"

# The in-process agent always operates with full permissions for its user.
# Read-only enforcement applies only to over-the-wire PAT tokens.
_AGENT_SCOPE = "read_write"


# ─────────────────────────────────────────────────────────
#  Agent dependencies (injected per-call)
# ─────────────────────────────────────────────────────────

@dataclass
class AgentDeps:
    """Runtime dependencies passed to every agent tool call."""

    user_id: str
    mcp_server: Any  # MTrackerMCPServer instance
    user_name: str = "User"
    currency: str = "INR"


# ─────────────────────────────────────────────────────────
#  Model
# ─────────────────────────────────────────────────────────

def _make_model():
    """Return the pydantic-ai Model for NVIDIA DiffusionGemma."""
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        raise ValueError("NVIDIA_API_KEY is not set. Please set it in your .env file or environment.")
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=30.0))
    provider = OpenAIProvider(base_url="https://integrate.api.nvidia.com/v1", api_key=key, http_client=http_client)
    return OpenAIChatModel(MODEL_ID, provider=provider)


# ─────────────────────────────────────────────────────────
#  Dynamic tool proxy builder
#
#  Each MCP tool's JSON Schema is turned into a real, typed Python function
#  signature so pydantic-ai generates an accurate schema for the LLM
#  (correct types, parameter descriptions, optional/default handling).
# ─────────────────────────────────────────────────────────

_TYPE_MAP = {
    "string": "str",
    "number": "float",
    "integer": "int",
    "boolean": "bool",
    "array": "list",
}


def _make_tool_proxy(name: str, input_schema: dict):
    """Build an async function that forwards to the MCP server in-process.

    The returned function has a typed ``__signature__`` and ``__annotations__``
    derived from the tool's JSON Schema, so pydantic-ai can generate a proper
    JSON schema for the model.
    """
    props = input_schema.get("properties", {}) or {}
    required = set(input_schema.get("required", []) or [])

    # Namespace for the dynamically-compiled function. It must be able to
    # resolve every annotation referenced in the generated code.
    ns: dict = {}
    exec(
        "from typing import Optional, Annotated, Literal\n"
        "from pydantic import Field\n"
        "import json",
        ns,
    )

    annotations: dict[str, Any] = {}
    param_defs: list[inspect.Parameter] = []
    arg_names: list[str] = []

    # Required params first: Python forbids non-default arguments after defaults,
    # and schemas may list an optional property before a required one.
    ordered = sorted(props.items(), key=lambda kv: kv[0] not in required)
    for pname, pmeta in ordered:
        # String enums become Literal[...] so the model sees the allowed values.
        enum_vals = pmeta.get("enum") if isinstance(pmeta, dict) else None
        if isinstance(enum_vals, list) and enum_vals and all(isinstance(v, str) for v in enum_vals):
            type_expr = "Literal[" + ", ".join(repr(v) for v in enum_vals) + "]"
        else:
            type_expr = _TYPE_MAP.get(str(pmeta.get("type", "string")), "str")
        desc = pmeta.get("description", "")
        if pname in required:
            ann_expr = f"Annotated[{type_expr}, Field(description={desc!r})]"
            default = inspect.Parameter.empty
        else:
            ann_expr = f"Annotated[Optional[{type_expr}], Field(default=None, description={desc!r})]"
            default = None
        exec(f"ann = {ann_expr}", ns)
        ann = ns["ann"]
        annotations[pname] = ann
        param_defs.append(
            inspect.Parameter(
                pname,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=default,
                annotation=ann,
            )
        )
        arg_names.append(pname)

    sig = inspect.Signature(
        [inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD), *param_defs]
    )
    annotations["return"] = "str"

    args_dict = ", ".join(f"'{n}': {n}" for n in arg_names)
    body = (
        "async def proxy(ctx, " + (", ".join(arg_names) if arg_names else "") + "):\n"
        "    _r = ctx.deps.mcp_server.call_tool(\n"
        f"        {name!r}, {{{args_dict}}},\n"
        "        user_id=ctx.deps.user_id,\n"
        "        user_name=ctx.deps.user_name,\n"
        f"        scope={_AGENT_SCOPE!r},\n"
        "    )\n"
        "    if isinstance(_r, dict) and 'error' in _r:\n"
        "        return _r['error']\n"
        "    return json.dumps(_r, default=str)"
    )

    g: dict = dict(ns)
    exec(compile(body, "<proxy>", "exec"), g)
    proxy = g["proxy"]
    proxy.__signature__ = sig
    proxy.__annotations__ = annotations
    return proxy


def _build_tools(mcp_server: Any) -> list[Tool]:
    """Build one pydantic-ai Tool per registered MCP tool."""
    if mcp_server is None:
        return []
    tools: list[Tool] = []
    for tool_def in mcp_server.list_tools()["tools"]:
        proxy = _make_tool_proxy(tool_def["name"], tool_def["inputSchema"])
        tools.append(
            Tool(
                proxy,
                takes_ctx=True,
                name=tool_def["name"],
                description=tool_def["description"],
            )
        )
    return tools


# ─────────────────────────────────────────────────────────
#  System prompt
# ─────────────────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful financial assistant for MTracker, a personal expense "
    "tracking application. You have tools to read and write the user's "
    "financial data. "
    "CRITICAL: You MUST use the provided tools to answer ANY question about "
    "the user's financial data. Do NOT rely on your own knowledge. "
    "For questions about specific expenses, dates, or amounts, use "
    "get_month_data which returns all income, expenses (with dates), and "
    "pending items for a month. Use list_months first to find which months "
    "exist. Use get_summary for high-level totals. Use get_last_expense_date "
    "to find the most recent expense entry. "
    "There are TWO types of expenses: regular paid expenses and "
    "personal/daily expenses (small daily spends logged as daily logs). "
    "Both count toward total expenses. "
    "Always confirm before writing data. Answer clearly and concisely."
)


# ─────────────────────────────────────────────────────────
#  Reusable API
# ─────────────────────────────────────────────────────────

_agent_cache: dict[str, dict] = {}


def _is_system_msg(msg) -> bool:
    return isinstance(msg, ModelRequest) and any(
        p.part_kind == 'system-prompt' for p in msg.parts
    )


def create_agent(mcp_server: Any = None, system_prompt: str | None = None) -> dict:
    """Create (or return a cached) Pydantic AI agent with MCP-driven tools.

    The cache is keyed by ``mcp_server`` instance, so a fresh server builds a
    fresh tool set.
    """
    key = f"agent:{id(mcp_server) if mcp_server is not None else 'none'}"
    if key in _agent_cache:
        return _agent_cache[key]

    model = _make_model()
    agent = Agent(
        model=model,
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        deps_type=AgentDeps,
        tools=_build_tools(mcp_server),
    )
    entry = {"agent": agent, "history": []}
    _agent_cache[key] = entry
    return entry


def get_response(
    message: str,
    *,
    user_id: str,
    mcp_server: Any,
    db: Any = None,
) -> str:
    """Send a message to the agent and return its text reply.

    Args:
        message: The user's message.
        user_id: The MTracker user id the agent acts as.
        mcp_server: An ``MTrackerMCPServer`` instance providing all tools.
        db: Optional DatabaseController used only to pre-fetch profile context.
            If omitted, profile context is fetched via the ``get_profile`` tool.

    All tools execute through ``mcp_server.call_tool(...)``. Conversation
    history is maintained.
    """
    if mcp_server is None:
        raise ValueError("mcp_server is required for the agent to access tools.")

    # Load user profile for dynamic context (db is a fast path; fall back to
    # the get_profile tool when no db handle is available).
    profile = None
    if db is not None:
        profile = db.get_user_by_id(user_id)
    if profile is None:
        prof_result = mcp_server.call_tool("get_profile", {}, user_id=user_id, user_name="User", scope=_AGENT_SCOPE)
        if isinstance(prof_result, dict) and "error" not in prof_result:
            profile = prof_result

    user_name = (profile or {}).get("name") or "User"
    currency = (profile or {}).get("currency_pref") or "INR"

    entry = create_agent(mcp_server)
    agent = entry["agent"]
    deps = AgentDeps(user_id=user_id, user_name=user_name, currency=currency, mcp_server=mcp_server)

    today = datetime.now().strftime("%Y-%m-%d")
    current_month = datetime.now().strftime("%Y-%m")

    # Per-call instructions (always fresh — not cached with the agent)
    instructions = (
        f"You are helping {user_name}. Today's date is {today} "
        f"(current month: {current_month}). The user's currency is {currency}. "
        f"Always use {currency} when discussing amounts. "
        f"Month keys use YYYY-MM format (e.g., '{current_month}' for this month)."
    )

    try:
        result = agent.run_sync(
            message,
            message_history=entry["history"],
            deps=deps,
            instructions=instructions,
            model_settings={"max_tokens": 2048},
        )
    except (IndexError, ValueError) as e:
        raise RuntimeError(
            f"Model returned an unexpected response "
            f"({type(e).__name__}: {e})."
        ) from e

    entry["history"] = [m for m in result.all_messages() if not _is_system_msg(m)]
    return result.output


def reset_agent():
    """Drop the cached agents."""
    global _agent_cache
    _agent_cache.clear()


# ─────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────

def main() -> None:
    from database_controller import DatabaseController
    from mcp_server import MTrackerMCPServer

    db = DatabaseController(
        {
            'host': os.getenv('host'),
            'user': os.getenv('user'),
            'password': os.getenv('password'),
            'database': os.getenv('database'),
        }
    )
    mcp_server = MTrackerMCPServer(db)
    user_id = os.getenv("CLI_USER_ID", "cli")

    print(f"\n MTracker Agent  |  model: {MODEL_ID}")
    print("─" * 50)
    print("Type 'quit' or 'exit' to stop.\n")

    while True:
        try:
            user_input = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            break

        reply = get_response(user_input, user_id=user_id, mcp_server=mcp_server, db=db)
        print(f"Agent > {reply}\n")


if __name__ == "__main__":
    main()