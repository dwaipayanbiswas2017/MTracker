"""
MTracker MCP Server — Model Context Protocol implementation.

Provides AI agents (Claude, Gemini, etc.) direct access to MTracker
financial data via 21 tools (JSON-RPC 2.0 over SSE transport).

Transport:
  GET  /api/mcp/sse        — SSE stream (server → client)
  POST /api/mcp/messages   — JSON-RPC requests (client → server)
"""

import json
import time
from datetime import datetime
from typing import Any

from database_controller import DatabaseController


# ─────────────────────────────────────────────────────────
#  Tool descriptor
# ─────────────────────────────────────────────────────────

class MCPTool:
    """Describes an MCP tool available to AI agents."""

    def __init__(self, name: str, description: str, input_schema: dict, handler: callable):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


# ─────────────────────────────────────────────────────────
#  Session manager
# ─────────────────────────────────────────────────────────

class MCPSession:
    """Tracks a single SSE connection and its pending messages."""

    def __init__(self, session_id: str, user_id: str, user_name: str, scope: str):
        self.session_id = session_id
        self.user_id = user_id
        self.user_name = user_name
        self.scope = scope
        self.created_at = time.time()
        self.pending_responses: list[dict] = []
        self._lock = None  # Simple flag; Flask sync avoids races

    def add_response(self, response: dict):
        self.pending_responses.append(response)

    def drain_responses(self) -> list[dict]:
        items = list(self.pending_responses)
        self.pending_responses.clear()
        return items


class MCPSessionManager:
    """Manages all active MCP sessions."""

    def __init__(self):
        self._sessions: dict[str, MCPSession] = {}

    def create(self, session_id: str, user_id: str, user_name: str, scope: str) -> MCPSession:
        session = MCPSession(session_id, user_id, user_name, scope)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> MCPSession | None:
        return self._sessions.get(session_id)

    def remove(self, session_id: str):
        self._sessions.pop(session_id, None)

    def cleanup_stale(self, max_age: float = 300.0):
        now = time.time()
        stale = [sid for sid, s in self._sessions.items() if now - s.created_at > max_age]
        for sid in stale:
            self._sessions.pop(sid, None)


sessions = MCPSessionManager()


# ─────────────────────────────────────────────────────────
#  JSON-RPC helpers
# ─────────────────────────────────────────────────────────

def make_jsonrpc_error(code: int, message: str, req_id: Any = None) -> dict:
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": req_id}


def make_jsonrpc_result(result: Any, req_id: Any = None) -> dict:
    return {"jsonrpc": "2.0", "result": result, "id": req_id}


# ─────────────────────────────────────────────────────────
#  MCP Server
# ─────────────────────────────────────────────────────────

