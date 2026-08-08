# MTracker — Agent Guide

## Run commands
- Dev: `python app.py` (0.0.0.0:5000)
- Production: `systemctl --user restart mtracker.service` — runs the app in Docker via `docker compose up` (host networking, port 80)
  - Image rebuilt with `sudo docker compose build` (`Dockerfile` + `docker-compose.yml` in repo root)
  - Docker daemon access via passwordless `sudo` (service ExecStart uses `sudo -n docker compose up`)
  - MySQL stays on the host (`host=127.0.0.1` via host networking); DB grants unchanged
- Logs: `sudo docker compose logs -f mtracker`
- Containers: `sudo docker ps`; stop/start stack: `sudo docker compose down/up`

## Stack
Python Flask (single `app.py` + `database_controller.py`), MySQL, jQuery inline in `templates/index.html`, Tailwind CSS (CDN), Chart.js, html2pdf, Lucide icons.

## Key architecture
- **Single-page app**: all JS in `templates/index.html` (~3000 lines). No build step, no bundler.
- **Data flow**: `GET /api/month/<month_id>` fetches full month data into `currentData` JS object. Mutations modify `currentData` locally, then `POST /api/save` persists full state.
- **Paid vs Daily expenses**: both live in `paid_expenses` table, differentiated by `is_daily_log` boolean.
  - `paidExpenses` → `is_daily_log = FALSE`
  - `personalExpenses` → `is_daily_log = TRUE`
- **Opening balances**: dict of `{account_name: amount}` or legacy float.
- **`totalPaidDisplay`** = sum of `paidExpenses` + `personalExpenses`.
- **Charts**: doughnut chart aggregating both paid + personal expenses by category.

## Database
Schema in `database/mtracker_schema.sql`. Key tables: `users`, `accounts`, `categories`, `months`, `opening_balances`, `income`, `paid_expenses`, `pending_expenses`, `long_pending`, `notes`. Stored procedures: `sp_create_month`, `sp_pay_pending_expense`, `sp_pay_long_pending`.

## Conventions
- All item IDs are JS timestamps (`Date.now()` stringified).
- Opening balance per-account: update via inline input `onchange="updateOpeningBalance('AccountName', value)"`.
- Categories and accounts: full CRUD via `/api/categories` and `/api/accounts`.
- No tests, no linting, no type checking configured.

## Directories
- `templates/` — 8 Jinja2 templates (main UI is `index.html`)
- `static/uploads/profile_pics/` — user avatars
- `database/` — SQL schema
