# MTracker

MTracker is a professional personal finance management application designed to help you track your income, expenses, and budget across multiple bank accounts.

**Live at [`https://mtracker.in`](https://mtracker.in)**

## Features

-   **Multi-Account Support**: Track expenses and income for different accounts (e.g., Cash, Bank, Credit Card) with an All/Default view toggle.
-   **Monthly Tracking**: Create and manage monthly budgets and transactions.
-   **Expense Categorization**: Categorize your expenses (e.g., Food, Bills, EMI) with full CRUD support.
-   **Fund Transfer**: Move money between accounts in a single operation — creates a debit (paid expense) in the source and a credit (income) in the destination. Deleting either side auto-removes the linked entry.
-   **Expense Analysis Chart**: Doughnut chart aggregating expenses by category, filterable to the default account for focused analysis.
-   **Personal Budget Tracking**: Mark any pending budget as "personal" to auto-reduce it against daily expenses, showing remaining vs. original amounts.
-   **Long Pending Payments**: Track and manage long-term debts with partial payment support linked to monthly cycles.
-   **Password Recovery**: Secure password reset flow using OTP verification via email for lost credentials.
-   **CSV Import**: Batch import transaction data from CSV files for rapid entry.
-   **PDF Export**: Generate professional monthly statements in PDF format with automatic charts.
-   **Profile Management**: Update profile pictures, manage contact info with OTP verification, and set currency/account preferences.
-   **Admin Panel & System Settings**: Global oversight with user management, system-wide SMTP configuration, and database backup management via a dedicated dashboard.
-   **Database Backup & Restore**: Create manual backups, schedule automatic daily backups (configurable time), restore from any backup file, download backups, and email backup files to admin users — all from the admin panel.
-   **AI Assistant**: Built-in AI chat assistant (floating chat widget) powered by NVIDIA AI models that answers questions about your financial data using natural language.
-   **MCP Server (v1.1.0)**: Model Context Protocol (MCP) server with 16 grouped tools (`manage_*` with `action` verbs) and PAT-based authentication. `mcp_server.py` is the single source of truth for all tools — both the Pydantic AI chat agent (in-process MCP) and over-the-wire MCP clients (SSE: Claude Desktop via `mcp-remote`, VSCode, generic clients) consume the same registry. `month_key` defaults to the current month; `read`-scoped tokens are limited to per-action read operations.
-   **API Keys Page**: Self-service Personal Access Token management at `/api-keys` — create (including expiry), list, and revoke tokens from the UI.
-   **MCP Help Page**: Setup guide with copy-paste client configs plus a live tool/resource reference rendered from the server registry at `/mcp-help`.
-   **Modern Dynamic UI**: Clean, tactile interface with a consistent theme engine supporting Light and Dark modes. Password visibility toggle on login/register.
-   **Secure Authentication**: Role-based access control with secure password hashing and dual-identifier (Email/Phone) login.

## API Endpoints

### Authentication
-   **`/login`**: Secure login (GET/POST).
-   **`/register`**: New user registration (GET/POST).
-   **`/logout`**: Session termination (GET).
-   **`/forgot_password`**: Password recovery initiation (GET).
-   **`/api/forgot_password/send`**: Send OTP for password reset (POST).
-   **`/api/forgot_password/reset`**: Verify OTP and update password (POST).
-   **`/api/verify_password`**: Internal identity verification (POST).
-   **`/api/send_otp`**: OTP generation for contact updates or security (POST).
-   **`/api/verify_otp`**: OTP verification for sensitive profile changes (POST).

### Dashboard & Data
-   **`/api/categories`**: CRUD operations for user categories (GET/POST).
-   **`/api/categories/update`**: Rename existing categories (POST).
-   **`/api/accounts`**: CRUD operations for user bank accounts (GET/POST).
-   **`/api/accounts/update`**: Rename existing accounts (POST).
-   **`/api/months`**: Retrieve list of managed months (GET).
-   **`/api/month/<month_id>`**: Comprehensive month-over-month data retrieval (GET).
-   **`/api/save`**: Persistent storage for monthly transaction blocks (POST).
-   **`/api/create_month`**: Scaffolding for new monthly cycles (POST).
-   **`/api/delete_month`**: Complete removal of a monthly cycle (POST).

### Transactions & Payments
-   **`/api/import`**: Bulk ingestion from external CSV sources (POST).
-   **`/api/month/<month_id>/expense/<expense_id>`**: Targeted transaction deletion (DELETE).
-   **`/api/long_pending`**: High-level debt overview (GET/POST).
-   **`/api/long_pending/<item_id>`**: Remove a debt track (DELETE).
-   **`/api/long_pending/<item_id>/partial_payment`**: Record partial debt clearances (POST).

### AI Assistant
-   **`/api/chat`**: Send a natural language query about your finances and get an AI-generated response (POST).

### MCP Server (Model Context Protocol)

Production base URL: `https://mtracker.in` (e.g. SSE stream at `https://mtracker.in/api/mcp/sse`).

-   **`/api-keys`**: Self-service API key management page — create, list, and revoke Personal Access Tokens (GET).
-   **`/mcp-help`**: MCP setup guide and live tool/resource reference for users (GET).
-   **`/api/mcp/sse`**: SSE stream endpoint for MCP client connections (GET).
-   **`/api/mcp/messages`**: JSON-RPC message endpoint for MCP client requests (POST).
-   **`/api/mcp/tokens`**: Create (accepts optional `expires_in_days`) and list Personal Access Tokens for MCP auth (GET/POST).
-   **`/api/mcp/tokens/<pat_id>`**: Revoke a Personal Access Token (DELETE).

### MCP Tools (v1.1.0)

Grouped by entity — each `manage_*` tool takes an `action` verb (only `action` is schema-required; per-action fields are validated at runtime). `month_key` defaults to the current month everywhere except `manage_months/delete`, which requires it explicitly. `R` marks actions available to `read`-scoped tokens.

| Tool | Actions | Description |
|---|---|---|
| `get_summary` | — (R) | Monthly totals: income, expenses, balances, counts. |
| `get_month_data` | — (R) | Full month state, with optional `sections` filter. |
| `get_account_balances` | — (R) | Per-account running balances. |
| `get_last_expense_date` | — (R) | Latest expense with date, amount, reason, category, account. |
| `manage_expenses` | `add_paid`, `add_daily`, `update`, `delete` | Regular + daily spends, in-place edits (linked entries blocked), cascade-aware deletes. |
| `manage_income` | `add`, `update`, `delete` | Income entries; delete cascades linked transfer expenses. |
| `manage_pending` | `add`, `list` (R), `delete` | Planned/unpaid budget items. |
| `manage_accounts` | `list` (R), `add`, `update`, `set_opening_balance` | Accounts incl. per-account opening balances. |
| `manage_categories` | `list` (R), `add`, `update` | Expense/income categories. |
| `manage_debts` | `list` (R), `add`, `update`, `delete`, `pay` | Debts/loans with partial payments linked to a month. |
| `manage_months` | `list` (R), `create`, `delete` | Month lifecycle (`copy_pending` supported; delete is irreversible). |
| `manage_notes` | `add`, `list` (R), `delete` | Month notes (delete + re-add to change). |
| `manage_profile` | `get` (R), `update` | Name, currency, default account (name or ID). |
| `manage_tokens` | `list` (R), `revoke` | Token metadata + revocation (creation is web-UI-only). |
| `transfer_funds` | — | Linked expense + income pair between accounts. |
| `import_bulk` | — | CSV import via pasted `csv_text` or server-side `file_path`. |

### Administration & Settings
-   **`/admin`**: Global dashboard overview for system administrators (GET).
-   **`/admin/toggle_user/<user_id>`**: Enable/Disable system access (POST).
-   **`/admin/toggle_admin/<user_id>`**: Promote/Demote administrative rights (POST).
-   **`/admin/delete_user/<user_id>`**: Permanent cascading deletion of user data (POST).
-   **`/api/admin/settings/mail`**: Manage system-wide SMTP settings (GET/POST).
-   **`/api/admin/settings/mail/test`**: Verify SMTP configuration with a test email (POST).
-   **`/admin/backup`**: Create a manual database backup (POST).
-   **`/admin/backups`**: List all backup files (GET).
-   **`/admin/backup/<filename>/download`**: Download a backup file (GET).
-   **`/admin/backup/<filename>/restore`**: Restore the database from a backup (POST).
-   **`/admin/backup/<filename>/delete`**: Delete a backup file (POST).
-   **`/admin/backup/<filename>/email`**: Email a backup file to all admin users (POST).
-   **`/admin/backup/schedule`**: Get or set the automatic backup schedule (GET/POST).
-   **`/admin/backup/check-schedule`**: Manually trigger a scheduled backup check (POST).

## Tech Stack

-   **Backend**: Python 3.x, Flask (Web Framework), Gunicorn (Production WSGI)
-   **Frontend**: HTML5, Tailwind CSS (CDN), jQuery (AJAX & DOM), Lucide (Icons), Chart.js, html2pdf
-   **Database**: MySQL 8.0+ (Transactions, Users, Persistent State)
-   **Authentication & Mail**: Flask-Login, Flask-WTF (CSRF), smtplib (Email)
-   **AI Agent**: Pydantic AI, NVIDIA AI API, SSE Streaming
-   **MCP**: Model Context Protocol (SSE transport, JSON-RPC 2.0, PAT auth)

## Setup & Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/dwaipayanbiswas2017/MTracker.git
    cd MTracker
    ```

2.  **Initialize Environment**:
    Create a `.env` file in the root directory with the following variables:
    ```env
    host=localhost
    user=your_db_user
    password=your_db_password
    database=mtracker
    NVIDIA_API_KEY=your_nvidia_key_here
    FLASK_SECRET_KEY=your_random_secret_here
    ```

3.  **Install dependencies**:
    It is recommended to use a virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

4.  **Database Setup**:
    Initialize your MySQL database using the schema provided in `database/mtracker_schema.sql`.

5.  **Run the application**:
    For development:
    ```bash
    python app.py
    ```
    For production, use Gunicorn with a **single gthread worker** (required: MCP SSE sessions live in process memory, so multiple sync workers break MCP clients):
    ```bash
    gunicorn --bind 0.0.0.0:80 --worker-class gthread --workers 1 --threads 16 --timeout 300 app:app
    ```

## Docker Deployment (Recommended)

The app ships with a `Dockerfile` and `docker-compose.yml` (host networking so the container reaches MySQL on the host; persistent volumes for profile pictures and backups):

```bash
sudo docker compose up -d --build
```

### `deploy.sh` — rebuild, redeploy, verify

`deploy.sh` automates the full rollout: rebuilds the image, redeploys the service, waits for readiness, and verifies the new code is live:

```bash
./deploy.sh                # rebuild + redeploy + verify (default)
./deploy.sh --no-build     # restart only, no rebuild
./deploy.sh --logs         # follow logs after a successful deploy
./deploy.sh --timeout 120  # seconds to wait for readiness (default 90)
```

Verification checks: `200` on `/login`, `401` on `/api/mcp/sse` (auth gate = MCP code serving), `302` on `/api-keys` and `/mcp-help` (login redirect = routes registered). Always redeploy with `./deploy.sh` (not a plain restart) after changing Python code or templates, since both are baked into the image.

## Production Deployment (Auto-start on Boot)

To ensure MTracker starts automatically on boot, a `systemd` service is provided:

1.  **Prepare User-level Service Directory**:
    ```bash
    mkdir -p ~/.config/systemd/user/
    ```

2.  **Copy Service File**:
    ```bash
    cp mtracker.service ~/.config/systemd/user/
    ```

3.  **Enable and Start Service**:
    ```bash
    systemctl --user daemon-reload
    systemctl --user enable mtracker.service
    systemctl --user start mtracker.service
    ```

4.  **Enable Lingering**:
    To allow the service to run without an active session:
    ```bash
    loginctl enable-linger $USER
    ```

5.  **Check Status**:
    ```bash
    systemctl --user status mtracker.service
    ```

> **Note:** `mtracker.service` runs stock Gunicorn defaults. For MCP SSE to work under systemd, its `ExecStart` must use the same single-gthread-worker flags as the `Dockerfile` (`--worker-class gthread --workers 1 --threads 16`). The Docker deployment above already does this and is the recommended production path.

## Initial Configuration
    - Visit `https://mtracker.in` to register (or `http://localhost:5000` when running locally).
    - If you are an admin, configure SMTP settings in the Admin Panel to enable email features like OTP and Password Recovery.
    - For the AI Assistant to work, set your NVIDIA AI API key in the `.env` file: `NVIDIA_API_KEY=your_key_here`.

## Usage

1.  **Register/Login**: Start by creating an account. The first registered user can be manually promoted to admin via the database if needed.
2.  **Initialize Months**: Create a "New Month" to start tracking. Balances are automatically calculated and carried forward.
3.  **Configure Accounts**: Add your bank accounts or physical wallets in the "Accounts" section. Set a default account in Profile for chart filtering and auto-selection.
4.  **Manage Transactions**: Use the dashboard to record income, expenses, track pending items, and transfer funds between accounts via the Transfer button in the balance card.
5.  **Analyze & Export**: Use the built-in Expense Analysis chart (toggle All/Default view) for visual analysis or export a professional PDF report for your records.
6.  **Backup**: Use the Admin Panel to create manual backups, schedule automatic daily backups, restore from backups, or email backups to admin users.
7.  **AI Assistant**: Click the chat button (bottom-right) to ask natural language questions about your finances.

## License

This project is for private use only. All rights reserved. &copy; 2026 MTracker Systems.
