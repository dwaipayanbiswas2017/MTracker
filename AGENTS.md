# MTracker — Agent Guide

## Quickstart

- **Run the Flask app**: `python app.py` (0.0.0.0:5000)
- **Production**: `https://mtracker.in` (Docker, host networking, port 80)
- **Run the AI agent CLI**: `python agent.py`
- **Docker**: `sudo docker compose up` (host networking, port 80)
- **Deploy (rebuild + verify)**: `./deploy.sh` (see `README.md` → Docker Deployment)
- **Logs**: `sudo docker compose logs -f mtracker`
- **Container ops**: `sudo docker ps`; `sudo docker compose down/up`

## Architecture

- **Single source of truth for tools**: `mcp_server.py` — all 16 tools are implemented exactly once, there.
- **Two consumers of the same registry**:
  - `agent.py` — Pydantic AI agent (Python `get_response()` API). It has NO tool implementations; it reads the MCP registry, builds typed pydantic-ai `Tool` proxies from each tool's JSON Schema, and every call routes through `MTrackerMCPServer.call_tool(...)` (in-process MCP).
  - Over-the-wire MCP — JSON-RPC 2.0 over SSE (`GET /api/mcp/sse`, `POST /api/mcp/messages`) for Claude/Gemini clients, served by the same `MTrackerMCPServer.dispatch(...)`.
- **Data flow**: Mutations modify `currentData` locally, then `POST /api/save` persists full state to MySQL via `database_controller.py`
- **Paid vs Daily expenses**: Both in `paid_expenses` table, differentiated by `is_daily_log` boolean (`FALSE` = regular, `TRUE` = daily/personal)
- **Opening balances**: `{account_name: amount}` dict per month; legacy float also supported
- **User-facing MCP pages**: `GET /api-keys` (`api_keys_page` → `templates/api_keys.html`) for PAT self-service; `GET /mcp-help` (`mcp_help_page` → `templates/mcp_help.html`) for setup docs rendered from the live tool registry. Both `@login_required`, theme-matched to `profile.html`/`admin.html` patterns
- **No tests, no linting, no typechecking** configured

## Agent (agent.py) — Tool Capabilities

The Pydantic AI agent (`agent.py`) exposes the same 16 tools as the MCP server via `get_response(message, *, user_id, mcp_server, db=None)`:

