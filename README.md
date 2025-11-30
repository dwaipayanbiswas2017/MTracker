# MTracker

MTracker is a personal finance management application designed to help you track your income, expenses, and budget across multiple bank accounts.

## Features

-   **Multi-Account Support**: Track expenses and income for different accounts (e.g., Cash, Bank, Credit Card).
-   **Monthly Tracking**: Create and manage monthly budgets.
-   **Expense Categorization**: Categorize your expenses (e.g., Food, Bills, EMI).
-   **Long Pending Payments**: Track and manage long-term debts or payments.
-   **PDF Export**: Generate monthly statements in PDF format.
-   **CSV Import**: Import transaction data from CSV files.
-   **Dark/Light Mode**: Toggle between dark and light themes.
-   **User Authentication**: Secure login and registration system.

## Updated Features

-   **Long Pending Payments**: Track long-term debts, make partial payments, and link them to monthly expenses.
-   **Month Auto-Creation**: Automatically create a new month with balances carried forward from the previous month.
-   **CSV Import**: Enhanced parsing logic for importing transactions, including income, expenses, and pending payments.
-   **Expense Deletion**: Delete expenses and reverse linked long-pending payments.

## API Endpoints

### Authentication
-   **`/login`**: Login route (GET/POST).
-   **`/register`**: Register route (GET/POST).
-   **`/logout`**: Logout route (GET).

### Categories
-   **`/api/categories`**: Get all categories (GET).
-   **`/api/categories`**: Add a new category (POST).

### Accounts
-   **`/api/accounts`**: Get all accounts (GET).
-   **`/api/accounts`**: Add a new account (POST).

### Months
-   **`/api/months`**: Get all months (GET).
-   **`/api/month/<month_id>`**: Get data for a specific month (GET).
-   **`/api/create_month`**: Create a new month (POST).
-   **`/api/delete_month`**: Delete a month (POST).

### Transactions
-   **`/api/save`**: Save data for a specific month (POST).
-   **`/api/import`**: Import transactions from a CSV file (POST).
-   **`/api/month/<month_id>/expense/<expense_id>`**: Delete an expense (DELETE).

### Long Pending Payments
-   **`/api/long_pending`**: Get all long-pending payments (GET).
-   **`/api/long_pending`**: Add a new long-pending payment (POST).
-   **`/api/long_pending/<item_id>`**: Delete a long-pending payment (DELETE).
-   **`/api/long_pending/<item_id>/partial_payment`**: Make a partial payment for a long-pending item (POST).

## Tech Stack

-   **Backend**: Python, Flask
-   **Frontend**: HTML, Tailwind CSS, jQuery
-   **Data Storage**: JSON files (per user)

## Setup & Installation

1.  **Clone the repository** (or download the source code).
2.  **Install dependencies**:
    ```bash
    pip install flask flask-login
    ```
3.  **Create necessary directories and files**:
    ```bash
    mkdir data
    echo {} > users.json
    ```
4.  **Run the application**:
    ```bash
    python app.py
    ```
5.  **Access the app**:
    Open your browser and go to `http://localhost:5000`.

## Usage

1.  **Register/Login**: Create an account to start tracking.
2.  **Create a Month**: Start a new month to begin tracking transactions.
3.  **Add Accounts**: Go to "Manage Accounts" to add your bank accounts.
4.  **Add Transactions**: Record income, paid expenses, and personal expenses.
5.  **View Reports**: Check the dashboard for real-time balance updates or export a PDF report.

## License

This project is for personal use.
