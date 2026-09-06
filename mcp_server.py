"""
MTracker MCP Server — single source of truth for all AI tools.

This module is the ONLY place where tool implementations live. Both the
Pydantic AI web/CLI agent (`agent.py`) and the Model Context Protocol
over-the-wire transport consume the exact same tool registry:

  * In-process:  ``MTrackerMCPServer.call_tool(...)`` (used by ``agent.py``)
  * Over-the-wire: JSON-RPC 2.0 over SSE (used by Claude/Gemini clients)

Transport endpoints (exposed by ``app.py``):
  GET  /api/mcp/sse        — SSE stream (server → client)
  POST /api/mcp/messages   — JSON-RPC requests (client → server)

Each tool is declared with a rich ``description`` and a full JSON Schema
``input_schema``. ``agent.py`` uses this metadata to build typed function
signatures dynamically, so the agent and every external MCP client see
identical, well-documented tools.
"""

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from database_controller import DatabaseController


# JSON-RPC 2.0 error codes (industry standard)
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_ERROR = -32000

PROTOCOL_VERSION = "2024-11-05"

# Spec versions this server can speak. Our wire surface (initialize / ping /
# tools / resources over SSE) is compatible across all of them, so during the
# `initialize` handshake we echo back the client's version when supported.
# Without this, modern clients (e.g. VSCode, which offers 2025-11-25) reject
# the hardcoded 2024-11-05 answer and never list tools.
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")


# ─────────────────────────────────────────────────────────
#  Tool descriptor
# ─────────────────────────────────────────────────────────

@dataclass
class MCPTool:
    """Single declarative tool definition shared by agent and wire transport."""

    name: str
    description: str
    input_schema: dict
    handler: Callable
    read_only: bool = False
    # For grouped (multi-action) tools: the set of `action` values a `read`
    # scoped token may invoke. None = legacy per-tool `read_only` flag.
    # Missing/unknown actions fail closed under `read` scope.
    read_actions: set | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


# ─────────────────────────────────────────────────────────
#  Session manager (over-the-wire SSE transport only)
# ─────────────────────────────────────────────────────────

class MCPSession:
    """Tracks a single SSE connection and its pending responses."""

    def __init__(self, session_id: str, user_id: str, user_name: str, scope: str):
        self.session_id = session_id
        self.user_id = user_id
        self.user_name = user_name
        self.scope = scope
        self.created_at = time.time()
        self.pending_responses: list[dict] = []
        self._lock = threading.Lock()

    def add_response(self, response: dict):
        with self._lock:
            self.pending_responses.append(response)

    def drain_responses(self) -> list[dict]:
        with self._lock:
            items = list(self.pending_responses)
            self.pending_responses.clear()
            return items


class MCPSessionManager:
    """Manages all active MCP sessions.

    Thread-safe, but NOT process-safe: sessions live in this process's memory.
    The server must run as a single worker process (gunicorn gthread,
    ``--workers 1``) so the SSE stream and the messages POSTs share state.
    """

    def __init__(self):
        self._sessions: dict[str, MCPSession] = {}
        self._lock = threading.Lock()

    def create(self, session_id: str, user_id: str, user_name: str, scope: str) -> MCPSession:
        session = MCPSession(session_id, user_id, user_name, scope)
        with self._lock:
            self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> MCPSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id: str):
        with self._lock:
            self._sessions.pop(session_id, None)

    def cleanup_stale(self, max_age: float = 300.0):
        now = time.time()
        with self._lock:
            stale = [sid for sid, s in self._sessions.items() if now - s.created_at > max_age]
            for sid in stale:
                self._sessions.pop(sid, None)


sessions = MCPSessionManager()


# ─────────────────────────────────────────────────────────
#  JSON-RPC 2.0 helpers
# ─────────────────────────────────────────────────────────

def make_jsonrpc_error(code: int, message: str, req_id: Any = None) -> dict:
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": req_id}


def make_jsonrpc_result(result: Any, req_id: Any = None) -> dict:
    return {"jsonrpc": "2.0", "result": result, "id": req_id}


def _is_notification(msg: dict) -> bool:
    """A JSON-RPC notification has no ``id`` — the server must not reply."""
    return "id" not in msg


# ─────────────────────────────────────────────────────────
#  MCP Server
# ─────────────────────────────────────────────────────────

