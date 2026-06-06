# MTracker

MTracker is a professional personal finance management application designed to help you track your income, expenses, and budget across multiple bank accounts.

## Features

-   **Multi-Account Support**: Track expenses and income for different accounts (e.g., Cash, Bank, Credit Card).
-   **Monthly Tracking**: Create and manage monthly budgets and transactions.
-   **Expense Categorization**: Categorize your expenses (e.g., Food, Bills, EMI) with full CRUD support.
-   **Long Pending Payments**: Track and manage long-term debts with partial payment support linked to monthly cycles.
-   **Password Recovery**: Secure password reset flow using OTP verification via email for lost credentials.
-   **CSV Import**: Batch import transaction data from CSV files for rapid entry.
-   **PDF Export**: Generate professional monthly statements in PDF format with automatic charts.
-   **Profile Management**: Update profile pictures, manage contact info with OTP verification, and set currency/account preferences.
-   **Admin Panel & System Settings**: Global oversight with user management and system-wide configuration (e.g., SMTP settings) via a dedicated dashboard.
-   **Modern Dynamic UI**: Clean, tactile interface with a consistent theme engine supporting Light and Dark modes.
-   **Secure Authentication**: Role-based access control with secure password hashing and dual-identifier (Email/Phone) login.

## API Endpoints

### Authentication
-   **`/login`**: Secure login (GET/POST).
-   **`/register`**: New user registration (GET/POST).
-   **`/logout`**: Session termination (GET).
-   **`/forgot_password`**: Password recovery initiation (GET).
-   **`/api/forgot_password/send`**: Send OTP for password reset (POST).
-   **`/api/forgot_password/verify`**: Verify OTP and update password (POST).
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

### Administration & Settings
-   **`/admin`**: Global dashboard overview for system administrators (GET).
-   **`/admin/toggle_user/<user_id>`**: Enable/Disable system access (POST).
-   **`/admin/toggle_admin/<user_id>`**: Promote/Demote administrative rights (POST).
-   **`/admin/delete_user/<user_id>`**: Permanent cascading deletion of user data (POST).
-   **`/api/admin/settings/mail`**: Manage system-wide SMTP settings (GET/POST).
-   **`/api/admin/settings/mail/test`**: Verify SMTP configuration with a test email (POST).

## Tech Stack

-   **Backend**: Python 3.x, Flask (Web Framework)
-   **Frontend**: HTML5, Tailwind CSS (Styling), jQuery (AJAX & DOM), Lucide (Icons)
-   **Database**: MySQL 8.0+ (Transactions, Users, Persistent State)
-   **Authentication & Mail**: Flask-Login, Flask-Mail, Werkzeug (Security)

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
    For production, use Gunicorn:
    ```bash
    gunicorn --bind 0.0.0.0:5000 app:app
    ```

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

## Initial Configuration
    - Visit `http://localhost:5000` to register.
    - If you are an admin, configure SMTP settings in the Admin Panel to enable email features like OTP and Password Recovery.

## Usage

1.  **Register/Login**: Start by creating an account. The first registered user can be manually promoted to admin via the database if needed.
2.  **Initialize Months**: Create a "New Month" to start tracking. Balances are automatically calculated and carried forward.
3.  **Configure Accounts**: Add your bank accounts or physical wallets in the "Accounts" section.
4.  **Manage Transactions**: Use the dashboard to record income, expenses, and track pending items.
5.  **Analyze & Export**: Use the built-in charts for visual analysis or export a professional PDF report for your records.

## License

This project is for private use only. All rights reserved. &copy; 2026 MTracker Systems.
