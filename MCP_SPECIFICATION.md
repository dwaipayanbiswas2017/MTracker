# MTracker Model Context Protocol (MCP) Specification

This document describes the live Model Context Protocol integration in MTracker. AI agents (Claude, Gemini, VSCode, and the built-in Pydantic AI assistant) interact with user financial data through 16 tools served over JSON-RPC 2.0 + SSE, plus 4 state resources. Everything below reflects the actual implementation in `mcp_server.py`, `app.py`, `agent.py`, and `database_controller.py`.

*Status: Implemented and in production*
*Tool count: 16 · Resources: 4 · Server: `mtracker/1.1.0`*

## 1. Architecture Overview

### Single source of truth

All 16 tools are implemented **exactly once** in `mcp_server.py` (`MTrackerMCPServer._register_tools`). There are no duplicate agent-side implementations. Each tool is declared as an `MCPTool` with:

| Field | Purpose | Seen by |
|---|---|---|
| `name` | Tool identifier (e.g. `get_summary`) | AI + wire clients |
| `description` | Rich usage documentation | AI (this is what the model reasons from) |
| `input_schema` | JSON Schema of parameters (types, descriptions, required) | AI + wire clients |
| `handler` | `(user_id, user_name, **kwargs) -> dict` implementation | server only |
| `read_only` | `True` = callable under a `read`-scoped token (standalone tools) | auth layer |
| `read_actions` | set of `action` values callable under a `read`-scoped token; `None` = fall back to `read_only` (grouped tools) | auth layer |

### Two consumers of the same registry

- **`agent.py` (Pydantic AI, in-process)** — reads the registry at startup, builds one typed `Tool` proxy per entry from its JSON Schema (`_make_tool_proxy`), and routes every call through `MTrackerMCPServer.call_tool(name, args, user_id=…, user_name=…, scope="read_write")`. The agent always acts with its user's full permissions.
- **Over-the-wire MCP (external clients)** — `MTrackerMCPServer.dispatch(message, user_id, user_name, scope)` serves spec-compliant JSON-RPC 2.0 over SSE (`GET /api/mcp/sse` + `POST /api/mcp/messages`).

### Data flow (SSE transport)

1. Client `GET /api/mcp/sse` with `Authorization: Bearer mt_live_…` → server creates a session, replies with an `event: endpoint` message containing the POST URL (`/api/mcp/messages?session_id=…`), then holds the stream open.
2. Client `POST`s JSON-RPC 2.0 messages to that URL → server dispatches and queues responses into the session.
3. The SSE stream drains the queue (every 0.5s) as `data: {json}` events.
4. POSTs without a matching session get the JSON-RPC response returned inline instead.

### Session constraint (operational)

Sessions live in **process memory** (`MCPSessionManager`, thread-safe via locks, 5-minute stale cleanup). Gunicorn must therefore run as a **single gthread worker** (`--workers 1 --threads N --worker-class gthread`, see `Dockerfile`): multiple sync workers split session state across processes and clients hang on `initialize`. A session-miss is logged as a warning (`MCP session miss for session_id=…`). Roll out with `./deploy.sh`, which rebuilds the image, redeploys, waits for readiness, and verifies the live routes (`200` login, `401` SSE auth gate, `302` on the user pages).

### Internal components

- **Auth middleware** (`app._mcp_authenticate`): validates the Bearer PAT via `db.validate_pat`, refreshes `last_used_at`, injects `user_id`/`user_name`/`scope`.
- **Dispatcher** (`MTrackerMCPServer.dispatch`): JSON-RPC 2.0 router — batch requests, notifications (no `id` → no reply), lifecycle methods, standard error codes.
- **Session manager**: per-connection response queues drained by the SSE event stream.
- **Audit**: every write tool logs via `db.log_audit(…, origin='mcp')`.

## 2. HTTP Endpoints

All MCP routes live in `app.py`. CSRF is exempt on the wire-transport routes (PAT auth replaces session auth); the page and token-management routes use the normal logged-in session + CSRF token.

