import mysql.connector
from mysql.connector import Error
from datetime import datetime
import json

class DatabaseController:
    """
    DatabaseController handles all MySQL database operations for the MTracker application.
    It encapsulates the logic for user management, monthly transactions, categories,
    accounts, and long-pending payments, transitioning from JSON storage to SQL.
    """

    def __init__(self, config):
        """
        Initialize the database controller with configuration.
        :param config: Dictionary containing 'host', 'user', 'password', and 'database'
        """
        self.config = config

    def get_connection(self):
        """Creates and returns a new database connection."""
        try:
            return mysql.connector.connect(**self.config)
        except Error as e:
            print(f"Error connecting to MySQL: {e}")
            return None

    # --- User Management ---

    def get_user_by_id(self, user_id):
        """
        Retrieves a user by their unique ID.
        :param user_id: The unique ID of the user.
        :return: Dict containing user data or None if not found.
        """
        conn = self.get_connection()
        if not conn: return None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE id = %s AND is_active = TRUE", (user_id,))
            return cursor.fetchone()
        finally:
            conn.close()

    def get_user_by_identifier(self, identifier):
        """
        Retrieves a user by their email or phone.
        :param identifier: The login identifier.
        :return: Dict containing user data or None if not found.
        """
        conn = self.get_connection()
        if not conn: return None
        try:
            cursor = conn.cursor(dictionary=True)
            query = "SELECT * FROM users WHERE (email = %s OR phone = %s) AND is_active = TRUE"
            cursor.execute(query, (identifier, identifier))
            return cursor.fetchone()
        finally:
            conn.close()

    def create_user(self, user_id, name, password_hash, email=None, phone=None, registration_method='email'):
        """
        Creates a new user record in the database.
        :param user_id: Unique identifier for the user.
        :param name: Full name of the user.
        :param password_hash: PBKDF2 hashed password string.
        :param email: Optional email address.
        :param phone: Optional phone number.
        :param registration_method: 'email' or 'phone'.
        """
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            query = "INSERT INTO users (id, name, password_hash, email, phone, registration_method) VALUES (%s, %s, %s, %s, %s, %s)"
            cursor.execute(query, (user_id, name, password_hash, email, phone, registration_method))
            conn.commit()
            return True
        except Error as e:
            print(f"Error creating user: {e}")
            return False
        finally:
            conn.close()

    def update_user(self, user_id, name=None, email=None, phone=None, profile_pic_path=None, currency_pref=None, default_account_id=None, password_hash=None):
        """
        Updates user profile information.
        """
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            updates = []
            params = []
            if name:
                updates.append("name = %s")
                params.append(name)
            if email:
                updates.append("email = %s")
                params.append(email)
            if phone:
                updates.append("phone = %s")
                params.append(phone)
            if profile_pic_path is not None:
                updates.append("profile_pic_path = %s")
                params.append(profile_pic_path)
            if currency_pref:
                updates.append("currency_pref = %s")
                params.append(currency_pref)
            if default_account_id:
                updates.append("default_account_id = %s")
                params.append(default_account_id)
            if password_hash:
                updates.append("password_hash = %s")
                params.append(password_hash)

            if not updates:
                return True

            query = f"UPDATE users SET {', '.join(updates)} WHERE id = %s"
            params.append(user_id)
            cursor.execute(query, tuple(params))
            conn.commit()
            return True
        except Error as e:
            print(f"Error updating user: {e}")
            return False
        finally:
            conn.close()

    # --- Categories & Accounts ---

    def get_categories(self, user_id):
        """Retrieves all active expense/income categories for a specific user."""
        conn = self.get_connection()
        if not conn: return []
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT category_name FROM categories WHERE user_id = %s AND is_active = TRUE ORDER BY display_order, category_name", (user_id,))
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    def add_category(self, user_id, category_name):
        """Adds a new category for a user if it doesn't already exist."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            query = "INSERT IGNORE INTO categories (user_id, category_name) VALUES (%s, %s)"
            cursor.execute(query, (user_id, category_name))
            conn.commit()
            return True
        finally:
            conn.close()

    def update_category(self, user_id, old_name, new_name):
        """Updates a category name for a user."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            query = "UPDATE categories SET category_name = %s WHERE user_id = %s AND category_name = %s AND is_active = TRUE"
            cursor.execute(query, (new_name, user_id, old_name))
            conn.commit()
            return cursor.rowcount > 0
        except Error as e:
            print(f"Error updating category: {e}")
            return False
        finally:
            conn.close()

    def get_accounts(self, user_id):
        """Retrieves all active bank/cash accounts for a specific user."""
        conn = self.get_connection()
        if not conn: return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT id, account_name, account_type FROM accounts WHERE user_id = %s AND is_active = TRUE ORDER BY display_order, account_name", (user_id,))
            return cursor.fetchall()
        finally:
            conn.close()

    def add_account(self, user_id, account_name):
        """Adds a new financial account for a user if it doesn't already exist."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            query = "INSERT IGNORE INTO accounts (user_id, account_name) VALUES (%s, %s)"
            cursor.execute(query, (user_id, account_name))
            conn.commit()
            return True
        finally:
            conn.close()

    def update_account(self, user_id, old_name, new_name):
        """Updates an financial account name for a user."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            query = "UPDATE accounts SET account_name = %s WHERE user_id = %s AND account_name = %s AND is_active = TRUE"
            cursor.execute(query, (new_name, user_id, old_name))
            conn.commit()
            return cursor.rowcount > 0
        except Error as e:
            print(f"Error updating account: {e}")
            return False
        finally:
            conn.close()

    # --- Months Management ---

    def get_months(self, user_id):
        """Retrieves all month keys (YYYY-MM) recorded for a user."""
        conn = self.get_connection()
        if not conn: return []
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT month_key FROM months WHERE user_id = %s ORDER BY month_key", (user_id,))
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    def create_month(self, user_id, month_key, copy_pending=False):
        """
        Initializes a new month using a stored procedure that handles carry-forward logic.
        :param user_id: The ID of the user.
        :param month_key: Month identifier (e.g., '2025-11').
        :param copy_pending: If True, pending expenses from the previous month are copied.
        """
        conn = self.get_connection()
        if not conn: return None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.callproc('sp_create_month', (user_id, month_key, copy_pending))
            # sp_create_month returns the new record's internal ID
            res = None
            for result in cursor.stored_results():
                res = result.fetchone()

            conn.commit() # Ensure the new month and copied items are saved
            return res
        finally:
            conn.close()

    def delete_month(self, user_id, month_key):
        """Deletes a monthly record and all associated transactions (cascading)."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM months WHERE user_id = %s AND month_key = %s", (user_id, month_key))
            conn.commit()
            return True
        finally:
            conn.close()

    # --- Transaction Data (The "load_data" logic) ---

    def get_month_data(self, user_id, month_key):
        """
        Assembles a comprehensive data object for a specific month, mimicking the JSON structure.
        :return: Dict containing income, openingBalance, paidExpenses, personalExpenses, pendingExpenses.
        """
        conn = self.get_connection()
        if not conn: return {}
        try:
            cursor = conn.cursor(dictionary=True)

            # 1. Get month internal ID
            cursor.execute("SELECT id FROM months WHERE user_id = %s AND month_key = %s", (user_id, month_key))
            month_row = cursor.fetchone()
            if not month_row: return None
            month_id = month_row['id']

            # 2. Get Opening Balances (Mapping account_id back to account_name)
            query_ob = """
                SELECT a.account_name, ob.amount
                FROM opening_balances ob
                JOIN accounts a ON ob.account_id = a.id
                WHERE ob.month_id = %s
            """
            cursor.execute(query_ob, (month_id,))
            opening_balance = {row['account_name']: float(row['amount']) for row in cursor.fetchall()}

            # 3. Get Income
            query_inc = """
                SELECT i.id, i.source, i.amount, a.account_name as account
                FROM income i
                JOIN accounts a ON i.account_id = a.id
                WHERE i.month_id = %s
            """
            cursor.execute(query_inc, (month_id,))
            income = cursor.fetchall()
            for r in income: r['amount'] = float(r['amount'])

            # 4. Get Paid Expenses
            query_pe = """
                SELECT pe.id, pe.reason, pe.amount, pe.expense_date as date,
                       c.category_name as category, a.account_name as account,
                       pe.is_long_pending, pe.linked_long_pending_id as linkedId
                FROM paid_expenses pe
                JOIN categories c ON pe.category_id = c.id
                LEFT JOIN accounts a ON pe.account_id = a.id
                WHERE pe.month_id = %s
            """
            cursor.execute(query_pe, (month_id,))
            paid_expenses = cursor.fetchall()
            for r in paid_expenses:
                r['amount'] = float(r['amount'])
                r['date'] = r['date'].strftime('%Y-%m-%d')

            # 5. Get Personal Expenses
            query_pers = """
                SELECT p.id, p.reason, p.amount, p.expense_date as date, a.account_name as account
                FROM personal_expenses p
                JOIN accounts a ON p.account_id = a.id
                WHERE p.month_id = %s
            """
            cursor.execute(query_pers, (month_id,))
            personal_expenses = cursor.fetchall()
            for r in personal_expenses:
                r['amount'] = float(r['amount'])
                r['date'] = r['date'].strftime('%Y-%m-%d')

            # 6. Get Pending Expenses
            query_pend = """
                SELECT p.id, p.reason, p.amount, p.payment_mode as mode, c.category_name as category, p.status
                FROM pending_expenses p
                JOIN categories c ON p.category_id = c.id
                WHERE p.month_id = %s AND p.status = 'pending'
            """
            cursor.execute(query_pend, (month_id,))
            pending_expenses = cursor.fetchall()
            for r in pending_expenses: r['amount'] = float(r['amount'])

            # 7. Get Notes
            cursor.execute("SELECT id, title, content, note_date as date FROM notes WHERE month_id = %s", (month_id,))
            notes = cursor.fetchall()
            for r in notes: r['date'] = r['date'].strftime('%Y-%m-%d')

            return {
                "income": income,
                "openingBalance": opening_balance,
                "paidExpenses": paid_expenses,
                "personalExpenses": personal_expenses,
                "pendingExpenses": pending_expenses,
                "notes": notes
            }
        finally:
            conn.close()

    def save_month_data(self, user_id, month_key, data):
        """
        Synchronizes a month's data from the UI state to the database.
        Note: This implementation clears and re-inserts transaction data to ensure consistency
        with the current JSON-based API behavior of sending the full state.
        """
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor(dictionary=True)

            # Get internal IDs
            cursor.execute("SELECT id FROM months WHERE user_id = %s AND month_key = %s", (user_id, month_key))
            month_row = cursor.fetchone()
            if not month_row: return False
            month_id = month_row['id']

            # Lookup helper to convert names to IDs
            cursor.execute("SELECT id, account_name FROM accounts WHERE user_id = %s", (user_id,))
            account_map = {r['account_name']: r['id'] for r in cursor.fetchall()}
            cursor.execute("SELECT id, category_name FROM categories WHERE user_id = %s", (user_id,))
            category_map = {r['category_name']: r['id'] for r in cursor.fetchall()}

            # 1. Update Opening Balances
            cursor.execute("DELETE FROM opening_balances WHERE month_id = %s", (month_id,))
            ob_data = data.get('openingBalance', {})
            for acc_name, amount in ob_data.items():
                if acc_name in account_map:
                    cursor.execute("INSERT INTO opening_balances (user_id, month_id, account_id, amount) VALUES (%s, %s, %s, %s)",
                                 (user_id, month_id, account_map[acc_name], amount))

            # 2. Update Income
            cursor.execute("DELETE FROM income WHERE month_id = %s", (month_id,))
            for item in data.get('income', []):
                acc_id = account_map.get(item.get('account'), account_map.get('Cash'))
                if acc_id:
                    cursor.execute("INSERT INTO income (id, user_id, month_id, account_id, source, amount) VALUES (%s, %s, %s, %s, %s, %s)",
                                 (str(item['id']), user_id, month_id, acc_id, item['source'], item['amount']))

            # 3. Update Paid Expenses
            # Note: We avoid deleting records that are linked to Long Pending to maintain history integrity
            cursor.execute("DELETE FROM paid_expenses WHERE month_id = %s AND is_long_pending = FALSE", (month_id,))
            for item in data.get('paidExpenses', []):
                if item.get('isLongPending'): continue # Skip long pending payments as they are managed via specific API
                acc_id = account_map.get(item.get('account'), account_map.get('Cash'))
                cat_id = category_map.get(item.get('category'))
                if acc_id and cat_id:
                    cursor.execute("""
                        INSERT INTO paid_expenses (id, user_id, month_id, account_id, category_id, reason, amount, expense_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE reason=VALUES(reason), amount=VALUES(amount)
                    """, (str(item['id']), user_id, month_id, acc_id, cat_id, item['reason'], item['amount'], item['date']))

            # 4. Update Personal Expenses
            cursor.execute("DELETE FROM personal_expenses WHERE month_id = %s", (month_id,))
            for item in data.get('personalExpenses', []):
                acc_id = account_map.get(item.get('account'), account_map.get('Cash'))
                if acc_id:
                    # date might be missing in some personal expense JSON
                    date_val = item.get('date') or datetime.now().strftime('%Y-%m-%d')
                    cursor.execute("INSERT INTO personal_expenses (id, user_id, month_id, account_id, reason, amount, expense_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                                 (str(item['id']), user_id, month_id, acc_id, item['reason'], item['amount'], date_val))

            # 5. Update Pending Expenses
            cursor.execute("DELETE FROM pending_expenses WHERE month_id = %s AND status = 'pending'", (month_id,))
            for item in data.get('pendingExpenses', []):
                cat_id = category_map.get(item.get('category'))
                if cat_id:
                    cursor.execute("INSERT INTO pending_expenses (id, user_id, month_id, category_id, reason, amount, payment_mode, status) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')",
                                 (str(item['id']), user_id, month_id, cat_id, item['reason'], item['amount'], item.get('mode', 'online')))

            # 6. Update Notes
            cursor.execute("DELETE FROM notes WHERE month_id = %s", (month_id,))
            for item in data.get('notes', []):
                cursor.execute("INSERT INTO notes (id, user_id, month_id, title, content, note_date) VALUES (%s, %s, %s, %s, %s, %s)",
                             (str(item['id']), user_id, month_id, item['title'], item['content'], item['date']))

            conn.commit()
            return True
        except Error as e:
            print(f"Error saving month data: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    # --- Long Pending Payments ---

    def get_long_pending(self, user_id):
        """Retrieves all long-pending items for a user."""
        conn = self.get_connection()
        if not conn: return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM long_pending WHERE user_id = %s ORDER BY created_date DESC", (user_id,))
            results = cursor.fetchall()
            for r in results:
                r['totalAmount'] = float(r['total_amount'])
                r['paidAmount'] = float(r['paid_amount'])
                r['remainingAmount'] = float(r['remaining_amount'])
                r['createdDate'] = r['created_date'].strftime('%Y-%m-%d')
            return results
        finally:
            conn.close()

    def add_long_pending(self, user_id, item_data):
        """Adds a new long-pending debt/payment item."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            query = """
                INSERT INTO long_pending (id, user_id, reason, total_amount, paid_amount, category, created_date, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')
            """
            cursor.execute(query, (
                str(item_data['id']),
                user_id,
                item_data['reason'],
                item_data['totalAmount'],
                item_data.get('paidAmount', 0),
                item_data.get('category', 'General'),
                item_data.get('createdDate', datetime.now().strftime('%Y-%m-%d'))
            ))
            conn.commit()
            return True
        finally:
            conn.close()

    def delete_long_pending(self, user_id, item_id):
        """Deletes a long-pending item from the database."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM long_pending WHERE user_id = %s AND id = %s", (user_id, item_id))
            conn.commit()
            return True
        finally:
            conn.close()

    def make_partial_payment(self, user_id, item_id, month_key, amount, account_name, mode):
        """
        Executes a partial payment on a long-pending item using a stored procedure.
        This updates the remaining balance and creates a linked expense.
        """
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor(dictionary=True)
            # Find month_id and account_id
            cursor.execute("SELECT id FROM months WHERE user_id = %s AND month_key = %s", (user_id, month_key))
            m_row = cursor.fetchone()
            cursor.execute("SELECT id FROM accounts WHERE user_id = %s AND account_name = %s", (user_id, account_name))
            a_row = cursor.fetchone()

            if m_row and a_row:
                cursor.callproc('sp_pay_long_pending', (
                    item_id, user_id, m_row['id'], a_row['id'], amount, mode, datetime.now().strftime('%Y-%m-%d')
                ))
                conn.commit()
                return True
            return False
        finally:
            conn.close()

    def delete_expense(self, user_id, month_key, expense_id):
        """
        Deletes an expense. If the expense was a long-pending payment, it
        automatically reverses the payment and updates the debt balance.
        """
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor(dictionary=True)

            # Fetch the expense to check if it's long pending
            cursor.execute("SELECT * FROM paid_expenses WHERE user_id = %s AND id = %s", (user_id, expense_id))
            expense = cursor.fetchone()

            if not expense: return False

            if expense['is_long_pending'] and expense['linked_long_pending_id']:
                # Reverse the payment on long_pending item
                cursor.execute("""
                    UPDATE long_pending
                    SET paid_amount = paid_amount - %s, status = 'active'
                    WHERE id = %s
                """, (expense['amount'], expense['linked_long_pending_id']))

            # Delete from paid_expenses (history entries in long_pending_payments will cascade or stay depending on DB choice)
            cursor.execute("DELETE FROM paid_expenses WHERE id = %s", (expense_id,))

            conn.commit()
            return True
        finally:
            conn.close()

    # --- CSV Import (Simplified mapping for integration) ---

    def sync_bulk_data(self, user_id, month_key, bulk_data):
        """
        Helper to save data imported from CSV.
        """
        return self.save_month_data(user_id, month_key, bulk_data)