class MTrackerMCPServer:
    """
    MCP protocol dispatcher for MTracker.
    Processes JSON-RPC 2.0 messages and routes them to the appropriate tool.
    """

    def __init__(self, db: DatabaseController):
        self.db = db
        self._tools: dict[str, MCPTool] = {}
        self._register_tools()

    # ── Tool registration ──────────────────────────────

    def _register_tools(self):
        """Register all 21 MCP tools with full descriptions and parameter schemas."""

        # ── Transaction Management ──────────────────────

        self._add_tool(
            name="get_summary",
            description=(
                "Get a high-level financial summary for a specific month. "
                "Returns total income, total expenses (paid + personal), net balance, "
                "and counts of transactions."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format (e.g. '2025-11')",
                    }
                },
                "required": ["month_key"],
            },
            handler=self._handle_get_summary,
        )

        self._add_tool(
            name="get_month_data",
            description=(
                "Get the full state of a month including all income entries, "
                "paid expenses, personal expenses, pending expenses, notes, "
                "and opening balances per account."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format (e.g. '2025-11')",
                    }
                },
                "required": ["month_key"],
            },
            handler=self._handle_get_month_data,
        )

        self._add_tool(
            name="add_paid_expense",
            description=(
                "Record a completed (paid) transaction. "
                "This adds an expense entry to the specified month. "
                "The amount is deducted from the selected account's balance."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Transaction amount in the user's currency (positive number)",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Description or purpose of the expense",
                    },
                    "category": {
                        "type": "string",
                        "description": "Expense category name (must exist in user's categories)",
                    },
                    "account": {
                        "type": "string",
                        "description": "Account name from which the payment was made",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format (optional, defaults to today)",
                    },
                },
                "required": ["month_key", "amount", "reason", "category", "account"],
            },
            handler=self._handle_add_paid_expense,
        )

        self._add_tool(
            name="add_income",
            description=(
                "Record a new income entry for a specific month. "
                "Adds the amount to the selected account's balance."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Income amount in the user's currency (positive number)",
                    },
                    "source": {
                        "type": "string",
                        "description": "Source or description of the income (e.g. 'Salary', 'Freelance')",
                    },
                    "account": {
                        "type": "string",
                        "description": "Account name to credit the income to",
                    },
                },
                "required": ["month_key", "amount", "source", "account"],
            },
            handler=self._handle_add_income,
        )

        self._add_tool(
            name="add_pending_item",
            description=(
                "Add an item to the monthly pending / budget list. "
                "These are planned expenses that have not yet been paid."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Planned amount for this budget item",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Description of the planned expense",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category name for this budget item",
                    },
                },
                "required": ["month_key", "amount", "reason", "category"],
            },
            handler=self._handle_add_pending_item,
        )

        self._add_tool(
            name="transfer_funds",
            description=(
                "Move money between two accounts within the same month. "
                "This creates a linked pair of entries: a paid expense on the "
                "source account and an income on the destination account. "
                "Both entries are tied together so deleting one automatically "
                "removes the other."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format",
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
                "required": ["month_key", "from_account", "to_account", "amount"],
            },
            handler=self._handle_transfer_funds,
        )

        self._add_tool(
            name="delete_expense",
            description=(
                "Remove an expense from a month. "
                "If the expense was linked to a long-pending debt payment, "
                "the debt balance is automatically reversed. "
                "If it was part of a fund transfer, the linked income entry "
                "is also removed."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier containing the expense",
                    },
                    "expense_id": {
                        "type": "string",
                        "description": "ID of the expense to delete",
                    },
                },
                "required": ["month_key", "expense_id"],
            },
            handler=self._handle_delete_expense,
        )

        self._add_tool(
            name="import_bulk",
            description=(
                "Import transactions in bulk from a CSV file. "
                "The CSV should contain sections for paid expenses, "
                "pending expenses, personal expenses, and income. "
                "Provide the full server-side file path to the CSV."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the CSV file on the server",
                    },
                    "month_key": {
                        "type": "string",
                        "description": "Target month identifier in YYYY-MM format",
                    },
                },
                "required": ["file_path", "month_key"],
            },
            handler=self._handle_import_bulk,
        )

        # ── Accounts & Categories ─────────────────────

        self._add_tool(
            name="list_accounts",
            description=(
                "Fetch all financial accounts (bank accounts, cash buckets) "
                "configured by the user."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=self._handle_list_accounts,
        )

        self._add_tool(
            name="add_account",
            description="Create a new financial account (bank, cash, wallet, etc.).",
            input_schema={
                "type": "object",
                "properties": {
                    "account_name": {
                        "type": "string",
                        "description": "Name for the new account",
                    }
                },
                "required": ["account_name"],
            },
            handler=self._handle_add_account,
        )

        self._add_tool(
            name="update_account",
            description="Rename an existing financial account.",
            input_schema={
                "type": "object",
                "properties": {
                    "old_name": {
                        "type": "string",
                        "description": "Current name of the account",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New name for the account",
                    },
                },
                "required": ["old_name", "new_name"],
            },
            handler=self._handle_update_account,
        )

        self._add_tool(
            name="list_categories",
            description="Fetch all expense and income categories configured by the user.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=self._handle_list_categories,
        )

        self._add_tool(
            name="add_category",
            description="Create a new expense/income category.",
            input_schema={
                "type": "object",
                "properties": {
                    "category_name": {
                        "type": "string",
                        "description": "Name for the new category",
                    }
                },
                "required": ["category_name"],
            },
            handler=self._handle_add_category,
        )

        self._add_tool(
            name="update_category",
            description="Rename an existing expense/income category.",
            input_schema={
                "type": "object",
                "properties": {
                    "old_name": {
                        "type": "string",
                        "description": "Current name of the category",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New name for the category",
                    },
                },
                "required": ["old_name", "new_name"],
            },
            handler=self._handle_update_category,
        )

        # ── Long Pending (Debts & Loans) ──────────────

        self._add_tool(
            name="list_long_pending",
            description=(
                "Fetch all active long-term debts and loans. "
                "Returns remaining balances, total amounts, and payment status."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=self._handle_list_long_pending,
        )

        self._add_tool(
            name="add_long_pending",
            description=(
                "Create a new long-term debt or loan entry. "
                "Use this for tracking loans taken, money owed to others, "
                "or any long-term financial obligation."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Description of the debt/loan",
                    },
                    "total_amount": {
                        "type": "number",
                        "description": "Total amount of the loan/debt",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category (optional, defaults to 'General')",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format (optional, defaults to today)",
                    },
                },
                "required": ["reason", "total_amount"],
            },
            handler=self._handle_add_long_pending,
        )

        self._add_tool(
            name="update_long_pending",
            description="Update the details of a long-term debt or loan entry.",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "ID of the debt/loan entry to update",
                    },
                    "reason": {
                        "type": "string",
                        "description": "New description",
                    },
                    "total_amount": {
                        "type": "number",
                        "description": "New total amount",
                    },
                },
                "required": ["id", "reason", "total_amount"],
            },
            handler=self._handle_update_long_pending,
        )

        self._add_tool(
            name="delete_long_pending",
            description="Permanently remove a long-term debt or loan record.",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "ID of the debt/loan to delete",
                    }
                },
                "required": ["id"],
            },
            handler=self._handle_delete_long_pending,
        )

        self._add_tool(
            name="pay_long_pending",
            description=(
                "Record a partial payment towards a long-term debt. "
                "This reduces the remaining balance and creates a paid expense "
                "entry in the specified month."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "ID of the debt/loan item to pay towards",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount being paid",
                    },
                    "account": {
                        "type": "string",
                        "description": "Account name from which the payment is made",
                    },
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier for the expense entry",
                    },
                },
                "required": ["item_id", "amount", "account", "month_key"],
            },
            handler=self._handle_pay_long_pending,
        )

        # ── Notes & Months ────────────────────────────

        self._add_tool(
            name="list_months",
            description="Get a list of all months that have financial data recorded.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=self._handle_list_months,
        )

        self._add_tool(
            name="create_month",
            description=(
                "Initialize a new month for tracking finances. "
                "Optionally copy pending expenses from the previous month."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format",
                    },
                    "copy_pending": {
                        "type": "boolean",
                        "description": "If true, copies pending expenses from the previous month",
                    },
                },
                "required": ["month_key"],
            },
            handler=self._handle_create_month,
        )

        self._add_tool(
            name="delete_month",
            description="Delete an entire month and all its financial data.",
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format to delete",
                    }
                },
                "required": ["month_key"],
            },
            handler=self._handle_delete_month,
        )

        self._add_tool(
            name="add_note",
            description=(
                "Save a text note for a specific month. "
                "Useful for recording context, reminders, or explanations "
                "about the month's finances."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "month_key": {
                        "type": "string",
                        "description": "Month identifier in YYYY-MM format",
                    },
                    "title": {
                        "type": "string",
                        "description": "Title of the note",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content or body of the note",
                    },
                },
                "required": ["month_key", "title", "content"],
            },
            handler=self._handle_add_note,
        )

        # ── Profile ───────────────────────────────────

        self._add_tool(
            name="get_profile",
            description=(
                "Get the user's profile settings including name, "
                "preferred currency, and default account."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=self._handle_get_profile,
        )

        self._add_tool(
            name="update_profile",
            description="Update user profile preferences such as name, currency, or default account.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "New display name (optional)",
                    },
                    "currency_pref": {
                        "type": "string",
                        "description": "Preferred currency code like 'INR', 'USD', 'EUR' (optional)",
                    },
                    "default_account_id": {
                        "type": "integer",
                        "description": "ID of the default account (optional)",
                    },
                },
                "required": [],
            },
            handler=self._handle_update_profile,
        )

    def _add_tool(self, name: str, description: str, input_schema: dict, handler: callable):
        self._tools[name] = MCPTool(name, description, input_schema, handler)

    def list_tools(self) -> dict:
        """Return the MCP ListToolsResult as a JSON-RPC result."""
        return {"tools": [t.to_dict() for t in self._tools.values()]}

    # ── Dispatch ──────────────────────────────────────

    def dispatch(self, message: dict, user_id: str, user_name: str, scope: str) -> list[dict]:
        """
        Process an incoming JSON-RPC 2.0 message and return response(s).

        Supports batched requests (list of messages).
        Returns a list of response dicts (one per request in batch).
        """
        if isinstance(message, list):
            return [self._handle_single(m, user_id, user_name, scope) for m in message]

        return [self._handle_single(message, user_id, user_name, scope)]

    def _handle_single(self, msg: dict, user_id: str, user_name: str, scope: str) -> dict:
        req_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        # Protocol-level methods
        if method == "tools/list":
            return make_jsonrpc_result(self.list_tools(), req_id)

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            tool = self._tools.get(tool_name)
            if not tool:
                return make_jsonrpc_error(-32601, f"Tool not found: {tool_name}", req_id)

            if scope == "read" and tool_name not in ("get_summary", "get_month_data", "list_accounts", "list_categories", "list_long_pending", "list_months", "get_profile"):
                return make_jsonrpc_error(-32000, "Read-only token cannot perform write operations", req_id)

            try:
                result = tool.handler(user_id, user_name, **arguments)
                return make_jsonrpc_result(result, req_id)
            except Exception as e:
                return make_jsonrpc_error(-32603, f"Tool error: {str(e)}", req_id)

        if method == "resources/list":
            return make_jsonrpc_result(self._list_resources(user_id), req_id)

        if method == "resources/read":
            uri = params.get("uri", "")
            return make_jsonrpc_result(self._read_resource(user_id, uri), req_id)

        return make_jsonrpc_error(-32601, f"Unknown method: {method}", req_id)

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

    # ── Tool Handlers ─────────────────────────────────

    def _audit(self, user_id: str, action: str, table: str, record_id: str, details: dict = None):
        """Write an audit log entry for MCP actions."""
        try:
            self.db.log_audit(user_id, action, table, record_id, details, origin='mcp')
        except Exception:
            pass  # Audit failures must never break the main flow

    def _read_month_and_append(self, user_id: str, month_key: str) -> dict | None:
        """Helper: read current month data. Returns None if month doesn't exist."""
        data = self.db.get_month_data(user_id, month_key)
        if data is None:
            return None
        # Ensure arrays exist
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

    # ── Individual tool handlers ──────────────────────

    def _handle_get_summary(self, user_id: str, user_name: str, month_key: str) -> dict:
        """Compute a high-level financial summary for a month."""
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

    def _handle_get_month_data(self, user_id: str, user_name: str, month_key: str) -> dict:
        """Return the full state of a month."""
        data = self.db.get_month_data(user_id, month_key)
        if data is None:
            return {"error": f"Month {month_key} not found. Use create_month first."}
        return data

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

    def _handle_import_bulk(self, user_id: str, user_name: str, file_path: str, month_key: str) -> dict:
        """Import transactions from a CSV file (reuses app.py CSV parser logic)."""
        import csv
        import io
        import os

        if not os.path.isfile(file_path):
            return {"error": f"File not found: {file_path}"}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return {"error": f"Could not read file: {e}"}

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
        return self.db.get_accounts(user_id)

    def _handle_add_account(self, user_id: str, user_name: str, account_name: str) -> dict:
        if self.db.add_account(user_id, account_name):
            self._audit(user_id, "INSERT", "accounts", account_name)
            return {"status": "success", "message": f"Account '{account_name}' created."}
        return {"error": f"Could not create account '{account_name}'. It may already exist."}

    def _handle_update_account(self, user_id: str, user_name: str, old_name: str, new_name: str) -> dict:
        if self.db.update_account(user_id, old_name, new_name):
            self._audit(user_id, "UPDATE", "accounts", old_name, {"new_name": new_name})
            return {"status": "success", "message": f"Account renamed from '{old_name}' to '{new_name}'."}
        return {"error": f"Could not rename account. '{old_name}' may not exist."}

    def _handle_list_categories(self, user_id: str, user_name: str) -> list:
        return self.db.get_categories(user_id)

    def _handle_add_category(self, user_id: str, user_name: str, category_name: str) -> dict:
        if self.db.add_category(user_id, category_name):
            self._audit(user_id, "INSERT", "categories", category_name)
            return {"status": "success", "message": f"Category '{category_name}' created."}
        return {"error": f"Could not create category '{category_name}'. It may already exist."}

    def _handle_update_category(self, user_id: str, user_name: str, old_name: str, new_name: str) -> dict:
        if self.db.update_category(user_id, old_name, new_name):
            self._audit(user_id, "UPDATE", "categories", old_name, {"new_name": new_name})
            return {"status": "success", "message": f"Category renamed from '{old_name}' to '{new_name}'."}
        return {"error": f"Could not rename category. '{old_name}' may not exist."}

    def _handle_list_long_pending(self, user_id: str, user_name: str) -> list:
        return self.db.get_long_pending(user_id)

    def _handle_add_long_pending(self, user_id: str, user_name: str, reason: str, total_amount: float, category: str = "General", date: str = None) -> dict:
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
        item_data = {"id": id, "reason": reason, "totalAmount": float(total_amount), "category": None}
        if self.db.update_long_pending(user_id, item_data):
            self._audit(user_id, "UPDATE", "long_pending", id, {"reason": reason, "total_amount": total_amount})
            return {"status": "success", "message": "Debt entry updated."}
        return {"error": "Debt entry not found or could not be updated."}

    def _handle_delete_long_pending(self, user_id: str, user_name: str, id: str) -> dict:
        if self.db.delete_long_pending(user_id, id):
            self._audit(user_id, "DELETE", "long_pending", id)
            return {"status": "success", "message": "Debt entry deleted."}
        return {"error": "Debt entry not found."}

    def _handle_pay_long_pending(self, user_id: str, user_name: str, item_id: str, amount: float, account: str, month_key: str) -> dict:
        if self.db.make_partial_payment(user_id, item_id, month_key, float(amount), account, "Online"):
            self._audit(user_id, "UPDATE", "long_pending", item_id, {"payment_amount": amount, "month_key": month_key, "account": account})
            return {"status": "success", "message": f"Payment of {amount} recorded towards debt."}
        return {"error": "Could not process payment. Check that the item ID and account are valid."}

    def _handle_list_months(self, user_id: str, user_name: str) -> list:
        return self.db.get_months(user_id)

    def _handle_create_month(self, user_id: str, user_name: str, month_key: str, copy_pending: bool = False) -> dict:
        result = self.db.create_month(user_id, month_key, copy_pending)
        if result:
            self._audit(user_id, "INSERT", "months", month_key, {"copy_pending": copy_pending})
            return {"status": "success", "message": f"Month {month_key} initialized.", "data": result}
        return {"error": f"Could not create month {month_key}. It may already exist."}

    def _handle_delete_month(self, user_id: str, user_name: str, month_key: str) -> dict:
        if self.db.delete_month(user_id, month_key):
            self._audit(user_id, "DELETE", "months", month_key)
            return {"status": "success", "message": f"Month {month_key} deleted."}
        return {"error": f"Could not delete month {month_key}."}

    def _handle_add_note(self, user_id: str, user_name: str, month_key: str, title: str, content: str) -> dict:
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

    def _handle_update_profile(self, user_id: str, user_name: str, name: str = None, currency_pref: str = None, default_account_id: int = None) -> dict:
        kwargs = {}
        if name is not None:
            kwargs["name"] = name
        if currency_pref is not None:
            kwargs["currency_pref"] = currency_pref
        if default_account_id is not None:
            kwargs["default_account_id"] = default_account_id

        if not kwargs:
            return {"status": "success", "message": "No changes requested."}

        if self.db.update_user(user_id, **kwargs):
            self._audit(user_id, "UPDATE", "users", user_id, kwargs)
            return {"status": "success", "message": "Profile updated."}
        return {"error": "Failed to update profile."}