| Endpoint | Method | Auth | Handler | Purpose |
|---|---|---|---|---|
| `/api/mcp/sse` | GET | Bearer PAT | `mcp_sse` | SSE stream (server → client). Emits `endpoint` event, then queued responses. Anti-buffering headers (`Cache-Control: no-cache`, `X-Accel-Buffering: no`). |
| `/api/mcp/messages` | POST | Bearer PAT | `mcp_messages` | JSON-RPC in (client → server). `?session_id=` routes into the SSE stream (`{"status":"queued"}`); without a session the response is returned inline. |
| `/api/mcp/tokens` | POST | login session | `mcp_create_token` | Create PAT. Body: `name` (required, ≤64 chars), `scope` (`read`/`read_write`), optional `expires_in_days` (positive int). Max 10 active tokens per user. Returns the raw token **once**. |
| `/api/mcp/tokens` | GET | login session | `mcp_list_tokens` | List active PATs (metadata only — never raw values). |
| `/api/mcp/tokens/<pat_id>` | DELETE | login session | `mcp_revoke_token` | Revoke a PAT (immediate effect). |
| `/api-keys` | GET | login session | `api_keys_page` | Self-service token management UI (`templates/api_keys.html`). |
| `/mcp-help` | GET | login session | `mcp_help_page` | Setup guide + live tool/resource reference (`templates/mcp_help.html`, rendered from the registry). |

## 3. Authentication

Bearer PAT in the `Authorization` header of **both** the SSE request and every message POST:

```http
GET /api/mcp/sse HTTP/1.1
Host: mtracker.in
Authorization: Bearer mt_live_abc123…
Accept: text/event-stream
```

Production base URL: `https://mtracker.in` (SSE stream at `https://mtracker.in/api/mcp/sse`). The `/mcp-help` page renders client configs with the deployment's real URLs — copy them from there.

- **Format:** `mt_live_` + 64 hex chars. Only the SHA-256 hash is stored (`personal_access_tokens.token_hash`); the raw value is shown once at creation.
- **Validation** (`db.validate_pat`): prefix check → hash lookup → must be unrevoked, unexpired, and belong to an active user. Returns `{user_id, user_name, scope}`.
- **Scopes:**

| Scope | Allows |
|---|---|
| `read` | Read-only surface only: the 4 standalone reads plus the per-tool read actions — `manage_pending/list`, `manage_accounts/list`, `manage_categories/list`, `manage_debts/list`, `manage_notes/list`, `manage_months/list`, `manage_profile/get`, `manage_tokens/list`. Anything else (including missing/unknown `action`) fails closed with `"Read-only token cannot perform this action"` (standalone writes: `"Read-only token cannot perform write operations"`). |
| `read_write` | All 16 tools, all actions. |

## 4. Protocol

- **Versions:** `SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")`. `initialize` echoes the client's version when supported, else falls back to `2024-11-05`. (Required: modern clients such as VSCode offer `2025-11-25` and drop the session if the server insists on an unsupported version.)
- **Server info:** `{name: "mtracker", version: "1.1.0"}` · **Capabilities:** `{tools: {listChanged: false}, resources: {}}`.
- **Lifecycle:** `initialize` → `notifications/initialized` → `tools/list` → `tools/call`; `ping` → `{}`; `resources/list`, `resources/read`.
- **Error codes:** `-32700` parse · `-32600` invalid request (incl. empty batch) · `-32601` method/tool not found · `-32602` invalid params · `-32603` internal · `-32000` server/scope errors.
- **`tools/call` result envelope:** `{"content": [{"type": "text", "text": …}], "structuredContent": <raw result>, "isError": bool}`. Any handler result containing an `"error"` key yields `isError: true` with the message as text.

## 5. Tools Reference (live registry)

`*` = required. `RO` = read-only (usable with `read` scope). Descriptions below are the exact AI-facing `description` strings from the registry.

### 💰 Financial data query (all RO)

