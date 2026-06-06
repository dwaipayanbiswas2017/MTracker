# GEMINI.md - MTracker Project Context

## Project Overview
MTracker is a professional personal finance management application designed to track income, expenses, and budgets across multiple bank accounts. It provides a modern, dynamic UI for financial management with features like CSV import, PDF export, and long-term debt tracking.

### Tech Stack
- **Backend:** Python 3.x, Flask (Web Framework)
- **Frontend:** HTML5, Tailwind CSS, jQuery, Lucide Icons, Chart.js
- **Database:** MySQL 8.0+
- **Authentication & Mail:** Flask-Login, Flask-Mail, Werkzeug

### Architecture
The project follows a classic Flask application structure:
- `app.py`: Entry point and route handlers.
- `database_controller.py`: Encapsulates all MySQL database operations.
- `templates/`: Jinja2 templates for the UI (including password recovery).
- `static/`: Static assets (uploads, profile pictures).
- `database/mtracker_schema.sql`: Database schema definition and system settings.

## Building and Running
### Prerequisites
- Python 3.x
- MySQL Server
- `.env` file with database credentials (host, user, password, database)

### Setup
1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Database Initialization:**
   Run the SQL script provided in `database/mtracker_schema.sql` to set up the database structure.
3. **Run Application:**
   ```bash
   python app.py
   ```
   The application will be accessible at `http://localhost:5000`.

## Development Conventions
### Code Style
- **Python:** Follow PEP 8 guidelines. Use `DatabaseController` for all database interactions.
- **JavaScript:** jQuery is used for AJAX and DOM manipulation. Avoid vanilla JS if it complicates existing patterns.
- **CSS:** Tailwind CSS is used for styling. Prefer utility classes over custom CSS where possible.

### Database Operations
- All database logic must reside in `database_controller.py`.
- Use MySQL stored procedures for complex operations (e.g., `sp_create_month`, `sp_pay_long_pending`).
- Transactions are managed by the controller to ensure data integrity.

### API Standards
- Routes return JSON for API calls and render HTML for page loads.
- Use `@login_required` for all protected routes.
- Follow existing naming conventions for API endpoints (e.g., `/api/save`, `/api/categories`).

### UI/UX
- Support for both Light and Dark modes is implemented via Tailwind's `dark` class.
- Use Lucide icons for consistency.
- Interactive charts are powered by Chart.js.

## Key Files
- `app.py`: Main application logic and routing.
- `database_controller.py`: Database access layer.
- `database/mtracker_schema.sql`: Full database schema and stored procedures.
- `templates/index.html`: Main dashboard template.
- `requirements.txt`: Project dependencies.