class MTrackerMCPServer:
    """
    MTracker tool server.

    * ``call_tool(name, arguments, *, user_id, user_name, scope)`` — the
      in-process API used by ``agent.py``. Returns the raw tool result dict.
    * ``dispatch(message, user_id, user_name, scope)`` — spec-compliant
      JSON-RPC 2.0 dispatcher for the over-the-wire transport.
    """

    def __init__(self, db: DatabaseController):
        self.db = db
        self._tools: dict[str, MCPTool] = {}
        self._register_tools()

    # ── Tool registration ──────────────────────────────

    def _add_tool(self, name: str, description: str, input_schema: dict, handler: Callable, read_only: bool = False, read_actions: set | None = None):
        if name in self._tools:
            raise ValueError(f"Duplicate tool registration: {name}")
        self._tools[name] = MCPTool(name, description, input_schema, handler, read_only=read_only, read_actions=read_actions)

    def _register_tools(self):
        """Register all 16 MCP tools (grouped by entity) with full descriptions and parameter schemas."""

        # ── Financial data query (read-only) ───────────

        self._add_tool(
            name="get_summary",
            description=(
                "Get a high-level financial summary for a specific month. "
                "Returns total income, total expenses (paid + personal/daily), net balance, "
                "per-account opening balances, and transaction counts."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format, e.g. '2025-11' (optional, defaults to current month)",
                    }
                },
                "required": [],
            },
            handler=self._handle_get_summary,
            read_only=True,
        )

        self._add_tool(
            name="get_month_data",
            description=(
                "Get the full state of a month including all income entries, "
                "paid expenses, personal expenses, pending expenses, notes, "
                "and opening balances per account. "
                "Large response — prefer `get_summary` for totals and use this "
                "only when item-level detail (IDs, dates, individual entries) is needed. "
                "Pass `sections` to return only part of the month and keep the "
                "response small."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format, e.g. '2025-11' (optional, defaults to current month)",
                    },
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["income", "paidExpenses", "personalExpenses", "pendingExpenses", "notes", "openingBalance"],
                        },
                        "description": "Optional subset of sections to return (default: all sections)",
                    },
                },
                "required": [],
            },
            handler=self._handle_get_month_data,
            read_only=True,
        )

        self._add_tool(
            name="get_account_balances",
            description=(
                "Get the running balance for each account in a given month. "
                "Computed as: opening balance + total income - total expenses "
                "(paid + personal/daily) per account."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format, e.g. '2025-11' (optional, defaults to current month)",
                    }
                },
                "required": [],
            },
            handler=self._handle_get_account_balances,
            read_only=True,
        )

        self._add_tool(
            name="get_last_expense_date",
            description=(
                "Find the most recent expense entry across all months. "
                "Returns the date, month, amount, reason, category, and account "
                "of the latest expense."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=self._handle_get_last_expense_date,
            read_only=True,
        )

        # ── Transaction Management ──────────────────────

        self._add_tool(
            name="manage_expenses",
            description=(
                "Manage expense entries: add regular or daily spends, update an "
                "entry in place, or delete one. "
                "Actions: `add_paid` (needs amount, reason, category, account; "
                "regular non-daily expense), `add_daily` (needs amount, reason, "
                "account; small daily/personal spend, category defaults to "
                "'Personal'), `update` (needs expense_id; only provided fields "
                "change), `delete` (needs expense_id). "
                "Transfer- or debt-linked entries cannot be updated — delete "
                "and re-create them instead. "
                "month_key defaults to the current month; date defaults to today."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add_paid", "add_daily", "update", "delete"],
                        "description": "Which expense operation to perform",
                    },
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format (optional, defaults to current month)",
                    },
                    "expense_id": {
                        "type": "string",
                        "description": "ID of the expense (required for update and delete)",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount in the user's currency (required for add_paid and add_daily)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Description of the expense (required for add_paid and add_daily)",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category name, must exist (required for add_paid)",
                    },
                    "account": {
                        "type": "string",
                        "description": "Account name, must exist (required for add_paid and add_daily)",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format (optional, defaults to today)",
                    },
                },
                "required": ["action"],
            },
            handler=self._handle_manage_expenses,
            read_actions=set(),
        )

        self._add_tool(
            name="manage_income",
            description=(
                "Manage income entries: record a new one, update one in place, "
                "or delete one. "
                "Actions: `add` (needs amount, source, account), `update` "
                "(needs income_id; only provided fields change), `delete` "
                "(needs income_id; a transfer-linked expense is removed too). "
                "Transfer-created entries cannot be updated — delete and "
                "re-create the transfer instead. "
                "month_key defaults to the current month."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "update", "delete"],
                        "description": "Which income operation to perform",
                    },
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format (optional, defaults to current month)",
                    },
                    "income_id": {
                        "type": "string",
                        "description": "ID of the income entry (required for update and delete)",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount in the user's currency (required for add)",
                    },
                    "source": {
                        "type": "string",
                        "description": "Source/description e.g. 'Salary' (required for add)",
                    },
                    "account": {
                        "type": "string",
                        "description": "Account name, must exist (required for add)",
                    },
                },
                "required": ["action"],
            },
            handler=self._handle_manage_income,
            read_actions=set(),
        )

        self._add_tool(
            name="manage_pending",
            description=(
                "Manage the monthly pending / budget list (planned, unpaid expenses). "
                "Actions: `add` (needs amount, reason, category), `list` "
                "(returns all planned items), `delete` (needs item_id; drops "
                "only the plan, never paid expenses). "
                "month_key defaults to the current month."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "list", "delete"],
                        "description": "Which pending-list operation to perform",
                    },
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format (optional, defaults to current month)",
                    },
                    "item_id": {
                        "type": "string",
                        "description": "ID of the pending item (required for delete)",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Planned amount (required for add)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Description of the planned expense (required for add)",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category name (required for add)",
                    },
                },
                "required": ["action"],
            },
            handler=self._handle_manage_pending,
            read_actions={"list"},
        )

        self._add_tool(
            name="transfer_funds",
            description=(
                "Move money between two accounts within the same month. "
                "This creates a linked pair of entries: a paid expense on the "
                "source account and an income on the destination account. "
                "Both entries are tied together so deleting one automatically "
                "removes the other. "
                "month_key defaults to the current month."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format (optional, defaults to current month)",
                    },
                    "from_account": {
                        "type": "string",
                        "description": "Source account name to transfer FROM",
                    },
                    "to_account": {
                        "type": "string",
                        "description": "Destination account name to transfer TO",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount to transfer (positive number)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional reason or note for the transfer (defaults to 'Fund Transfer')",
                    },
                },
                "required": ["from_account", "to_account", "amount"],
            },
            handler=self._handle_transfer_funds,
        )

        self._add_tool(
            name="import_bulk",
            description=(
                "Import transactions in bulk from CSV content. "
                "The CSV should contain sections for paid expenses, "
                "pending expenses, personal expenses, and income. "
                "Remote clients must pass the CSV content via `csv_text`; "
                "`file_path` only works for files already on the server. "
                "Provide exactly one of `csv_text` or `file_path`."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "csv_text": {
                        "type": "string",
                        "description": "Raw CSV content to import (preferred for remote clients)",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to a CSV file already on the server (alternative to csv_text)",
                    },
                    "month_key": {
                        "type": "string",
                        "description": "Target month identifier in YYYY-MM format (optional, defaults to current month)",
                    },
                },
                "required": [],
            },
            handler=self._handle_import_bulk,
        )

        # ── Accounts & Categories ─────────────────────

        self._add_tool(
            name="manage_accounts",
            description=(
                "Manage financial accounts (bank accounts, cash buckets). "
                "Actions: `list` (all accounts), `add` (needs account; creates "
                "a bank/cash/wallet account), `update` (needs old_name and "
                "new_name; renames an account), `set_opening_balance` (needs "
                "account and amount; sets one account's starting balance for "
                "the month, overwriting any previous value; month_key defaults "
                "to the current month)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "update", "set_opening_balance"],
                        "description": "Which account operation to perform",
                    },
                    "account": {
                        "type": "string",
                        "description": "Account name (required for add and set_opening_balance)",
                    },
                    "old_name": {
                        "type": "string",
                        "description": "Current account name (required for update)",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New account name (required for update)",
                    },
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format, for set_opening_balance only (optional, defaults to current month)",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Opening balance amount, may be zero/negative (required for set_opening_balance)",
                    },
                },
                "required": ["action"],
            },
            handler=self._handle_manage_accounts,
            read_actions={"list"},
        )

        self._add_tool(
            name="manage_categories",
            description=(
                "Manage expense/income categories. "
                "Actions: `list` (all categories), `add` (needs category_name), "
                "`update` (needs old_name and new_name; renames a category)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "update"],
                        "description": "Which category operation to perform",
                    },
                    "category_name": {
                        "type": "string",
                        "description": "Name for the new category (required for add)",
                    },
                    "old_name": {
                        "type": "string",
                        "description": "Current category name (required for update)",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New category name (required for update)",
                    },
                },
                "required": ["action"],
            },
            handler=self._handle_manage_categories,
            read_actions={"list"},
        )

        # ── Long Pending (Debts & Loans) ──────────────

        self._add_tool(
            name="manage_debts",
            description=(
                "Manage long-term debts and loans (money owed to others, loans taken). "
                "Actions: `list` (all active debts with remaining balances and "
                "payment status), `add` (needs reason and total_amount; "
                "category defaults to 'General', date defaults to today), "
                "`update` (needs id, reason and total_amount; full replacement, "
                "both overwritten), `delete` (needs id; permanent), `pay` "
                "(needs id, amount and account; records a partial payment, "
                "reduces the remaining balance and creates a paid expense; "
                "month_key defaults to the current month)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "update", "delete", "pay"],
                        "description": "Which debt operation to perform",
                    },
                    "id": {
                        "type": "string",
                        "description": "ID of the debt/loan entry (required for update, delete and pay)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Description of the debt/loan (required for add; part of replacement for update)",
                    },
                    "total_amount": {
                        "type": "number",
                        "description": "Total amount of the loan/debt (required for add; part of replacement for update)",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category for add (optional, defaults to 'General')",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format for add (optional, defaults to today)",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Payment amount (required for pay)",
                    },
                    "account": {
                        "type": "string",
                        "description": "Account the payment is made from (required for pay)",
                    },
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier for the pay expense entry (optional, defaults to current month)",
                    },
                },
                "required": ["action"],
            },
            handler=self._handle_manage_debts,
            read_actions={"list"},
        )

        # ── Notes & Months ────────────────────────────

        self._add_tool(
            name="manage_months",
            description=(
                "Manage tracked months. "
                "Actions: `list` (all months with data), `create` (initializes "
                "a month, optionally carrying pending items forward with "
                "copy_pending; fails if it exists; month defaults to current), "
                "`delete` (deletes a month and all its data — irreversible, "
                "confirm first; month_key is required, never defaulted)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "create", "delete"],
                        "description": "Which month operation to perform",
                    },
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format (optional for create, defaults to current month; required for delete)",
                    },
                    "copy_pending": {
                        "type": "boolean",
                        "description": "For create: copy pending expenses from the previous month",
                    },
                },
                "required": ["action"],
            },
            handler=self._handle_manage_months,
            read_actions={"list"},
        )

        self._add_tool(
            name="manage_notes",
            description=(
                "Manage text notes for a month (context, reminders, explanations). "
                "Actions: `add` (needs title and content), `list` (all notes), "
                "`delete` (needs note_id; permanent). "
                "Notes cannot be edited — delete and re-add to change one. "
                "month_key defaults to the current month."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "list", "delete"],
                        "description": "Which note operation to perform",
                    },
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format (optional, defaults to current month)",
                    },
                    "note_id": {
                        "type": "string",
                        "description": "ID of the note (required for delete)",
                    },
                    "title": {
                        "type": "string",
                        "description": "Title of the note (required for add)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Body of the note (required for add)",
                    },
                },
                "required": ["action"],
            },
            handler=self._handle_manage_notes,
            read_actions={"list"},
        )

        # ── Profile ───────────────────────────────────

        self._add_tool(
            name="manage_profile",
            description=(
                "Manage user profile preferences. "
                "Actions: `get` (name, currency, default account), `update` "
                "(any of name, currency_pref like 'INR'/'USD'/'EUR', "
                "default_account as an account NAME e.g. 'Cash', or "
                "default_account_id as the numeric alternative)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "update"],
                        "description": "Which profile operation to perform",
                    },
                    "name": {
                        "type": "string",
                        "description": "New display name (for update)",
                    },
                    "currency_pref": {
                        "type": "string",
                        "description": "Preferred currency code like 'INR', 'USD', 'EUR' (for update)",
                    },
                    "default_account": {
                        "type": "string",
                        "description": "Account NAME to set as default, e.g. 'Cash' or 'SBI-2390' (for update)",
                    },
                    "default_account_id": {
                        "type": "integer",
                        "description": "Numeric ID of the default account (for update, alternative to default_account)",
                    },
                },
                "required": ["action"],
            },
            handler=self._handle_manage_profile,
            read_actions={"get"},
        )

        # ── API Tokens (PAT self-service) ─────────────

        self._add_tool(
            name="manage_tokens",
            description=(
                "Manage your API tokens for MCP access. "
                "Actions: `list` (active token metadata only — raw values are "
                "never returned), `revoke` (needs pat_id; takes effect "
                "immediately). "
                "Token creation is intentionally unavailable here: new tokens "
                "are created on the API Keys web page, where the show-once "
                "secret can be copied securely."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "revoke"],
                        "description": "Which token operation to perform",
                    },
                    "pat_id": {
                        "type": "string",
                        "description": "ID of the token (required for revoke; find it via list)",
                    },
                },
                "required": ["action"],
            },
            handler=self._handle_manage_tokens,
            read_actions={"list"},
        )

    # ── Registry access ──────────────────────────────

    def get_tool(self, name: str) -> MCPTool | None:
        """Return the tool descriptor by name, or None."""
        return self._tools.get(name)

    def list_tools(self) -> dict:
        """Return the MCP ListToolsResult as a JSON-RPC result."""
        return {"tools": [t.to_dict() for t in self._tools.values()]}

    # ── In-process API (used by agent.py) ────────────

    def call_tool(
        self,
        name: str,
        arguments: dict,
        *,
        user_id: str,
        user_name: str,
        scope: str = "read_write",
    ) -> dict:
        """Invoke a tool directly and return its raw result dict.

        This is the programmatic entry point used by ``agent.py``. The result
        is always a JSON-serializable dict: on success the handler's output,
        on failure a dict containing an ``"error"`` key.
        """
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Tool not found: {name}"}

        if scope == "read":
            if tool.read_actions is not None:
                action = arguments.get("action") if isinstance(arguments, dict) else None
                if action not in tool.read_actions:
                    return {"error": "Read-only token cannot perform this action"}
            elif not tool.read_only:
                return {"error": "Read-only token cannot perform write operations"}

        try:
            return tool.handler(user_id, user_name, **arguments)
        except Exception as e:
            return {"error": f"Tool error: {e}"}

    # ── JSON-RPC 2.0 dispatcher (over-the-wire) ──────

    def dispatch(self, message: dict | list, user_id: str, user_name: str, scope: str) -> list[dict]:
        """Process a JSON-RPC 2.0 message (or batch) and return response(s).

        Supports:
          * batch requests (list of messages)
          * notifications (no ``id`` → no response emitted)
          * ``initialize`` / ``notifications/initialized`` / ``ping``
          * ``tools/list`` / ``tools/call``
          * ``resources/list`` / ``resources/read``
        """
        messages = message if isinstance(message, list) else [message]
        if not messages:
            return [make_jsonrpc_error(INVALID_REQUEST, "Invalid Request: empty batch", None)]

        responses: list[dict] = []
        for msg in messages:
            if not isinstance(msg, dict):
                responses.append(make_jsonrpc_error(INVALID_REQUEST, "Invalid Request", None))
                continue

            resp = self._handle_single(msg, user_id, user_name, scope)
            if resp is not None:
                responses.append(resp)
        return responses

    def _handle_single(self, msg: dict, user_id: str, user_name: str, scope: str) -> dict | None:
        req_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {}) or {}
        notification = _is_notification(msg)

        if method == "initialize":
            if not isinstance(params, dict):
                params = {}
            requested = params.get("protocolVersion", "")
            version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
            result = {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}, "resources": {}},
                "serverInfo": {"name": "mtracker", "version": "1.1.0"},
            }
            return None if notification else make_jsonrpc_result(result, req_id)

        if method in ("notifications/initialized", "notifications/cancelled"):
            return None

        if method == "ping":
            return None if notification else make_jsonrpc_result({}, req_id)

        if method == "tools/list":
            return None if notification else make_jsonrpc_result(self.list_tools(), req_id)

        if method == "tools/call":
            if notification:
                # Tools/call must not be a notification; still process the side effect.
                pass
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            result = self.call_tool(tool_name, arguments, user_id=user_id, user_name=user_name, scope=scope)
            is_error = isinstance(result, dict) and "error" in result
            text = str(result.get("error", json.dumps(result, default=str))) if is_error else json.dumps(result, default=str)
            return make_jsonrpc_result(
                {
                    "content": [{"type": "text", "text": text}],
                    "structuredContent": result,
                    "isError": is_error,
                },
                req_id,
            )

        if method == "resources/list":
            return None if notification else make_jsonrpc_result(self._list_resources(user_id), req_id)

        if method == "resources/read":
            uri = params.get("uri", "")
            return None if notification else make_jsonrpc_result(self._read_resource(user_id, uri), req_id)

        if method in ("completion/complete", "logging/setLevel", "prompts/list", "prompts/get"):
            return make_jsonrpc_error(METHOD_NOT_FOUND, f"Unknown method: {method}", req_id)

        return None if notification else make_jsonrpc_error(METHOD_NOT_FOUND, f"Unknown method: {method}", req_id)

    # ── Resources ─────────────────────────────────────

    def _list_resources(self, user_id: str) -> dict:
        resources = [
            {"uri": "mtracker://accounts", "name": "Accounts", "description": "Configured bank accounts and cash buckets", "mimeType": "application/json"},
            {"uri": "mtracker://categories", "name": "Categories", "description": "Active expense and income categories", "mimeType": "application/json"},
            {"uri": "mtracker://debts/active", "name": "Active Debts", "description": "All outstanding loans and dues", "mimeType": "application/json"},
            {"uri": "mtracker://schema", "name": "Schema", "description": "Structural information about MTracker data storage", "mimeType": "application/json"},
        ]
        return {"resources": resources}

    def _read_resource(self, user_id: str, uri: str) -> dict:
        if uri == "mtracker://accounts":
            accounts = self.db.get_accounts(user_id)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(accounts, default=str)}]}

        if uri == "mtracker://categories":
            categories = self.db.get_categories(user_id)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(categories, default=str)}]}

        if uri == "mtracker://debts/active":
            debts = self.db.get_long_pending(user_id)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(debts, default=str)}]}

        if uri == "mtracker://schema":
            schema = {
                "tables": {
                    "months": {"columns": ["id", "user_id", "month_key"], "description": "Monthly period container"},
                    "income": {"columns": ["id", "user_id", "month_id", "account_id", "source", "amount", "notes"], "description": "Income entries per month"},
                    "paid_expenses": {"columns": ["id", "user_id", "month_id", "account_id", "category_id", "reason", "amount", "expense_date", "is_daily_log", "is_long_pending", "notes"], "description": "Completed expenses (both regular and personal/daily)"},
                    "pending_expenses": {"columns": ["id", "user_id", "month_id", "category_id", "reason", "amount", "payment_mode", "status"], "description": "Planned/pending budget items"},
                    "opening_balances": {"columns": ["id", "user_id", "month_id", "account_id", "amount"], "description": "Opening balance per account per month"},
                    "notes": {"columns": ["id", "user_id", "month_id", "title", "content", "note_date"], "description": "Monthly notes"},
                    "long_pending": {"columns": ["id", "user_id", "reason", "total_amount", "paid_amount", "remaining_amount", "category", "created_date", "status"], "description": "Long-term debts and loans"},
                    "categories": {"columns": ["id", "user_id", "category_name", "is_active"], "description": "Expense/income categories"},
                    "accounts": {"columns": ["id", "user_id", "account_name", "account_type", "is_active"], "description": "Financial accounts"},
                    "users": {"columns": ["id", "name", "email", "phone", "currency_pref", "default_account_id"], "description": "User profiles"},
                }
            }
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(schema, default=str)}]}

        return {"contents": []}

    # ── Shared helpers ────────────────────────────────

    def _audit(self, user_id: str, action: str, table: str, record_id: str, details: dict = None):
        """Write an audit log entry for MCP actions."""
        try:
            self.db.log_audit(user_id, action, table, record_id, details, origin='mcp')
        except Exception:
            pass  # Audit failures must never break the main flow

    @staticmethod
    def _resolve_month(month_key: str | None) -> str:
        """Default an omitted month to the current month (YYYY-MM)."""
        return month_key or datetime.now().strftime("%Y-%m")

    def _read_month_and_append(self, user_id: str, month_key: str) -> dict | None:
        """Read current month data, ensuring expected arrays exist. Returns None if month doesn't exist."""
        data = self.db.get_month_data(user_id, month_key)
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

    def _save_month(self, user_id: str, month_key: str, data: dict) -> bool:
        """Persist month data via the full-state sync."""
        return self.db.save_month_data(user_id, month_key, data)

    def _get_account_map(self, user_id: str) -> dict:
        """Return {account_name: account_id} lookup."""
        accounts = self.db.get_accounts(user_id)
        return {a["account_name"]: a["id"] for a in accounts}

    # ── Tool handlers ─────────────────────────────────

    def _handle_get_summary(self, user_id: str, user_name: str, month_key: str = None) -> dict:
        """Compute a high-level financial summary for a month."""
        month_key = self._resolve_month(month_key)
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        total_income = sum(float(i["amount"]) for i in data["income"])
        total_paid = sum(float(e["amount"]) for e in data["paidExpenses"])
        total_personal = sum(float(e["amount"]) for e in data["personalExpenses"])
        total_expenses = total_paid + total_personal
        ob = data.get("openingBalance", {})
        total_opening = sum(float(v) for v in ob.values()) if isinstance(ob, dict) else float(ob or 0)

        return {
            "month_key": month_key,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "total_paid_expenses": total_paid,
            "total_personal_expenses": total_personal,
            "opening_balance": total_opening,
            "net_balance": total_opening + total_income - total_expenses,
            "transaction_count": len(data["paidExpenses"]) + len(data["personalExpenses"]),
            "pending_count": len(data["pendingExpenses"]),
            "note_count": len(data["notes"]),
        }

    _MONTH_SECTIONS = ("income", "paidExpenses", "personalExpenses", "pendingExpenses", "notes", "openingBalance")

    def _handle_get_month_data(self, user_id: str, user_name: str, month_key: str = None, sections: list = None) -> dict:
        """Return the full (or section-filtered) state of a month."""
        month_key = self._resolve_month(month_key)
        data = self.db.get_month_data(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}
        if sections is None:
            return data
        if isinstance(sections, str):
            sections = [sections]
        if not isinstance(sections, list) or not sections:
            return {"error": f"Sections must be a non-empty list of: {', '.join(self._MONTH_SECTIONS)}."}
        unknown = [s for s in sections if s not in self._MONTH_SECTIONS]
        if unknown:
            return {"error": f"Unknown section(s): {', '.join(unknown)}. Allowed: {', '.join(self._MONTH_SECTIONS)}."}
        return {k: data.get(k) for k in sections}

    def _handle_get_account_balances(self, user_id: str, user_name: str, month_key: str = None) -> dict:
        """Compute the running balance for each account in a given month."""
        month_key = self._resolve_month(month_key)
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        ob = data.get("openingBalance", {})
        if not isinstance(ob, dict):
            ob = {}

        account_income: dict[str, float] = {}
        for inc in data["income"]:
            acct = inc.get("account", "Cash")
            account_income[acct] = account_income.get(acct, 0) + float(inc["amount"])

        account_expense: dict[str, float] = {}
        for exp in data["paidExpenses"]:
            acct = exp.get("account", "Cash")
            account_expense[acct] = account_expense.get(acct, 0) + float(exp["amount"])
        for exp in data["personalExpenses"]:
            acct = exp.get("account", "Cash")
            account_expense[acct] = account_expense.get(acct, 0) + float(exp["amount"])

        all_accounts = set(list(ob.keys()) + list(account_income.keys()) + list(account_expense.keys()))
        if not all_accounts:
            return {"error": f"No account data for {month_key}."}

        balances = []
        for acct in sorted(all_accounts):
            op = float(ob.get(acct, 0))
            inc = account_income.get(acct, 0)
            exp = account_expense.get(acct, 0)
            balances.append({
                "account": acct,
                "opening_balance": op,
                "income": inc,
                "expenses": exp,
                "balance": op + inc - exp,
            })

        return {"month_key": month_key, "balances": balances}

    def _handle_get_last_expense_date(self, user_id: str, user_name: str) -> dict:
        """Find the most recent expense entry across all months, with details."""
        months = self.db.get_months(user_id)
        if not months:
            return {"error": "No months found. No expenses recorded yet."}

        months.sort(reverse=True)
        latest = None
        latest_month = None
        latest_expense = None
        for m in months:
            data = self.db.get_month_data(user_id, m)
            if data is None:
                continue
            all_expenses = data.get("paidExpenses", []) + data.get("personalExpenses", [])
            for e in all_expenses:
                d = e.get("date", "")
                if d and (latest is None or d > latest):
                    latest = d
                    latest_month = m
                    latest_expense = e

        if latest is None:
            return {"error": "No expenses found in any month."}

        return {
            "last_expense_date": latest,
            "month_key": latest_month,
            "amount": float(latest_expense.get("amount", 0)),
            "reason": latest_expense.get("reason"),
            "category": latest_expense.get("category"),
            "account": latest_expense.get("account"),
        }

    def _handle_add_paid_expense(self, user_id: str, user_name: str, month_key: str, amount: float, reason: str, category: str, account: str, date: str = None) -> dict:
        """Record a completed transaction by appending to the month's paid expenses."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        cats = self.db.get_categories(user_id)
        if category not in cats:
            return {"error": f"Category '{category}' not found. Available: {', '.join(cats)}"}

        accs = self._get_account_map(user_id)
        if account not in accs:
            return {"error": f"Account '{account}' not found."}

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

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "INSERT", "paid_expenses", item["id"], {"month_key": month_key, "reason": reason, "amount": amount})
            return {"status": "success", "id": item["id"], "message": f"Expense '{reason}' ({amount}) recorded."}
        return {"error": "Failed to save expense."}

    def _handle_add_income(self, user_id: str, user_name: str, month_key: str, amount: float, source: str, account: str) -> dict:
        """Record a new income entry."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        accs = self._get_account_map(user_id)
        if account not in accs:
            return {"error": f"Account '{account}' not found."}

        item = {
            "id": str(datetime.now().timestamp()),
            "source": source,
            "account": account,
            "amount": float(amount),
            "notes": None,
        }
        data["income"].append(item)

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "INSERT", "income", item["id"], {"month_key": month_key, "source": source, "amount": amount})
            return {"status": "success", "id": item["id"], "message": f"Income '{source}' ({amount}) recorded."}
        return {"error": "Failed to save income."}

    def _handle_add_pending_item(self, user_id: str, user_name: str, month_key: str, amount: float, reason: str, category: str) -> dict:
        """Add an item to the monthly pending/budget list."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        cats = self.db.get_categories(user_id)
        if category not in cats:
            return {"error": f"Category '{category}' not found. Available: {', '.join(cats)}"}

        item = {
            "id": str(datetime.now().timestamp()),
            "reason": reason,
            "category": category,
            "amount": float(amount),
            "mode": "online",
        }
        data["pendingExpenses"].append(item)

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "INSERT", "pending_expenses", item["id"], {"month_key": month_key, "reason": reason, "amount": amount})
            return {"status": "success", "id": item["id"], "message": f"Pending item '{reason}' ({amount}) added."}
        return {"error": "Failed to save pending item."}

    def _handle_transfer_funds(self, user_id: str, user_name: str, month_key: str, from_account: str, to_account: str, amount: float, reason: str = None) -> dict:
        """Move money between accounts using linked expense + income entries."""
        month_key = self._resolve_month(month_key)
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        accs = self._get_account_map(user_id)
        if from_account not in accs:
            return {"error": f"Source account '{from_account}' not found."}
        if to_account not in accs:
            return {"error": f"Destination account '{to_account}' not found."}
        if from_account == to_account:
            return {"error": "Source and destination accounts must differ."}

        # Ensure a "Transfer" category exists
        cats = self.db.get_categories(user_id)
        if "Transfer" not in cats:
            self.db.add_category(user_id, "Transfer")

        reason = reason or "Fund Transfer"
        transfer_ref = str(datetime.now().timestamp())

        expense_item = {
            "id": str(datetime.now().timestamp() + 1),
            "reason": f"{reason} (to {to_account})",
            "category": "Transfer",
            "account": from_account,
            "amount": float(amount),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "notes": f"__transfer__:{transfer_ref}",
        }

        income_item = {
            "id": str(datetime.now().timestamp() + 2),
            "source": f"{reason} (from {from_account})",
            "account": to_account,
            "amount": float(amount),
            "notes": f"__transfer__:{transfer_ref}",
        }

        data["paidExpenses"].append(expense_item)
        data["income"].append(income_item)

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "INSERT", "paid_expenses", expense_item["id"], {"month_key": month_key, "transfer": True, "from": from_account, "to": to_account, "amount": amount})
            self._audit(user_id, "INSERT", "income", income_item["id"], {"month_key": month_key, "transfer": True, "from": from_account, "to": to_account, "amount": amount})
            return {
                "status": "success",
                "transfer_ref": transfer_ref,
                "expense_id": expense_item["id"],
                "income_id": income_item["id"],
                "message": f"Transferred {amount} from {from_account} to {to_account}.",
            }
        return {"error": "Failed to process transfer."}

    def _handle_delete_expense(self, user_id: str, user_name: str, month_key: str, expense_id: str) -> dict:
        """Remove an expense using the DB's cascade-aware delete method."""
        if self.db.delete_expense(user_id, month_key, expense_id):
            self._audit(user_id, "DELETE", "paid_expenses", expense_id, {"month_key": month_key})
            return {"status": "success", "message": "Expense deleted."}
        return {"error": "Expense not found or could not be deleted."}

    def _handle_import_bulk(self, user_id: str, user_name: str, month_key: str = None, csv_text: str = None, file_path: str = None) -> dict:
        """Import transactions from CSV content or a server-side CSV file."""
        month_key = self._resolve_month(month_key)
        import csv
        import io
        import os

        if csv_text:
            content = csv_text
        elif file_path:
            if not os.path.isfile(file_path):
                return {"error": f"File not found: {file_path}"}
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                return {"error": f"Could not read file: {e}"}
        else:
            return {"error": "Provide either csv_text (CSV content) or file_path (server-side path)."}

        stream = io.StringIO(content, newline=None)
        csv_input = csv.reader(stream)
        rows = list(csv_input)

        paid_expenses = []
        pending_expenses = []
        personal_expenses = []
        income = 0
        opening_balance = 0
        section = None

        for i, row in enumerate(rows):
            clean_row = [str(cell).strip() for cell in row]
            first_cell = clean_row[0] if len(clean_row) > 0 else ""

            if "TOTAL EXPENSE LIST" in first_cell or "PAYMENT REASON" in first_cell:
                section = "paid"
                continue
            if "PENDING" in first_cell:
                section = "pending"
                continue
            if "Personal Expenses" in first_cell:
                section = "personal"
                continue

            for col_idx, cell in enumerate(clean_row):
                if "INCOME IN CURRENT MONTH" in str(cell):
                    try:
                        income = float(clean_row[col_idx + 1].replace(",", ""))
                    except Exception:
                        pass
                if "AVAILABLE FROM PREVIOUS MONTH" in str(cell):
                    try:
                        opening_balance = float(clean_row[col_idx + 1].replace(",", ""))
                    except Exception:
                        pass

            if first_cell in ["PAYMENT REASON", "Type", ""]:
                continue

            try:
                if section == "paid" and len(clean_row) >= 4 and clean_row[3]:
                    amt = float(clean_row[3].replace(",", ""))
                    if amt > 0:
                        paid_expenses.append({
                            "id": str(datetime.now().timestamp()) + str(i),
                            "reason": clean_row[0],
                            "category": clean_row[1],
                            "date": clean_row[2],
                            "amount": amt,
                            "mode": "Online",
                        })
                elif section == "pending" and len(clean_row) >= 4 and clean_row[3]:
                    amt = float(clean_row[3].replace(",", ""))
                    pending_expenses.append({
                        "id": str(datetime.now().timestamp()) + str(i),
                        "reason": clean_row[0],
                        "category": clean_row[1],
                        "amount": amt,
                        "mode": clean_row[2],
                    })
                elif section == "personal":
                    non_empty = [c for c in clean_row if c]
                    if len(non_empty) >= 2:
                        amt = float(non_empty[-1].replace(",", ""))
                        personal_expenses.append({
                            "id": str(datetime.now().timestamp()) + str(i),
                            "reason": non_empty[0],
                            "date": "",
                            "amount": amt,
                        })
            except (ValueError, IndexError):
                continue

        month_data = {
            "income": [{"id": "csv-import", "source": "CSV Import", "amount": income, "account": "Cash"}],
            "openingBalance": {"Cash": opening_balance},
            "paidExpenses": paid_expenses,
            "pendingExpenses": pending_expenses,
            "personalExpenses": personal_expenses,
        }

        if self.db.sync_bulk_data(user_id, month_key, month_data):
            total = len(paid_expenses) + len(pending_expenses) + len(personal_expenses)
            self._audit(user_id, "INSERT", "multiple", file_path, {"month_key": month_key, "items_imported": total})
            return {"status": "success", "items_imported": total, "message": f"Imported {total} items from CSV."}
        return {"error": "Failed to import CSV data."}

    def _handle_list_accounts(self, user_id: str, user_name: str) -> list:
        """Fetch all financial accounts (bank accounts, cash buckets) configured by the user."""
        return self.db.get_accounts(user_id)

    def _handle_add_account(self, user_id: str, user_name: str, account_name: str) -> dict:
        """Create a new financial account (bank, cash, wallet, etc.)."""
        if self.db.add_account(user_id, account_name):
            self._audit(user_id, "INSERT", "accounts", account_name)
            return {"status": "success", "message": f"Account '{account_name}' created."}
        return {"error": f"Could not create account '{account_name}'. It may already exist."}

    def _handle_update_account(self, user_id: str, user_name: str, old_name: str, new_name: str) -> dict:
        """Rename an existing financial account."""
        if self.db.update_account(user_id, old_name, new_name):
            self._audit(user_id, "UPDATE", "accounts", old_name, {"new_name": new_name})
            return {"status": "success", "message": f"Account renamed from '{old_name}' to '{new_name}'."}
        return {"error": f"Could not rename account. '{old_name}' may not exist."}

    def _handle_list_categories(self, user_id: str, user_name: str) -> list:
        """Fetch all expense and income categories configured by the user."""
        return self.db.get_categories(user_id)

    def _handle_add_category(self, user_id: str, user_name: str, category_name: str) -> dict:
        """Create a new expense/income category."""
        if self.db.add_category(user_id, category_name):
            self._audit(user_id, "INSERT", "categories", category_name)
            return {"status": "success", "message": f"Category '{category_name}' created."}
        return {"error": f"Could not create category '{category_name}'. It may already exist."}

    def _handle_update_category(self, user_id: str, user_name: str, old_name: str, new_name: str) -> dict:
        """Rename an existing expense/income category."""
        if self.db.update_category(user_id, old_name, new_name):
            self._audit(user_id, "UPDATE", "categories", old_name, {"new_name": new_name})
            return {"status": "success", "message": f"Category renamed from '{old_name}' to '{new_name}'."}
        return {"error": f"Could not rename category. '{old_name}' may not exist."}

    def _handle_list_long_pending(self, user_id: str, user_name: str) -> list:
        """Fetch all active long-term debts and loans with remaining balances."""
        return self.db.get_long_pending(user_id)

    def _handle_add_long_pending(self, user_id: str, user_name: str, reason: str, total_amount: float, category: str = "General", date: str = None) -> dict:
        """Create a new long-term debt or loan entry."""
        item_data = {
            "id": str(datetime.now().timestamp()),
            "reason": reason,
            "totalAmount": float(total_amount),
            "paidAmount": 0,
            "category": category,
            "createdDate": date or datetime.now().strftime("%Y-%m-%d"),
        }
        if self.db.add_long_pending(user_id, item_data):
            self._audit(user_id, "INSERT", "long_pending", item_data["id"], {"reason": reason, "total_amount": total_amount})
            return {"status": "success", "id": item_data["id"], "message": f"Debt '{reason}' ({total_amount}) recorded."}
        return {"error": "Failed to create debt entry."}

    def _handle_update_long_pending(self, user_id: str, user_name: str, id: str, reason: str, total_amount: float) -> dict:
        """Update a long-term debt or loan entry (full replacement of reason and total)."""
        item_data = {"id": id, "reason": reason, "totalAmount": float(total_amount), "category": None}
        if self.db.update_long_pending(user_id, item_data):
            self._audit(user_id, "UPDATE", "long_pending", id, {"reason": reason, "total_amount": total_amount})
            return {"status": "success", "message": "Debt entry updated."}
        return {"error": "Debt entry not found or could not be updated."}

    def _handle_delete_long_pending(self, user_id: str, user_name: str, id: str) -> dict:
        """Permanently remove a long-term debt or loan record."""
        if self.db.delete_long_pending(user_id, id):
            self._audit(user_id, "DELETE", "long_pending", id)
            return {"status": "success", "message": "Debt entry deleted."}
        return {"error": "Debt entry not found."}

    def _handle_pay_long_pending(self, user_id: str, user_name: str, item_id: str, amount: float, account: str, month_key: str) -> dict:
        """Record a partial payment towards a long-term debt (reduces balance + creates expense)."""
        if self.db.make_partial_payment(user_id, item_id, month_key, float(amount), account, "Online"):
            self._audit(user_id, "UPDATE", "long_pending", item_id, {"payment_amount": amount, "month_key": month_key, "account": account})
            return {"status": "success", "message": f"Payment of {amount} recorded towards debt."}
        return {"error": "Could not process payment. Check that the item ID and account are valid."}

    def _handle_list_months(self, user_id: str, user_name: str) -> list:
        """Get a list of all months that have financial data recorded."""
        return self.db.get_months(user_id)

    def _handle_create_month(self, user_id: str, user_name: str, month_key: str, copy_pending: bool = False) -> dict:
        """Initialize a new month, optionally carrying pending items forward."""
        result = self.db.create_month(user_id, month_key, copy_pending)
        if result:
            self._audit(user_id, "INSERT", "months", month_key, {"copy_pending": copy_pending})
            return {"status": "success", "message": f"Month {month_key} initialized.", "data": result}
        return {"error": f"Could not create month {month_key}. It may already exist."}

    def _handle_delete_month(self, user_id: str, user_name: str, month_key: str) -> dict:
        """Delete an entire month and all its financial data (irreversible)."""
        if self.db.delete_month(user_id, month_key):
            self._audit(user_id, "DELETE", "months", month_key)
            return {"status": "success", "message": f"Month {month_key} deleted."}
        return {"error": f"Could not delete month {month_key}."}

    def _handle_add_note(self, user_id: str, user_name: str, month_key: str, title: str, content: str) -> dict:
        """Save a text note for a specific month."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        item = {
            "id": str(datetime.now().timestamp()),
            "title": title,
            "content": content,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        data["notes"].append(item)

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "INSERT", "notes", item["id"], {"month_key": month_key, "title": title})
            return {"status": "success", "id": item["id"], "message": f"Note '{title}' saved."}
        return {"error": "Failed to save note."}

    def _handle_get_profile(self, user_id: str, user_name: str) -> dict:
        """Get the user's profile settings (name, currency, default account)."""
        user = self.db.get_user_by_id(user_id)
        if not user:
            return {"error": "User not found."}
        return {
            "name": user.get("name"),
            "email": user.get("email"),
            "phone": user.get("phone"),
            "currency_pref": user.get("currency_pref", "INR"),
            "default_account_id": user.get("default_account_id"),
        }

    def _handle_update_profile(self, user_id: str, user_name: str, name: str = None, currency_pref: str = None, default_account: str = None, default_account_id: int = None) -> dict:
        """Update user profile preferences (name, currency, default account by NAME or ID)."""
        kwargs = {}
        if name is not None:
            kwargs["name"] = name
        if currency_pref is not None:
            kwargs["currency_pref"] = currency_pref
        if default_account is not None:
            account_id = self._get_account_map(user_id).get(default_account)
            if account_id is None:
                accounts = self.db.get_accounts(user_id)
                available = ", ".join(a["account_name"] for a in accounts) if accounts else "none"
                return {"error": f"Account '{default_account}' not found. Available accounts: {available}"}
            kwargs["default_account_id"] = account_id
        elif default_account_id is not None:
            kwargs["default_account_id"] = default_account_id

        if not kwargs:
            return {"status": "success", "message": "No changes requested."}

        if self.db.update_user(user_id, **kwargs):
            self._audit(user_id, "UPDATE", "users", user_id, kwargs)
            return {"status": "success", "message": "Profile updated."}
        return {"error": "Failed to update profile."}

    # ── New handlers: full CRUD coverage ────────────────

    @staticmethod
    def _is_linked(item: dict) -> str | None:
        """Detect transfer- or debt-linked entries that must not be edited in place.

        Returns a human-readable link description, or None when the entry is
        a plain standalone record that is safe to update.
        """
        notes = item.get("notes") or ""
        if isinstance(notes, str) and notes.startswith("__transfer__:"):
            return "a fund transfer"
        if item.get("is_long_pending") or item.get("linkedId") or item.get("isLongPending") or item.get("linked_long_pending_id"):
            return "a long-pending debt payment"
        return None

    def _handle_add_daily_expense(self, user_id: str, user_name: str, month_key: str, amount: float, reason: str, account: str, category: str = "Personal", date: str = None) -> dict:
        """Record a small daily/personal spend as a daily-log entry."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        accs = self._get_account_map(user_id)
        if account not in accs:
            return {"error": f"Account '{account}' not found."}

        item = {
            "id": str(datetime.now().timestamp()),
            "reason": reason,
            "category": category or "Personal",
            "account": account,
            "amount": float(amount),
            "date": date or datetime.now().strftime("%Y-%m-%d"),
        }
        data["personalExpenses"].append(item)

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "INSERT", "paid_expenses", item["id"], {"month_key": month_key, "reason": reason, "amount": amount, "daily": True})
            return {"status": "success", "id": item["id"], "message": f"Daily spend '{reason}' ({amount}) recorded."}
        return {"error": "Failed to save daily expense."}

    def _handle_set_opening_balance(self, user_id: str, user_name: str, month_key: str, account: str, amount: float) -> dict:
        """Set the opening balance for one account in a month."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        accs = self._get_account_map(user_id)
        if account not in accs:
            return {"error": f"Account '{account}' not found."}

        data["openingBalance"][account] = float(amount)

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "UPDATE", "opening_balances", account, {"month_key": month_key, "amount": amount})
            return {"status": "success", "message": f"Opening balance for '{account}' set to {amount}.", "opening_balances": data["openingBalance"]}
        return {"error": "Failed to save opening balance."}

    def _handle_list_pending_items(self, user_id: str, user_name: str, month_key: str) -> list:
        """List all planned/pending budget items for a month."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}
        return data["pendingExpenses"]

    def _handle_delete_pending_item(self, user_id: str, user_name: str, month_key: str, item_id: str) -> dict:
        """Remove a planned/pending budget item from a month."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        before = len(data["pendingExpenses"])
        data["pendingExpenses"] = [i for i in data["pendingExpenses"] if str(i.get("id")) != str(item_id)]
        if len(data["pendingExpenses"]) == before:
            return {"error": "Pending item not found."}

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "DELETE", "pending_expenses", item_id, {"month_key": month_key})
            return {"status": "success", "message": "Pending item deleted."}
        return {"error": "Failed to delete pending item."}

    def _handle_update_expense(self, user_id: str, user_name: str, month_key: str, expense_id: str, amount: float = None, reason: str = None, category: str = None, account: str = None, date: str = None) -> dict:
        """Update amount/reason/category/account/date of an expense in place."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        target = None
        for exp in data["paidExpenses"] + data["personalExpenses"]:
            if str(exp.get("id")) == str(expense_id):
                target = exp
                break
        if target is None:
            return {"error": "Expense not found."}

        link = self._is_linked(target)
        if link:
            return {"error": f"This expense is linked to {link} and cannot be edited. Delete it and re-create instead."}

        if category is not None:
            cats = self.db.get_categories(user_id)
            if category not in cats:
                return {"error": f"Category '{category}' not found. Available: {', '.join(cats)}"}
            target["category"] = category
        if account is not None:
            accs = self._get_account_map(user_id)
            if account not in accs:
                return {"error": f"Account '{account}' not found."}
            target["account"] = account
        if amount is not None:
            target["amount"] = float(amount)
        if reason is not None:
            target["reason"] = reason
        if date is not None:
            target["date"] = date

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "UPDATE", "paid_expenses", expense_id, {"month_key": month_key})
            return {"status": "success", "message": "Expense updated."}
        return {"error": "Failed to update expense."}

    def _handle_update_income(self, user_id: str, user_name: str, month_key: str, income_id: str, amount: float = None, source: str = None, account: str = None) -> dict:
        """Update amount/source/account of an income entry in place."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        target = None
        for inc in data["income"]:
            if str(inc.get("id")) == str(income_id):
                target = inc
                break
        if target is None:
            return {"error": "Income entry not found."}

        link = self._is_linked(target)
        if link:
            return {"error": f"This income is linked to {link} and cannot be edited. Delete it and re-create instead."}

        if account is not None:
            accs = self._get_account_map(user_id)
            if account not in accs:
                return {"error": f"Account '{account}' not found."}
            target["account"] = account
        if amount is not None:
            target["amount"] = float(amount)
        if source is not None:
            target["source"] = source

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "UPDATE", "income", income_id, {"month_key": month_key})
            return {"status": "success", "message": "Income entry updated."}
        return {"error": "Failed to update income entry."}

    def _handle_delete_income(self, user_id: str, user_name: str, month_key: str, income_id: str) -> dict:
        """Remove an income entry, cascading to a linked transfer expense."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        target = None
        for inc in data["income"]:
            if str(inc.get("id")) == str(income_id):
                target = inc
                break
        if target is None:
            return {"error": "Income entry not found."}

        cascaded = False
        notes = target.get("notes") or ""
        if isinstance(notes, str) and notes.startswith("__transfer__:"):
            ref = notes.split(":", 1)[1]
            before = len(data["paidExpenses"])
            data["paidExpenses"] = [e for e in data["paidExpenses"] if (e.get("notes") or "") != f"__transfer__:{ref}"]
            cascaded = len(data["paidExpenses"]) != before

        data["income"] = [i for i in data["income"] if str(i.get("id")) != str(income_id)]

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "DELETE", "income", income_id, {"month_key": month_key, "cascaded": cascaded})
            msg = "Income entry deleted."
            if cascaded:
                msg += " The linked transfer expense was removed as well."
            return {"status": "success", "message": msg}
        return {"error": "Failed to delete income entry."}

    def _handle_list_notes(self, user_id: str, user_name: str, month_key: str) -> list:
        """List all text notes for a month."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}
        return data["notes"]

    def _handle_delete_note(self, user_id: str, user_name: str, month_key: str, note_id: str) -> dict:
        """Permanently remove a text note from a month."""
        data = self._read_month_and_append(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}

        before = len(data["notes"])
        data["notes"] = [n for n in data["notes"] if str(n.get("id")) != str(note_id)]
        if len(data["notes"]) == before:
            return {"error": "Note not found."}

        if self._save_month(user_id, month_key, data):
            self._audit(user_id, "DELETE", "notes", note_id, {"month_key": month_key})
            return {"status": "success", "message": "Note deleted."}
        return {"error": "Failed to delete note."}

    def _handle_list_pats(self, user_id: str, user_name: str) -> list:
        """List active API tokens (metadata only)."""
        return self.db.list_pats(user_id)

    def _handle_revoke_pat(self, user_id: str, user_name: str, pat_id: str) -> dict:
        """Revoke an API token with immediate effect."""
        if self.db.revoke_pat(user_id, pat_id):
            self._audit(user_id, "DELETE", "personal_access_tokens", pat_id)
            return {"status": "success", "message": "Token revoked."}
        return {"error": "Token not found."}

    # ── Grouped dispatchers (each delegates to the handlers above) ──

    @staticmethod
    def _need(kwargs: dict, *fields) -> str | None:
        """Return an error message if any listed field is missing/None, else None."""
        missing = [f for f in fields if kwargs.get(f) is None]
        if missing:
            return f"Missing required field(s) for this action: {', '.join(missing)}."
        return None

    def _handle_manage_expenses(self, user_id: str, user_name: str, action: str, month_key: str = None, expense_id: str = None, amount: float = None, reason: str = None, category: str = None, account: str = None, date: str = None) -> dict:
        """Route an expense job (paid/daily add, update, delete) to its handler."""
        month_key = self._resolve_month(month_key)
        if action == "add_paid":
            err = self._need(locals(), "amount", "reason", "category", "account")
            if err:
                return {"error": err}
            return self._handle_add_paid_expense(user_id, user_name, month_key, amount, reason, category, account, date)
        if action == "add_daily":
            err = self._need(locals(), "amount", "reason", "account")
            if err:
                return {"error": err}
            return self._handle_add_daily_expense(user_id, user_name, month_key, amount, reason, account, category or "Personal", date)
        if action == "update":
            err = self._need(locals(), "expense_id")
            if err:
                return {"error": err}
            return self._handle_update_expense(user_id, user_name, month_key, expense_id, amount, reason, category, account, date)
        if action == "delete":
            err = self._need(locals(), "expense_id")
            if err:
                return {"error": err}
            data = self._read_month_and_append(user_id, month_key)
            if data is None:
                return {"error": f"Month {month_key} not found. Use manage_months(create) first."}
            found = any(str(e.get("id")) == str(expense_id) for e in data["paidExpenses"] + data["personalExpenses"])
            if not found:
                return {"error": "Expense not found."}
            return self._handle_delete_expense(user_id, user_name, month_key, expense_id)
        return {"error": f"Unknown action '{action}'. Valid: add_paid, add_daily, update, delete."}

    def _handle_manage_income(self, user_id: str, user_name: str, action: str, month_key: str = None, income_id: str = None, amount: float = None, source: str = None, account: str = None) -> dict:
        """Route an income job (add, update, delete) to its handler."""
        month_key = self._resolve_month(month_key)
        if action == "add":
            err = self._need(locals(), "amount", "source", "account")
            if err:
                return {"error": err}
            return self._handle_add_income(user_id, user_name, month_key, amount, source, account)
        if action == "update":
            err = self._need(locals(), "income_id")
            if err:
                return {"error": err}
            return self._handle_update_income(user_id, user_name, month_key, income_id, amount, source, account)
        if action == "delete":
            err = self._need(locals(), "income_id")
            if err:
                return {"error": err}
            return self._handle_delete_income(user_id, user_name, month_key, income_id)
        return {"error": f"Unknown action '{action}'. Valid: add, update, delete."}

    def _handle_manage_pending(self, user_id: str, user_name: str, action: str, month_key: str = None, item_id: str = None, amount: float = None, reason: str = None, category: str = None) -> dict:
        """Route a pending-budget job (add, list, delete) to its handler."""
        month_key = self._resolve_month(month_key)
        if action == "add":
            err = self._need(locals(), "amount", "reason", "category")
            if err:
                return {"error": err}
            return self._handle_add_pending_item(user_id, user_name, month_key, amount, reason, category)
        if action == "list":
            return self._handle_list_pending_items(user_id, user_name, month_key)
        if action == "delete":
            err = self._need(locals(), "item_id")
            if err:
                return {"error": err}
            return self._handle_delete_pending_item(user_id, user_name, month_key, item_id)
        return {"error": f"Unknown action '{action}'. Valid: add, list, delete."}

    def _handle_manage_accounts(self, user_id: str, user_name: str, action: str, account: str = None, old_name: str = None, new_name: str = None, month_key: str = None, amount: float = None) -> dict:
        """Route an account job (list, add, update, set_opening_balance) to its handler."""
        if action == "list":
            return self._handle_list_accounts(user_id, user_name)
        if action == "add":
            err = self._need(locals(), "account")
            if err:
                return {"error": err}
            return self._handle_add_account(user_id, user_name, account)
        if action == "update":
            err = self._need(locals(), "old_name", "new_name")
            if err:
                return {"error": err}
            return self._handle_update_account(user_id, user_name, old_name, new_name)
        if action == "set_opening_balance":
            err = self._need(locals(), "account", "amount")
            if err:
                return {"error": err}
            return self._handle_set_opening_balance(user_id, user_name, self._resolve_month(month_key), account, amount)
        return {"error": f"Unknown action '{action}'. Valid: list, add, update, set_opening_balance."}

    def _handle_manage_categories(self, user_id: str, user_name: str, action: str, category_name: str = None, old_name: str = None, new_name: str = None) -> dict:
        """Route a category job (list, add, update) to its handler."""
        if action == "list":
            return self._handle_list_categories(user_id, user_name)
        if action == "add":
            err = self._need(locals(), "category_name")
            if err:
                return {"error": err}
            return self._handle_add_category(user_id, user_name, category_name)
        if action == "update":
            err = self._need(locals(), "old_name", "new_name")
            if err:
                return {"error": err}
            return self._handle_update_category(user_id, user_name, old_name, new_name)
        return {"error": f"Unknown action '{action}'. Valid: list, add, update."}

    def _handle_manage_debts(self, user_id: str, user_name: str, action: str, id: str = None, reason: str = None, total_amount: float = None, category: str = None, date: str = None, amount: float = None, account: str = None, month_key: str = None) -> dict:
        """Route a debt/loan job (list, add, update, delete, pay) to its handler."""
        if action == "list":
            return self._handle_list_long_pending(user_id, user_name)
        if action == "add":
            err = self._need(locals(), "reason", "total_amount")
            if err:
                return {"error": err}
            return self._handle_add_long_pending(user_id, user_name, reason, total_amount, category or "General", date)
        if action == "update":
            err = self._need(locals(), "id", "reason", "total_amount")
            if err:
                return {"error": err}
            return self._handle_update_long_pending(user_id, user_name, id, reason, total_amount)
        if action == "delete":
            err = self._need(locals(), "id")
            if err:
                return {"error": err}
            return self._handle_delete_long_pending(user_id, user_name, id)
        if action == "pay":
            err = self._need(locals(), "id", "amount", "account")
            if err:
                return {"error": err}
            return self._handle_pay_long_pending(user_id, user_name, id, amount, account, self._resolve_month(month_key))
        return {"error": f"Unknown action '{action}'. Valid: list, add, update, delete, pay."}

    def _handle_manage_notes(self, user_id: str, user_name: str, action: str, month_key: str = None, note_id: str = None, title: str = None, content: str = None) -> dict:
        """Route a note job (add, list, delete) to its handler."""
        month_key = self._resolve_month(month_key)
        if action == "add":
            err = self._need(locals(), "title", "content")
            if err:
                return {"error": err}
            return self._handle_add_note(user_id, user_name, month_key, title, content)
        if action == "list":
            return self._handle_list_notes(user_id, user_name, month_key)
        if action == "delete":
            err = self._need(locals(), "note_id")
            if err:
                return {"error": err}
            return self._handle_delete_note(user_id, user_name, month_key, note_id)
        return {"error": f"Unknown action '{action}'. Valid: add, list, delete."}

    def _handle_manage_months(self, user_id: str, user_name: str, action: str, month_key: str = None, copy_pending: bool = False) -> dict:
        """Route a month job (list, create, delete) to its handler."""
        if action == "list":
            return self._handle_list_months(user_id, user_name)
        if action == "create":
            return self._handle_create_month(user_id, user_name, self._resolve_month(month_key), copy_pending or False)
        if action == "delete":
            if not month_key:
                return {"error": "month_key is required for delete (no default — deleting a month is irreversible)."}
            return self._handle_delete_month(user_id, user_name, month_key)
        return {"error": f"Unknown action '{action}'. Valid: list, create, delete."}

    def _handle_manage_profile(self, user_id: str, user_name: str, action: str, name: str = None, currency_pref: str = None, default_account: str = None, default_account_id: int = None) -> dict:
        """Route a profile job (get, update) to its handler."""
        if action == "get":
            return self._handle_get_profile(user_id, user_name)
        if action == "update":
            return self._handle_update_profile(user_id, user_name, name, currency_pref, default_account, default_account_id)
        return {"error": f"Unknown action '{action}'. Valid: get, update."}

    def _handle_manage_tokens(self, user_id: str, user_name: str, action: str, pat_id: str = None) -> dict:
        """Route a token job (list, revoke) to its handler."""
        if action == "list":
            return self._handle_list_pats(user_id, user_name)
        if action == "revoke":
            err = self._need(locals(), "pat_id")
            if err:
                return {"error": err}
            return self._handle_revoke_pat(user_id, user_name, pat_id)
        return {"error": f"Unknown action '{action}'. Valid: list, revoke."}