| Tool | RO | Parameters | Description & result |
|---|---|---|---|
| `get_summary` | ✅ | `month_key`* (`YYYY-MM`) | High-level summary: total income, total expenses (paid + personal/daily), net balance, per-account opening balances, transaction counts. Returns `{month_key, total_income, total_expenses, total_paid_expenses, total_personal_expenses, opening_balance, net_balance, transaction_count, pending_count, note_count}` or `{"error": …}` when the month is missing. |
| `get_month_data` | ✅ | `month_key` (default current), `sections` (optional subset) | Full month state: income, paid/personal/pending expenses, notes, per-account opening balances. Raw dict (large — prefer `get_summary` for totals). |
| `get_account_balances` | ✅ | `month_key`* | Per-account running balance: opening + income − expenses (paid + personal/daily). Returns `{month_key, balances: [{account, opening_balance, income, expenses, balance}]}`. |
| `get_last_expense_date` | ✅ | - | Latest expense with full details. Returns `{last_expense_date, month_key, amount, reason, category, account}`. |
| `get_month_data` sections | n/a | `sections` (optional array of `income`, `paidExpenses`, `personalExpenses`, `pendingExpenses`, `notes`, `openingBalance`) | Returns only the requested sections instead of the full month. Unknown names yield an error listing the allowed values. |

> **Grouped tools** (v1.1.0): related operations share one tool with an `action`
> enum. Only `action` is schema-required; per-action required fields are listed
> below and enforced at runtime. `month_key` defaults to the current month
> everywhere except `manage_months/delete`, which requires it explicitly.
> `RO` lists the actions a `read`-scoped token may run (anything else, including
> missing/unknown actions, fails closed).

### 💸 Expenses — `manage_expenses` (all actions write)

| Action | Needs | Behavior |
|---|---|---|
| `add_paid` | `amount`, `reason`, `category` (must exist), `account` (must exist) | Regular non-daily expense. Returns `{status, id, message}`. |
| `add_daily` | `amount`, `reason`, `account` (must exist) | Daily/personal spend (`is_daily_log=TRUE`); category defaults to `Personal`. |
| `update` | `expense_id` (+ any of `amount`, `reason`, `category`, `account`, `date`) | In-place edit across paid + personal lists. Transfer-/debt-linked entries rejected. |
| `delete` | `expense_id` | Cascade-aware delete (reverses debt payments, drops linked transfer income). |

### 💰 Income — `manage_income` (all actions write)

| Action | Needs | Behavior |
|---|---|---|
| `add` | `amount`, `source`, `account` | New income entry. Returns `{status, id, message}`. |
| `update` | `income_id` (+ `amount`/`source`/`account`) | In-place edit; transfer-linked entries rejected. |
| `delete` | `income_id` | Removes entry (+ linked transfer expense, noted in message). |

### 📋 Budget — `manage_pending` (RO: `list`)

| Action | Needs | Behavior |
|---|---|---|
| `add` | `amount`, `reason`, `category` | Planned/unpaid budget item. |
| `list` | — | All planned items (raw list). |
| `delete` | `item_id` | Drops the plan only; paid expenses untouched. |

### 🔀 Transfers & bulk

| Tool | RO | Parameters | Description, behavior & errors |
|---|---|---|---|
| `transfer_funds` | ❌ | `from_account`*, `to_account`*, `amount`*, `month_key` (default current), `reason` (default `Fund Transfer`) | Linked expense + income pair sharing a `__transfer__:<ref>` marker (auto-creates the `Transfer` category). Deleting one side removes the other. Returns `{status, transfer_ref, expense_id, income_id, message}`. |
| `import_bulk` | ❌ | `month_key` (default current), `csv_text`? (raw CSV, preferred) OR `file_path`? (server path) — exactly one required | Parses CSV sections and syncs via `db.sync_bulk_data`. Returns `{status, items_imported, message}`. |

### 🏦 Accounts — `manage_accounts` (RO: `list`)

