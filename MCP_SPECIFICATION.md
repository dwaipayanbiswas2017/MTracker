# MTracker Model Context Protocol (MCP) Specification

This document outlines the proposed integration of the Model Context Protocol (MCP) into the MTracker application. This will allow AI agents (like Claude or Gemini) to interact directly with your financial data to provide insights, record transactions, and manage budgets.

## 1. Architecture Overview

The MTracker MCP integration utilizes **HTTP with Server-Sent Events (SSE)** to provide a web-native, stateful connection between the MTracker backend and AI clients.

### 🔄 Data Flow (SSE Transport)
1.  **Connection Establishment:** The client initiates a `GET` request to `/api/mcp/sse`.
2.  **Event Stream:** The server keeps the connection open, sending an `endpoint` event containing the URL for client-to-server POST requests (e.g., `/api/mcp/messages?session_id=...`).
3.  **Client Requests:** The client sends JSON-RPC 2.0 messages via `POST` to the message endpoint.
4.  **Server Responses:** The server processes the request (e.g., querying the DB) and streams the response back via the SSE channel.

### 🏗️ Internal Components
- **Auth Middleware:** Intercepts the `Authorization` header, validates the PAT, and injects the `user_id` into the request context.
- **MCP Router:** Maps JSON-RPC tool calls to specific `DatabaseController` methods.
- **Session Manager:** Tracks active SSE connections and ensures responses are routed to the correct client.

## 2. Authentication Implementation

Authentication is handled via a **Bearer Token** in the HTTP headers of both the initial SSE request and all subsequent message POSTs.

**Example Headers:**
```http
GET /api/mcp/sse HTTP/1.1
Host: mtracker.yourdomain.com
Authorization: Bearer mt_live_xyz123...
Accept: text/event-stream
```

## 3. Client Configuration Sample

To connect an LLM client (like Claude Desktop) to MTracker, use the following configuration in your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mtracker": {
      "url": "https://mtracker.yourdomain.com/api/mcp/sse",
      "env": {
        "MTRACKER_API_KEY": "your_generated_pat_here"
      }
    }
  }
}
```

*Note: The actual client implementation (e.g., using `@modelcontextprotocol/sdk`) will handle the SSE handshake and message passing automatically.*

## 4. Available Functionalities

### 📊 Tools (Actions)
These allow the AI to perform operations on the user's behalf.

#### 💰 Transaction Management
| Tool | Description | Parameters |
| :--- | :--- | :--- |
| `get_summary` | High-level summary (Income, Expense, Balance) for a month. | `month_key` |
| `get_month_data` | Full state of a month (Income, Paid, Pending, Notes). | `month_key` |
| `add_paid_expense` | Record a completed transaction. | `month_key`, `amount`, `reason`, `category`, `account`, `date` |
| `add_income` | Record a new income source. | `month_key`, `amount`, `source`, `account` |
| `add_pending_item` | Add an item to the monthly budget/pending list. | `month_key`, `amount`, `reason`, `category` |
| `transfer_funds` | Move money between accounts (creates linked paid expense + income). | `month_key`, `from_account`, `to_account`, `amount`, `reason` |
| `delete_expense` | Remove an expense (reverses balance if it was a debt payment). | `month_key`, `expense_id` |
| `import_bulk` | Process a CSV file to bulk-save transactions. | `file_path`, `month_key` |

#### 💳 Accounts & Categories
| Tool | Description | Parameters |
| :--- | :--- | :--- |
| `list_accounts` | Fetch all bank accounts and cash buckets. | - |
| `add_account` | Create a new financial account. | `account_name` |
| `update_account` | Rename an existing account. | `old_name`, `new_name` |
| `list_categories` | Fetch all expense/income categories. | - |
| `add_category` | Create a new transaction category. | `category_name` |
| `update_category` | Rename an existing category. | `old_name`, `new_name` |

#### 📉 Long Pending (Debts & Loans)
| Tool | Description | Parameters |
| :--- | :--- | :--- |
| `list_long_pending` | Fetch all active debts/loans and remaining balances. | - |
| `add_long_pending` | Create a new long-term debt/loan entry. | `reason`, `total_amount`, `category`, `date` |
| `update_long_pending`| Update debt details (amount or reason). | `id`, `reason`, `total_amount` |
| `delete_long_pending`| Permanently remove a debt record. | `id` |
| `pay_long_pending` | Record a partial payment towards a debt. | `item_id`, `amount`, `account`, `month_key` |

#### 📝 Notes & Months
| Tool | Description | Parameters |
| :--- | :--- | :--- |
| `list_months` | Get list of all months with data. | - |
| `create_month` | Initialize a new month (with optional carry-forward). | `month_key`, `copy_pending` |
| `delete_month` | Delete an entire month's data. | `month_key` |
| `add_note` | Save a text note for a specific month. | `month_key`, `title`, `content` |

#### 👤 Profile
| Tool | Description | Parameters |
| :--- | :--- | :--- |
| `get_profile` | Get user settings (currency, default account). | - |
| `update_profile` | Update user preferences. | `name`, `currency_pref`, `default_account_id` |

### 📂 Resources (State)
These provide the AI with long-lived context about the user's setup.

- `mtracker://accounts`: List of configured bank accounts/cash buckets.
- `mtracker://categories`: List of active expense and income categories.
- `mtracker://debts/active`: List of all outstanding loans and dues.
- `mtracker://schema`: Structural information about how MTracker stores data.

