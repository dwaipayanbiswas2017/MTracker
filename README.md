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
3.  **Run the application**:
    ```bash
    python app.py
    ```
4.  **Access the app**:
    Open your browser and go to `http://localhost:5000`.

## Usage

1.  **Register/Login**: Create an account to start tracking.
2.  **Create a Month**: Start a new month to begin tracking transactions.
3.  **Add Accounts**: Go to "Manage Accounts" to add your bank accounts.
4.  **Add Transactions**: Record income, paid expenses, and personal expenses.
5.  **View Reports**: Check the dashboard for real-time balance updates or export a PDF report.

## License

This project is for personal use.