| Action | Needs | Behavior |
|---|---|---|
| `list` | — | All bank accounts / cash buckets (`[{id, account_name, …}]`). |
| `add` | `account` | Creates a bank/cash/wallet account. Errors if it exists. |
| `update` | `old_name`, `new_name` | Renames an account. |
| `set_opening_balance` | `account`, `amount` (may be zero/negative) | Overwrites one account's opening balance (`month_key` defaults to current). |

### 🏷️ Categories — `manage_categories` (RO: `list`)

| Action | Needs | Behavior |
|---|---|---|
| `list` | — | All expense/income category names. |
| `add` | `category_name` | Creates a category. Errors if it exists. |
| `update` | `old_name`, `new_name` | Renames a category. |

### 📉 Debts & loans — `manage_debts` (RO: `list`)

| Action | Needs | Behavior |
|---|---|---|
| `list` | — | Active debts with remaining balances, totals, payment status. |
| `add` | `reason`, `total_amount` | New debt/loan (`paidAmount: 0`); category/date defaulted. |
| `update` | `id`, `reason`, `total_amount` | Full replacement (both overwritten). |
| `delete` | `id` | Permanent removal. |
| `pay` | `id`, `amount`, `account` (+ `month_key`, default current) | Partial payment via `sp_pay_long_pending`; creates a linked expense (no `__transfer__` marker). |

### 📅 Months — `manage_months` (RO: `list`)

| Action | Needs | Behavior |
|---|---|---|
| `list` | — | All months with recorded data. |
| `create` | `month_key` (default current), `copy_pending` | Initializes via `sp_create_month`; errors if it exists. |
| `delete` | `month_key` (**required, never defaulted**) | Deletes month + all data. **Irreversible — confirm first.** |

### 📝 Notes — `manage_notes` (RO: `list`)

| Action | Needs | Behavior |
|---|---|---|
| `add` | `title`, `content` | Dated text note. |
| `list` | — | All notes for the month. |
| `delete` | `note_id` | Permanent removal. Notes cannot be edited. |

### 👤 Profile & 🔑 API Tokens

| Tool | RO | Parameters | Description |
|---|---|---|---|
| `manage_profile` | `get` | `action`*, + `name`/`currency_pref`/`default_account` (NAME e.g. `Cash`)/`default_account_id` for `update` | `get` returns `{name, email, phone, currency_pref, default_account_id}`; `update` resolves account NAME→ID. |
| `manage_tokens` | `list` | `action`*, `pat_id` (for `revoke`) | `list` returns token metadata (never raw values); `revoke` takes effect immediately. Token *creation* is web-UI-only (`/api-keys`), never exposed over MCP. |

### Handler → DB mapping

Grouped dispatchers delegate to the original handlers, which map as follows. Computed from `get_month_data`: `get_summary`, `get_account_balances`, `get_last_expense_date`. Read-modify-write via `save_month_data`: expenses, income, pending, transfers, opening balances, notes. Direct DB methods: deletes/updates of expenses (`delete_expense`), accounts, categories, long-pending (`get/add/update/delete_long_pending`, `make_partial_payment`), months (`get_months`, `create_month`, `delete_month`), `sync_bulk_data`, `get_user_by_id`, `update_user`, `list_pats`, `revoke_pat`.

## 6. Resources

| URI | Content |
|---|---|
| `mtracker://accounts` | `db.get_accounts(user_id)` |
| `mtracker://categories` | `db.get_categories(user_id)` |
| `mtracker://debts/active` | `db.get_long_pending(user_id)` |
| `mtracker://schema` | Static table/column map (months, income, paid/pending expenses, opening_balances, notes, long_pending, categories, accounts, users) |

## 7. Client configuration

Claude Desktop speaks stdio, so remote access goes through the `mcp-remote` bridge (requires Node.js); VSCode connects natively over SSE with a static header. The `/mcp-help` page renders both configs live with the deployment's real SSE URL — copy them from there rather than hand-writing:

