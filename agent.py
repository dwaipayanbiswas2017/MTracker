"""
MTracker AI Agent — Built with Pydantic AI.

CLI usage:
    python agent.py
    python agent.py --provider openai --model gpt-4o
    python agent.py --provider nvidia --model google/diffusiongemma-26b-a4b-it

Programmatic usage (from Flask):
    from agent import get_response
    reply = get_response("Hello", model_id="google/diffusiongemma-26b-a4b-it")

API keys are read from environment variables:
  OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, GROQ_API_KEY,
  DEEPSEEK_API_KEY, XAI_API_KEY, OPENROUTER_API_KEY, NVIDIA_API_KEY
"""

import argparse
import os
import sys
from dotenv import load_dotenv

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, SystemPromptPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

load_dotenv()

# ─────────────────────────────────────────────────────────
#  Provider helpers
# ─────────────────────────────────────────────────────────

def make_model(model_id: str, provider_name: str, api_key: str | None = None):
    """Return a pydantic-ai Model for the given provider.

    Standard providers (openai, anthropic, groq, deepseek)
    are resolved automatically by pydantic-ai from the model string.

    Providers with custom OpenAI-compatible endpoints
    (google, openrouter, nvidia, xai) get an explicit ``OpenAIChatModel``.
    """

    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")

    custom_endpoints = {
        "google":    ("https://generativelanguage.googleapis.com/v1beta/openai/", "GOOGLE_API_KEY"),
        "openrouter":("https://openrouter.ai/api/v1",                           "OPENROUTER_API_KEY"),
        "nvidia":    ("https://integrate.api.nvidia.com/v1",                    "NVIDIA_API_KEY"),
        "xai":       ("https://api.x.ai/v1",                                    "XAI_API_KEY"),
    }

    if provider_name in custom_endpoints:
        base_url, env_key = custom_endpoints[provider_name]
        key = api_key or os.environ.get(env_key)
        if not key:
            raise ValueError(f"{env_key} is not set. Please set it in your .env file or environment.")

        provider = OpenAIProvider(base_url=base_url, api_key=key)
        return OpenAIChatModel(model_id, provider=provider)

    # Standard provider – pydantic-ai reads the correct env var itself
    # from the model-id prefix (e.g. "openai:gpt-4o" → OPENAI_API_KEY).
    return f"{provider_name}:{model_id}"


def _require_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        print(f"Error: {key} is not set.", file=sys.stderr)
        sys.exit(1)
    return val


# ─────────────────────────────────────────────────────────
#  Known models per provider (for help / defaults)
# ─────────────────────────────────────────────────────────

DEFAULT_MODELS = {
    "openai":      "gpt-4o",
    "anthropic":   "claude-sonnet-4-0",
    "google":      "gemini-2.0-flash",
    "groq":        "llama-3.3-70b-versatile",
    "deepseek":    "deepseek-chat",
    "xai":         "grok-4",
    "openrouter":  "openai/gpt-4o",
    "nvidia":      "google/diffusiongemma-26b-a4b-it",
}


# ─────────────────────────────────────────────────────────
#  NVIDIA-specific model catalogue (for the chatbot UI)
# ─────────────────────────────────────────────────────────

NVIDIA_MODELS = {
    "google/diffusiongemma-26b-a4b-it": "DiffusionGemma 26B",
    "qwen/qwen3.5-122b-a10b":           "Qwen 3.5 122B (10B active)",
}

NVIDIA_DEFAULT_MODEL = "google/diffusiongemma-26b-a4b-it"


# ─────────────────────────────────────────────────────────
#  Reusable API
# ─────────────────────────────────────────────────────────

_agent_cache: dict[str, dict] = {}

def _is_system_msg(msg) -> bool:
    """Return True if *msg* is a ModelRequest that contains a system-prompt part."""
    return isinstance(msg, ModelRequest) and any(
        p.part_kind == 'system-prompt' for p in msg.parts
    )