## 4. Security & Privacy

- **Data Isolation:** All queries are strictly filtered by `user_id`.
- **Read/Write Scopes:** Tokens can be configured as "Read-Only" for safe analysis.
- **Audit Logging:** Every action performed via MCP is logged in the `audit_log` table with an `origin='mcp'` tag.
- **Local First:** The MCP server runs on the same infrastructure as the MTracker app, ensuring data never leaves the controlled environment except for the LLM processing.

## 5. Implementation Notes

The following tools map directly to existing `DatabaseController` methods:

- `get_month_data` → `get_month_data(user_id, month_key)` (line 298)
- `delete_expense` → `delete_expense(user_id, month_key, expense_id)` (line 599)
- `list_accounts` → `get_accounts(user_id)` (line 209)
- `add_account` → `add_account(user_id, account_name)` (line 220)
- `update_account` → `update_account(user_id, old_name, new_name)` (line 233)
- `list_categories` → `get_categories(user_id)` (line 169)
- `add_category` → `add_category(user_id, category_name)` (line 180)
- `update_category` → `update_category(user_id, old_name, new_name)` (line 193)
- `list_long_pending` → `get_long_pending(user_id)` (line 498)
- `add_long_pending` → `add_long_pending(user_id, item_data)` (line 515)
- `update_long_pending` → `update_long_pending(user_id, item_data)` (line 539)
- `delete_long_pending` → `delete_long_pending(user_id, item_id)` (line 562)
- `pay_long_pending` → `make_partial_payment(user_id, item_id, month_key, amount, account, mode)` (line 574)
- `list_months` → `get_months(user_id)` (line 251)
- `create_month` → `create_month(user_id, month_key, copy_pending)` (line 262)
- `delete_month` → `delete_month(user_id, month_key)` (line 284)
- `get_profile` → `get_user_by_id(user_id)` (line 30)
- `update_profile` → `update_user(user_id, ...)` (line 121)

The following tools require **new `DatabaseController` methods** — the codebase currently persists all month data via a full-state sync (`save_month_data`, line 393):

- `get_summary` — no equivalent method; summary must be computed from `get_month_data` response
- `add_paid_expense`, `add_income`, `add_pending_item`, `add_note` — no single-record insert methods exist; each will need either a dedicated `DatabaseController` method or should wrap `save_month_data` (read current state → append → write back)
- `transfer_funds` — requires a new method that inserts a linked paid expense + income pair with a `__transfer__:<ref>` marker in the `notes` column
- `import_bulk` — CSV import exists at `app.py:570` as a file-upload endpoint; the MCP tool should accept a file path and delegate to the same parser logic

## 6. Potential Use Cases

1.  **Conversational Analysis:** *"How much did I spend on groceries in the last 3 months?"*
2.  **Automated Entry:** *"I just spent 450 on fuel via UPI, add it to my current month."*
3.  **Budget Forecasting:** *"Based on my last 6 months of EMI and bills, how much will I likely save next month?"*
4.  **Debt Tracking:** *"What is the remaining balance on my Home Loan?"*

---
*Status: Proposed Integration*  
*Target Version: v4.0*