- **Claude Desktop** (`claude_desktop_config.json`): `{mcpServers: {mtracker: {command: "npx", args: ["-y", "mcp-remote", "<sse-url>", "--header", "Authorization: Bearer mt_live_…"]}}}` — restart the app after saving.
- **VSCode** (`.vscode/mcp.json`): `{servers: {mtracker: {type: "sse", url: "<sse-url>", headers: {Authorization: "Bearer ${input:mtracker-pat}"}}}, inputs: [{type: "promptString", id: "mtracker-pat", password: true, …}]}` — then `MCP: List Servers` → start. No OAuth exists server-side; skip any client-registration prompt.
- **Generic clients**: `GET <sse-url>` (Bearer + `Accept: text/event-stream`) → read `endpoint` event → `POST` JSON-RPC to the given messages URL.

## 8. Security & Privacy

- **Data isolation:** every tool and resource call is filtered by the PAT's `user_id`.
- **Least privilege:** `read` scope exposes only read actions (4 standalone reads + `list`/`get` actions on the grouped tools; see §3); `read_write` unlocks all 16 tools. Grouped `read_actions` fail closed on missing/unknown actions.
- **Audit logging:** all writes logged with `origin='mcp'` (reads are not logged).
- **Token hygiene:** raw values shown once, hashes only at rest, 10-token cap per user, instant revocation, `last_used_at` tracking.
- **Transport:** CSRF-exempt wire routes rely solely on PAT auth; user pages keep session + CSRF.
- **Local-first:** the MCP server runs on the same infrastructure as the app; data leaves only toward the LLM at query time.

## 9. Coverage log & remaining limitations

### v1.1.0 consolidation (38 → 16 tools)

Entity-grouped tools with an `action` enum replaced the flat per-operation
tools; the old names are retired (unknown names return `Tool not found`).
`month_key` defaults to the current month everywhere except
`manage_months/delete`. Read scoping moved from per-tool flags to per-action
`read_actions` (fail-closed). `serverInfo` bumped to `1.1.0`. Token creation
was deliberately left out of `manage_tokens` (list/revoke only) — new tokens
are minted on the `/api-keys` web page so the show-once secret never passes
through model context.

### Completed improvement rounds

- **Daily/personal-expense writes** — `add_daily_expense` (`is_daily_log=TRUE`), now folded into `manage_expenses/add_daily`.
- **Remote bulk import** — `import_bulk` accepts pasted `csv_text` (exactly one of `csv_text`/`file_path`).
- **Pending-item management** — `list_pending_items` / `delete_pending_item`, now folded into `manage_pending`.
- **In-place edits** — `update_expense` (paid + personal, linked-entry guards), `update_income`, `delete_income` (transfer cascade), `delete_note`, now folded into `manage_expenses` / `manage_income` / `manage_notes`.
- **Opening balances** — `set_opening_balance`, now folded into `manage_accounts`.
- **PAT self-service** — `list_pats` / `revoke_pat`, now folded into `manage_tokens` (creation deliberately web-UI-only).
- **Richer reads** — `get_last_expense_date` returns amount/reason/category/account; `get_month_data` accepts a `sections` filter; `month_key` defaults to the current month (except `manage_months/delete`).
- **Token expiry** — `db.create_pat(..., expires_at=...)`, honored by `validate_pat`; exposed via the REST token endpoint (`expires_in_days`).
- **Docstrings** — all handlers carry docstrings; grouped registry descriptions document per-action requirements.

### Deliberately out of scope (not gaps)

- **Auth & identity** (login/register/logout/password/OTP/email/phone/PIN, profile-pic upload): preconditions for MCP access and credential-grade operations — must never flow through AI tools.
- **Admin surface** (user management, SMTP settings, backups, system stats): separate privilege domain from user PATs.
- **Raw `save_month_data` exposure**: full-state overwrite is too dangerous as a model-callable tool; all writes go through validated single-purpose tools.
- **Push/real-time and client-side features** (PDF export, charts): the client renders; MCP supplies the data.

### Genuinely remaining

- **Shared session store** — sessions are in-process memory with a documented single-gthread-worker constraint. Multi-replica/HA deployments need Redis (or sticky sessions) before horizontal scaling.