def create_agent(
    provider: str = "nvidia",
    model_id: str | None = None,
    api_key: str | None = None,
    system_prompt: str | None = None,
):
    """Create (or return a cached) Pydantic AI agent per model.

    Pass ``model_id`` to select a specific model (e.g. ``"qwen/qwen3.5-122b-a10b"``).
    Agents are cached per model so conversation history is preserved
    when switching back to a previously used model.
    """
    global _agent_cache
    model_id = model_id or NVIDIA_DEFAULT_MODEL

    key = f"{provider}:{model_id}"
    if key in _agent_cache:
        return _agent_cache[key]

    system_prompt = system_prompt or (
        "You are a helpful financial assistant for MTracker, "
        "a personal expense tracking application. Answer the user's "
        "questions clearly and concisely."
    )

    model = make_model(model_id, provider, api_key=api_key)
    _agent_cache[key] = {
        "agent": Agent(model=model, system_prompt=system_prompt),
        "history": [],
    }
    return _agent_cache[key]


def get_response(
    message: str,
    *,
    model_id: str | None = None,
    provider: str = "nvidia",
    api_key: str | None = None,
) -> str:
    """Send a message to the agent for the given model and return its text reply.

    Conversation history is maintained automatically per model so the agent
    remembers context across calls.
    """
    global _agent_cache
    model_id = model_id or NVIDIA_DEFAULT_MODEL
    key = f"{provider}:{model_id}"

    if key not in _agent_cache:
        create_agent(provider=provider, model_id=model_id, api_key=api_key)

    entry = _agent_cache[key]
    agent = entry["agent"]

    try:
        result = agent.run_sync(
            message,
            message_history=entry["history"],
            model_settings={"max_tokens": 512},
        )
    except (IndexError, ValueError) as e:
        raise RuntimeError(
            f"Model '{model_id}' returned an unexpected response "
            f"({type(e).__name__}: {e}). Try a different model."
        ) from e

    entry["history"] = [m for m in result.all_messages() if not _is_system_msg(m)]
    return result.output


def reset_agent(model_id: str | None = None):
    """Drop cached agent(s).

    If ``model_id`` is given only that agent is dropped;
    otherwise all cached agents are dropped.
    """
    global _agent_cache
    if model_id:
        key = f"nvidia:{model_id}"
        _agent_cache.pop(key, None)
    else:
        _agent_cache.clear()


# ─────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="MTracker AI Agent (Pydantic AI)")
    p.add_argument(
        "--provider",
        default="openai",
        choices=list(DEFAULT_MODELS),
        help="LLM provider (default: openai)",
    )
    p.add_argument(
        "--model",
        default=None,
        help=(
            "Model identifier. If omitted a sensible default is used. "
            "Examples: gpt-4o, claude-sonnet-4-0, gemini-2.0-flash, "
            "deepseek-chat, google/diffusiongemma-26b-a4b-it"
        ),
    )
    p.add_argument(
        "--system-prompt",
        default="You are a helpful financial assistant for MTracker, "
                "a personal expense tracking application. Answer the user's "
                "questions clearly and concisely.",
        help="System prompt for the agent",
    )
    p.add_argument(
        "--api-key",
        default=None,
        help="API key (overrides the corresponding *_API_KEY env var)",
    )
    return p


# ─────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────

def main() -> None:
    args = build_parser().parse_args()

    model_id = args.model or DEFAULT_MODELS[args.provider]

    agent = create_agent(
        provider=args.provider,
        model_id=model_id,
        api_key=args.api_key,
        system_prompt=args.system_prompt,
    )

    print(f"\n MTracker Agent  |  provider: {args.provider}  |  model: {model_id}")
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

        reply = get_response(user_input, model_id=model_id, provider=args.provider)
        print(f"Agent > {reply}\n")


if __name__ == "__main__":
    main()
