"""
MTracker AI Agent — Built with Pydantic AI.

CLI usage:
    python agent.py
    python agent.py --provider openai --model gpt-4o
    python agent.py --provider nvidia --model google/diffusiongemma-26b-a4b-it

Programmatic usage (from Flask):
    from agent import get_response
    reply = get_response("Hello", user_id="...", db=db_obj)

API keys are read from environment variables:
  OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, GROQ_API_KEY,
  DEEPSEEK_API_KEY, XAI_API_KEY, OPENROUTER_API_KEY, NVIDIA_API_KEY
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelRequest, SystemPromptPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

load_dotenv()


# ─────────────────────────────────────────────────────────
#  Agent dependencies (injected per-call)
# ─────────────────────────────────────────────────────────

@dataclass
class AgentDeps:
    """Runtime dependencies passed to every agent tool call."""
    user_id: str
    db: Any  # DatabaseController instance


# ─────────────────────────────────────────────────────────
#  Provider helpers
# ─────────────────────────────────────────────────────────

def make_model(model_id: str, provider_name: str, api_key: str | None = None):
    """Return a pydantic-ai Model for the given provider."""
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

    return f"{provider_name}:{model_id}"


def _require_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        print(f"Error: {key} is not set.", file=sys.stderr)
        sys.exit(1)
    return val


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


NVIDIA_MODELS = {
    "google/diffusiongemma-26b-a4b-it": "DiffusionGemma 26B",
    "qwen/qwen3.5-122b-a10b":           "Qwen 3.5 122B (10B active)",
}

NVIDIA_DEFAULT_MODEL = "google/diffusiongemma-26b-a4b-it"


# ─────────────────────────────────────────────────────────
#  MCP Tool helpers
# ─────────────────────────────────────────────────────────

def _read_month(ctx: RunContext[AgentDeps], month_key: str) -> dict | None:
    """Read month data, returning None if not found."""
    data = ctx.deps.db.get_month_data(ctx.deps.user_id, month_key)
    if data is None:
        return None
    data.setdefault("income", [])
    data.setdefault("paidExpenses", [])
    data.setdefault("personalExpenses", [])
    data.setdefault("pendingExpenses", [])
    data.setdefault("notes", [])
    if not isinstance(data.get("openingBalance"), dict):
        data["openingBalance"] = {}
    return data


def _save_month(ctx: RunContext[AgentDeps], month_key: str, data: dict) -> bool:
    return ctx.deps.db.save_month_data(ctx.deps.user_id, month_key, data)


def _audit(ctx: RunContext[AgentDeps], action: str, table: str, record_id: str, details: dict = None):
    try:
        ctx.deps.db.log_audit(ctx.deps.user_id, action, table, record_id, details, origin="agent")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
#  MCP Tool Definitions
# ─────────────────────────────────────────────────────────

async def tool_get_summary(ctx: RunContext[AgentDeps], month_key: str) -> str:
    """Get a high-level financial summary (income, expenses, balance) for a month. Use YYYY-MM format for month_key."""
    data = _read_month(ctx, month_key)
    if data is None:
        return f"Month {month_key} not found. Use create_month first."
    total_income = sum(float(i["amount"]) for i in data["income"])
    total_paid = sum(float(e["amount"]) for e in data["paidExpenses"])
    total_personal = sum(float(e["amount"]) for e in data["personalExpenses"])
    ob = data.get("openingBalance", {})
    total_opening = sum(float(v) for v in ob.values()) if isinstance(ob, dict) else float(ob or 0)
    total_expenses = total_paid + total_personal
    return (
        f"Summary for {month_key}:\n"
        f"  Opening Balance: {total_opening}\n"
        f"  Income: {total_income}\n"
        f"  Expenses (Paid): {total_paid}\n"
        f"  Expenses (Personal): {total_personal}\n"
        f"  Total Expenses: {total_expenses}\n"
        f"  Net Balance: {total_opening + total_income - total_expenses}\n"
        f"  Transactions: {len(data['paidExpenses']) + len(data['personalExpenses'])}\n"
        f"  Pending Items: {len(data['pendingExpenses'])}\n"
        f"  Notes: {len(data['notes'])}"
    )


async def tool_get_month_data(ctx: RunContext[AgentDeps], month_key: str) -> str:
    """Get the full state of a month including all income, paid expenses, pending items, and notes."""
    data = ctx.deps.db.get_month_data(ctx.deps.user_id, month_key)
    if data is None:
        return f"Month {month_key} not found."
    return json.dumps(data, default=str, indent=2)


async def tool_add_paid_expense(ctx: RunContext[AgentDeps], month_key: str, amount: float, reason: str, category: str, account: str, date: str = None) -> str:
    """Record a completed (paid) transaction. amount, reason, category, and account are required. Date defaults to today."""
    data = _read_month(ctx, month_key)
    if data is None:
        return f"Month {month_key} not found. Use create_month first."
    cats = ctx.deps.db.get_categories(ctx.deps.user_id)
    if category not in cats:
        return f"Category '{category}' not found. Available: {', '.join(cats)}"
    accs = ctx.deps.db.get_accounts(ctx.deps.user_id)
    acc_names = [a["account_name"] for a in accs]
    if account not in acc_names:
        return f"Account '{account}' not found."
    item = {
        "id": str(datetime.now().timestamp()),
        "reason": reason,
        "category": category,
        "account": account,
        "amount": float(amount),
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "notes": None,
    }
    data["paidExpenses"].append(item)
    if _save_month(ctx, month_key, data):
        _audit(ctx, "INSERT", "paid_expenses", item["id"], {"month_key": month_key, "reason": reason, "amount": amount})
        return f"Expense '{reason}' ({amount}) recorded in {month_key}."
    return "Failed to save expense."


async def tool_add_income(ctx: RunContext[AgentDeps], month_key: str, amount: float, source: str, account: str) -> str:
    """Record a new income entry. amount, source, and account are required."""
    data = _read_month(ctx, month_key)
    if data is None:
        return f"Month {month_key} not found. Use create_month first."
    accs = ctx.deps.db.get_accounts(ctx.deps.user_id)
    acc_names = [a["account_name"] for a in accs]
    if account not in acc_names:
        return f"Account '{account}' not found."
    item = {
        "id": str(datetime.now().timestamp()),
        "source": source,
        "account": account,
        "amount": float(amount),
        "notes": None,
    }
    data["income"].append(item)
    if _save_month(ctx, month_key, data):
        _audit(ctx, "INSERT", "income", item["id"], {"month_key": month_key, "source": source, "amount": amount})
        return f"Income '{source}' ({amount}) recorded in {month_key}."
    return "Failed to save income."


async def tool_add_pending_item(ctx: RunContext[AgentDeps], month_key: str, amount: float, reason: str, category: str) -> str:
    """Add a planned/pending budget item to a month. amount, reason, and category are required."""
    data = _read_month(ctx, month_key)
    if data is None:
        return f"Month {month_key} not found. Use create_month first."
    cats = ctx.deps.db.get_categories(ctx.deps.user_id)
    if category not in cats:
        return f"Category '{category}' not found. Available: {', '.join(cats)}"
    item = {
        "id": str(datetime.now().timestamp()),
        "reason": reason,
        "category": category,
        "amount": float(amount),
        "mode": "online",
    }
    data["pendingExpenses"].append(item)
    if _save_month(ctx, month_key, data):
        _audit(ctx, "INSERT", "pending_expenses", item["id"], {"month_key": month_key, "reason": reason, "amount": amount})
        return f"Pending item '{reason}' ({amount}) added to {month_key}."
    return "Failed to save pending item."


async def tool_transfer_funds(ctx: RunContext[AgentDeps], month_key: str, from_account: str, to_account: str, amount: float, reason: str = None) -> str:
    """Move money between accounts. Creates a linked expense (from) and income (to) pair. from_account, to_account, and amount are required."""
    data = _read_month(ctx, month_key)
    if data is None:
        return f"Month {month_key} not found."
    accs = ctx.deps.db.get_accounts(ctx.deps.user_id)
    acc_names = [a["account_name"] for a in accs]
    if from_account not in acc_names:
        return f"Source account '{from_account}' not found."
    if to_account not in acc_names:
        return f"Destination account '{to_account}' not found."
    if from_account == to_account:
        return "Source and destination accounts must differ."
    cats = ctx.deps.db.get_categories(ctx.deps.user_id)
    if "Transfer" not in cats:
        ctx.deps.db.add_category(ctx.deps.user_id, "Transfer")
    reason = reason or "Fund Transfer"
    ref = str(datetime.now().timestamp())
    expense = {
        "id": str(datetime.now().timestamp() + 1),
        "reason": f"{reason} (to {to_account})",
        "category": "Transfer",
        "account": from_account,
        "amount": float(amount),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "notes": f"__transfer__:{ref}",
    }
    income = {
        "id": str(datetime.now().timestamp() + 2),
        "source": f"{reason} (from {from_account})",
        "account": to_account,
        "amount": float(amount),
        "notes": f"__transfer__:{ref}",
    }
    data["paidExpenses"].append(expense)
    data["income"].append(income)
    if _save_month(ctx, month_key, data):
        return f"Transferred {amount} from {from_account} to {to_account}."
    return "Failed to process transfer."


async def tool_delete_expense(ctx: RunContext[AgentDeps], month_key: str, expense_id: str) -> str:
    """Delete an expense from a month. Reverses linked debt payments and removes linked transfer entries."""
    if ctx.deps.db.delete_expense(ctx.deps.user_id, month_key, expense_id):
        return "Expense deleted successfully."
    return "Expense not found or could not be deleted."


async def tool_import_bulk(ctx: RunContext[AgentDeps], file_path: str, month_key: str) -> str:
    """Import transactions from a CSV file. Provide the server-side absolute file path."""
    import csv, io
    if not os.path.isfile(file_path):
        return f"File not found: {file_path}"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"Could not read file: {e}"
    stream = io.StringIO(content, newline=None)
    rows = list(csv.reader(stream))
    paid, pending, personal, income_total, opening = [], [], [], 0, 0
    section = None
    for i, row in enumerate(rows):
        clean = [str(c).strip() for c in row]
        first = clean[0] if clean else ""
        if "TOTAL EXPENSE LIST" in first or "PAYMENT REASON" in first:
            section = "paid"; continue
        if "PENDING" in first:
            section = "pending"; continue
        if "Personal Expenses" in first:
            section = "personal"; continue
        for ci, c in enumerate(clean):
            if "INCOME IN CURRENT MONTH" in str(c):
                try: income_total = float(clean[ci + 1].replace(",", ""))
                except: pass
            if "AVAILABLE FROM PREVIOUS MONTH" in str(c):
                try: opening = float(clean[ci + 1].replace(",", ""))
                except: pass
        if first in ("PAYMENT REASON", "Type", ""):
            continue
        try:
            ts = str(datetime.now().timestamp())
            if section == "paid" and len(clean) >= 4 and clean[3]:
                a = float(clean[3].replace(",", ""))
                if a > 0: paid.append({"id": ts + str(i), "reason": clean[0], "category": clean[1], "date": clean[2], "amount": a, "mode": "Online"})
            elif section == "pending" and len(clean) >= 4 and clean[3]:
                a = float(clean[3].replace(",", ""))
                pending.append({"id": ts + str(i), "reason": clean[0], "category": clean[1], "amount": a, "mode": clean[2]})
            elif section == "personal":
                ne = [c for c in clean if c]
                if len(ne) >= 2:
                    a = float(ne[-1].replace(",", ""))
                    personal.append({"id": ts + str(i), "reason": ne[0], "date": "", "amount": a})
        except: continue
    data = {"income": [{"id": "csv-import", "source": "CSV Import", "amount": income_total, "account": "Cash"}], "openingBalance": {"Cash": opening}, "paidExpenses": paid, "pendingExpenses": pending, "personalExpenses": personal}
    if ctx.deps.db.sync_bulk_data(ctx.deps.user_id, month_key, data):
        total = len(paid) + len(pending) + len(personal)
        return f"Imported {total} items from CSV into {month_key}."
    return "Failed to import CSV data."


async def tool_list_accounts(ctx: RunContext[AgentDeps]) -> str:
    """List all financial accounts (bank accounts, cash buckets)."""
    accs = ctx.deps.db.get_accounts(ctx.deps.user_id)
    if not accs:
        return "No accounts configured."
    return "\n".join(f"  - {a['account_name']}" for a in accs)


async def tool_add_account(ctx: RunContext[AgentDeps], account_name: str) -> str:
    """Create a new financial account."""
    if ctx.deps.db.add_account(ctx.deps.user_id, account_name):
        return f"Account '{account_name}' created."
    return f"Could not create account '{account_name}'. It may already exist."


async def tool_update_account(ctx: RunContext[AgentDeps], old_name: str, new_name: str) -> str:
    """Rename an existing financial account."""
    if ctx.deps.db.update_account(ctx.deps.user_id, old_name, new_name):
        return f"Account renamed from '{old_name}' to '{new_name}'."
    return f"Could not rename account."


async def tool_list_categories(ctx: RunContext[AgentDeps]) -> str:
    """List all expense/income categories."""
    cats = ctx.deps.db.get_categories(ctx.deps.user_id)
    if not cats:
        return "No categories configured."
    return "\n".join(f"  - {c}" for c in cats)


async def tool_add_category(ctx: RunContext[AgentDeps], category_name: str) -> str:
    """Create a new expense/income category."""
    if ctx.deps.db.add_category(ctx.deps.user_id, category_name):
        return f"Category '{category_name}' created."
    return f"Could not create category."


async def tool_update_category(ctx: RunContext[AgentDeps], old_name: str, new_name: str) -> str:
    """Rename an existing expense/income category."""
    if ctx.deps.db.update_category(ctx.deps.user_id, old_name, new_name):
        return f"Category renamed from '{old_name}' to '{new_name}'."
    return f"Could not rename category."


async def tool_list_long_pending(ctx: RunContext[AgentDeps]) -> str:
    """List all active long-term debts/loans with remaining balances."""
    items = ctx.deps.db.get_long_pending(ctx.deps.user_id)
    if not items:
        return "No long-term debts or loans."
    lines = []
    for i in items:
        lines.append(f"  [{i['id']}] {i['reason']} — Total: {i['totalAmount']}, Paid: {i['paidAmount']}, Remaining: {i['remainingAmount']}")
    return "\n".join(lines)


async def tool_add_long_pending(ctx: RunContext[AgentDeps], reason: str, total_amount: float, category: str = "General", date: str = None) -> str:
    """Create a new long-term debt/loan entry. reason and total_amount are required."""
    item = {
        "id": str(datetime.now().timestamp()),
        "reason": reason,
        "totalAmount": float(total_amount),
        "paidAmount": 0,
        "category": category,
        "createdDate": date or datetime.now().strftime("%Y-%m-%d"),
    }
    if ctx.deps.db.add_long_pending(ctx.deps.user_id, item):
        return f"Debt '{reason}' ({total_amount}) recorded."
    return "Failed to create debt entry."


async def tool_update_long_pending(ctx: RunContext[AgentDeps], id: str, reason: str, total_amount: float) -> str:
    """Update a long-term debt/loan entry. Provide the id, new reason, and new total_amount."""
    item = {"id": id, "reason": reason, "totalAmount": float(total_amount), "category": None}
    if ctx.deps.db.update_long_pending(ctx.deps.user_id, item):
        return "Debt entry updated."
    return "Debt entry not found."


async def tool_delete_long_pending(ctx: RunContext[AgentDeps], id: str) -> str:
    """Permanently remove a long-term debt/loan record. Provide the id."""
    if ctx.deps.db.delete_long_pending(ctx.deps.user_id, id):
        return "Debt entry deleted."
    return "Debt entry not found."


async def tool_pay_long_pending(ctx: RunContext[AgentDeps], item_id: str, amount: float, account: str, month_key: str) -> str:
    """Record a partial payment towards a long-term debt. Creates an expense in the specified month."""
    if ctx.deps.db.make_partial_payment(ctx.deps.user_id, item_id, month_key, float(amount), account, "Online"):
        return f"Payment of {amount} recorded towards debt."
    return "Could not process payment."


async def tool_list_months(ctx: RunContext[AgentDeps]) -> str:
    """List all months that have financial data."""
    months = ctx.deps.db.get_months(ctx.deps.user_id)
    if not months:
        return "No months found."
    return "\n".join(f"  - {m}" for m in months)


async def tool_create_month(ctx: RunContext[AgentDeps], month_key: str, copy_pending: bool = False) -> str:
    """Initialize a new month for tracking finances. Use YYYY-MM format."""
    result = ctx.deps.db.create_month(ctx.deps.user_id, month_key, copy_pending)
    if result:
        return f"Month {month_key} initialized."
    return f"Could not create month {month_key}. It may already exist."


async def tool_delete_month(ctx: RunContext[AgentDeps], month_key: str) -> str:
    """Delete an entire month and all its financial data."""
    if ctx.deps.db.delete_month(ctx.deps.user_id, month_key):
        return f"Month {month_key} deleted."
    return f"Could not delete month {month_key}."


async def tool_add_note(ctx: RunContext[AgentDeps], month_key: str, title: str, content: str) -> str:
    """Save a text note for a specific month."""
    data = _read_month(ctx, month_key)
    if data is None:
        return f"Month {month_key} not found."
    item = {"id": str(datetime.now().timestamp()), "title": title, "content": content, "date": datetime.now().strftime("%Y-%m-%d")}
    data["notes"].append(item)
    if _save_month(ctx, month_key, data):
        return f"Note '{title}' saved to {month_key}."
    return "Failed to save note."


async def tool_get_profile(ctx: RunContext[AgentDeps]) -> str:
    """Get user profile settings (name, currency, default account)."""
    user = ctx.deps.db.get_user_by_id(ctx.deps.user_id)
    if not user:
        return "User not found."
    return (
        f"Name: {user.get('name')}\n"
        f"Email: {user.get('email') or 'Not set'}\n"
        f"Phone: {user.get('phone') or 'Not set'}\n"
        f"Currency: {user.get('currency_pref', 'INR')}\n"
        f"Default Account ID: {user.get('default_account_id')}"
    )


async def tool_update_profile(ctx: RunContext[AgentDeps], name: str = None, currency_pref: str = None, default_account_id: int = None) -> str:
    """Update user profile preferences (name, currency, default account)."""
    kwargs = {}
    if name is not None: kwargs["name"] = name
    if currency_pref is not None: kwargs["currency_pref"] = currency_pref
    if default_account_id is not None: kwargs["default_account_id"] = default_account_id
    if not kwargs:
        return "No changes requested."
    if ctx.deps.db.update_user(ctx.deps.user_id, **kwargs):
        return "Profile updated."
    return "Failed to update profile."


# ─────────────────────────────────────────────────────────
#  Agent tools registry
# ─────────────────────────────────────────────────────────

AGENT_TOOLS = [
    tool_get_summary,
    tool_get_month_data,
    tool_add_paid_expense,
    tool_add_income,
    tool_add_pending_item,
    tool_transfer_funds,
    tool_delete_expense,
    tool_import_bulk,
    tool_list_accounts,
    tool_add_account,
    tool_update_account,
    tool_list_categories,
    tool_add_category,
    tool_update_category,
    tool_list_long_pending,
    tool_add_long_pending,
    tool_update_long_pending,
    tool_delete_long_pending,
    tool_pay_long_pending,
    tool_list_months,
    tool_create_month,
    tool_delete_month,
    tool_add_note,
    tool_get_profile,
    tool_update_profile,
]


# ─────────────────────────────────────────────────────────
#  Reusable API
# ─────────────────────────────────────────────────────────

_agent_cache: dict[str, dict] = {}

def _is_system_msg(msg) -> bool:
    return isinstance(msg, ModelRequest) and any(
        p.part_kind == 'system-prompt' for p in msg.parts
    )


def create_agent(
    provider: str = "nvidia",
    model_id: str | None = None,
    api_key: str | None = None,
    system_prompt: str | None = None,
):
    """Create (or return a cached) Pydantic AI agent per model with MCP tools."""
    global _agent_cache
    model_id = model_id or NVIDIA_DEFAULT_MODEL
    key = f"{provider}:{model_id}"
    if key in _agent_cache:
        return _agent_cache[key]

    system_prompt = system_prompt or (
        "You are a helpful financial assistant for MTracker, "
        "a personal expense tracking application. You have access to MCP tools "
        "that let you read and write the user's financial data. "
        "Use these tools when the user asks about their finances, "
        "wants to record transactions, or needs budget insights. "
        "Always confirm before writing data. "
        "Answer clearly and concisely."
    )

    model = make_model(model_id, provider, api_key=api_key)
    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        deps_type=AgentDeps,
        tools=AGENT_TOOLS,
    )
    _agent_cache[key] = {
        "agent": agent,
        "history": [],
    }
    return _agent_cache[key]


def get_response(
    message: str,
    *,
    user_id: str,
    db: Any,
    model_id: str | None = None,
    provider: str = "nvidia",
    api_key: str | None = None,
) -> str:
    """Send a message to the agent and return its text reply.

    The agent has access to MCP tools that operate on the user's data.
    Conversation history is maintained per model.
    """
    global _agent_cache
    model_id = model_id or NVIDIA_DEFAULT_MODEL
    key = f"{provider}:{model_id}"

    if key not in _agent_cache:
        create_agent(provider=provider, model_id=model_id, api_key=api_key)

    entry = _agent_cache[key]
    agent = entry["agent"]
    deps = AgentDeps(user_id=user_id, db=db)

    try:
        result = agent.run_sync(
            message,
            message_history=entry["history"],
            deps=deps,
            model_settings={"max_tokens": 1024},
        )
    except (IndexError, ValueError) as e:
        raise RuntimeError(
            f"Model '{model_id}' returned an unexpected response "
            f"({type(e).__name__}: {e}). Try a different model."
        ) from e

    entry["history"] = [m for m in result.all_messages() if not _is_system_msg(m)]
    return result.output


def reset_agent(model_id: str | None = None):
    """Drop cached agent(s)."""
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
    p.add_argument("--provider", default="openai", choices=list(DEFAULT_MODELS), help="LLM provider")
    p.add_argument("--model", default=None, help="Model identifier")
    p.add_argument("--system-prompt", default="You are a helpful financial assistant for MTracker...", help="System prompt")
    p.add_argument("--api-key", default=None, help="API key override")
    return p


def main() -> None:
    args = build_parser().parse_args()
    model_id = args.model or DEFAULT_MODELS[args.provider]
    agent = create_agent(provider=args.provider, model_id=model_id, api_key=args.api_key, system_prompt=args.system_prompt)

    print(f"\n MTracker Agent  |  provider: {args.provider}  |  model: {model_id}")
    print("─" * 50)
    print("Type 'quit' or 'exit' to stop.\n")

    while True:
        try:
            user_input = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not user_input: continue
        if user_input.lower() in ("quit", "exit"): break

        reply = get_response(
            user_input,
            user_id="cli",
            db=None,
            model_id=model_id,
            provider=args.provider,
        )
        print(f"Agent > {reply}\n")


if __name__ == "__main__":
    main()