- The agent builds one pydantic-ai `Tool` per MCP registry entry using `_make_tool_proxy()` (dynamic typed function signature derived from each tool's JSON Schema).
- Each tool call runs through `MTrackerMCPServer.call_tool(name, args, user_id=..., user_name=..., scope="read_write")` — the agent always acts as its user with full permissions.
- `db` is optional and only used to pre-fetch profile context (name/currency); if omitted, profile comes from the `manage_profile/get` tool.

### Reads (standalone, all read-only)
- `get_summary` — High-level summary (income, expenses, net balance) for a month (default current)
- `get_month_data` — Full state of a month (optional `sections` filter)
- `get_account_balances` — per-account running balance (opening + income - expenses)
- `get_last_expense_date` — most recent expense with date/month/amount/reason/category/account

### Grouped entity tools (`action` enum; `month_key` defaults to current month)
- `manage_expenses` — `add_paid` / `add_daily` (`is_daily_log=TRUE`) / `update` / `delete` (linked-entry guards; delete cascades)
- `manage_income` — `add` / `update` / `delete` (delete cascades linked transfer expense)
- `manage_pending` — `add` / `list` (RO) / `delete`
- `manage_accounts` — `list` (RO) / `add` / `update` (rename) / `set_opening_balance`
- `manage_categories` — `list` (RO) / `add` / `update` (rename)
- `manage_debts` — `list` (RO) / `add` / `update` / `delete` / `pay` (partial payment → expense)
- `manage_months` — `list` (RO) / `create` (optional `copy_pending`) / `delete` (explicit `month_key` required)
- `manage_notes` — `add` / `list` (RO) / `delete`
- `manage_profile` — `get` (RO) / `update` (name, currency, default account NAME or ID)
- `manage_tokens` — `list` (RO) / `revoke` (creation is web-UI-only)

### Standalone (unique semantics)
- `transfer_funds` — Move between accounts (linked expense + income pair)
- `import_bulk` — Import from CSV content (`csv_text`) or server-side path (`file_path`)

## MCP Server (mcp_server.py)

- **16 tools defined exactly once (10 grouped + 4 reads + transfer/import)**; `MTrackerMCPServer` is the shared engine behind both the in-process agent and the over-the-wire transport (`serverInfo` v1.1.0; legacy flat tool names are retired)
- Over-the-wire: spec-compliant JSON-RPC 2.0 over SSE (`GET /api/mcp/sse`, `POST /api/mcp/messages`)
- **Single gthread worker required**: MCP SSE sessions live in process memory, so gunicorn must run `--workers 1 --threads N --worker-class gthread` (see `Dockerfile`). Multiple sync workers split session state across processes and clients hang on `initialize`. Session manager is thread-safe via locks; a session-miss is logged as a warning
- **In-process API**: `call_tool(name, arguments, *, user_id, user_name, scope)` returns raw result dict (used by `agent.py`)
- **Read-only tokens**: scope `read` allows only standalone reads + per-tool `read_actions` (`manage_pending/list`, `manage_profile/get`, etc.); everything else fails closed. Standalone writes (`transfer_funds`, `import_bulk`) are always blocked under `read`
- **Lifecycle methods**: `initialize` (negotiates protocol version against `SUPPORTED_PROTOCOL_VERSIONS`), `ping`, `notifications/initialized`, batch requests, standard JSON-RPC error codes
- **`tools/call` result**: MCP envelope `{content, structuredContent, isError}`
- **Authentication**: Bearer PAT (`mt_live_...`); validate via `database_controller.py::validate_pat`
- **Resources**: `mtracker://accounts`, `mtracker://categories`, `mtracker://debts/active`, `mtracker://schema`
- **Audit logging**: Every action logged with `origin='mcp'` or `origin='web'`

## Database (database_controller.py)

- MySQL-backed with stored procedures: `sp_create_month`, `sp_pay_long_pending`
- Key tables: `users`, `accounts`, `categories`, `months`, `opening_balances`, `income`, `paid_expenses`, `pending_expenses`, `long_pending`, `notes`
- **Full-state sync**: `save_month_data()` replaces all transaction data for a month — do not partially modify returned dicts
- **Partial payments**: Use `make_partial_payment()` (wraps `sp_pay_long_pending`) — updates remaining balance + creates linked expense
- **Expense deletion**: `delete_expense()` cascades: reverses long-pending payments, removes transfer-linked income
- **PAT ops**: `create_pat`, `validate_pat`, `list_pats`, `revoke_pat` (in `database_controller.py:804-891`)
- **Backups**: `create_backup()`, `restore_backup()`, `set_backup_schedule()` (in `database_controller.py:900-1085`)

## Conventions & Gotchas

- All item IDs are JS timestamps stringified (`str(datetime.now().timestamp())`)
- **Opening balance per-account**: update via `onchange="updateOpeningBalance('AccountName', value)"` in the UI; DB reflected through `opening_balances` table
- **Categories/accounts**: full CRUD via `/api/categories` and `/api/accounts`; MCP via `manage_categories` / `manage_accounts` (`list`/`add`/`update` actions)
- **CSV import**: `import_bulk` takes pasted `csv_text` (preferred for remote clients) or server-side absolute `file_path`; parses sections: `TOTAL EXPENSE LIST`/`PAYMENT REASON` (paid), `PENDING`, `Personal Expenses`, `INCOME IN CURRENT MONTH`, `AVAILABLE FROM PREVIOUS MONTH`
- **Transfer marker**: transfers use `__transfer__:<ref>` in `notes` field; deleting a transfer expense removes linked income
- **Daily log expenses**: `is_daily_log=TRUE` in `paid_expenses`; appear in both `paidExpenses` and `personalExpenses` aggregates
- **Long-pending payments**: `make_partial_payment()` creates an expense entry in the specified month; the `__transfer__` marker is NOT added for long-pending payments
- **No transactional single-record inserts**: Most operations read-current-state → append → `save_month_data()`; race conditions possible with concurrent edits
- **Profile `default_account`**: provide account NAME (e.g. `'Cash'`, `'SBI-2390'`), not ID — `manage_profile/update` resolves the name to an ID internally (or pass `default_account_id` directly)
- **Currency**: user prefs from `users` table; agent injects per-call; MCP tokens have scope-level read/write

## Commands Summary

| Operation | Tool + action (agent + MCP) | DB Method |
|---|---|---|
| List months | `manage_months` / `list` | `get_months` |
| Create month | `manage_months` / `create` | `sp_create_month` |
| Add paid expense | `manage_expenses` / `add_paid` | (via `save_month_data`) |
| Add daily expense | `manage_expenses` / `add_daily` | (via `save_month_data`, `is_daily_log=TRUE`) |
| Add income | `manage_income` / `add` | (via `save_month_data`) |
| Transfer funds | `transfer_funds` | (via `save_month_data`) |
| Pay long-pending | `manage_debts` / `pay` | `make_partial_payment`/`sp_pay_long_pending` |
| Add long-pending debt | `manage_debts` / `add` | `add_long_pending` |
| Delete expense | `manage_expenses` / `delete` | `delete_expense` |
| CSV import | `import_bulk` | `sync_bulk_data`/`save_month_data` |
| Get account balances | `get_account_balances` | `get_month_data` + compute |
| Get last expense date | `get_last_expense_date` | manual scan across months |