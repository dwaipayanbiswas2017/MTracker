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

    def update_user_password(self, user_id, hashed_password):
        """
        Updates a user's password.
        """
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            query = "UPDATE users SET password_hash = %s WHERE id = %s"
            cursor.execute(query, (hashed_password, user_id))
            conn.commit()
            return cursor.rowcount > 0
        except Error as e:
            print(f"Error updating password: {e}")
            return False
        finally:
            conn.close()

    def is_identifier_available(self, identifier, exclude_user_id=None):
        """
        Checks if an email or phone number is already in use by another user.
        """
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor(dictionary=True)
            query = "SELECT id FROM users WHERE (email = %s OR phone = %s)"
            params = [identifier, identifier]
            if exclude_user_id:
                query += " AND id != %s"
                params.append(exclude_user_id)
            cursor.execute(query, tuple(params))
            return cursor.fetchone() is None
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

            # 4. Get Paid Expenses (Excluding daily logs to prevent duplication in frontend arrays)
            query_pe = """
                SELECT pe.id, pe.reason, pe.amount, pe.expense_date as date,
                       c.category_name as category, a.account_name as account,
                       pe.is_long_pending, pe.linked_long_pending_id as linkedId
                FROM paid_expenses pe
                JOIN categories c ON pe.category_id = c.id
                LEFT JOIN accounts a ON pe.account_id = a.id
                WHERE pe.month_id = %s AND (pe.is_daily_log IS FALSE OR pe.is_daily_log IS NULL)
            """
            cursor.execute(query_pe, (month_id,))
            paid_expenses = cursor.fetchall()
            for r in paid_expenses:
                r['amount'] = float(r['amount'])
                r['date'] = r['date'].strftime('%Y-%m-%d')

            # 5. Get Personal Expenses (From paid_expenses where is_daily_log=TRUE)
            query_pers = """
                SELECT p.id, p.reason, p.amount, p.expense_date as date,
                       a.account_name as account, c.category_name as category
                FROM paid_expenses p
                JOIN accounts a ON p.account_id = a.id
                LEFT JOIN categories c ON p.category_id = c.id
                WHERE p.month_id = %s AND p.is_daily_log = TRUE
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
            # We also ensure we don't accidentally wipe daily logs which are now in this table,
            # but since we are about to re-insert them, we DO want to wipe them for this month.
            cursor.execute("DELETE FROM paid_expenses WHERE month_id = %s AND is_long_pending = FALSE", (month_id,))

            # Insert standard paid expenses
            for item in data.get('paidExpenses', []):
                if item.get('isLongPending'): continue
                acc_id = account_map.get(item.get('account'), account_map.get('Cash'))
                cat_id = category_map.get(item.get('category'))
                if acc_id and cat_id:
                    cursor.execute("""
                        INSERT INTO paid_expenses (id, user_id, month_id, account_id, category_id, reason, amount, expense_date, is_daily_log)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE)
                        ON DUPLICATE KEY UPDATE reason=VALUES(reason), amount=VALUES(amount), category_id=VALUES(category_id)
                    """, (str(item['id']), user_id, month_id, acc_id, cat_id, item['reason'], item['amount'], item['date']))

            # 4. Update Personal Expenses (Insert as daily_log entries in paid_expenses)
            # No separate delete needed as step 3 deleted all non-long-pending for the month
            for item in data.get('personalExpenses', []):
                acc_id = account_map.get(item.get('account'), account_map.get('Cash'))
                # Handle Category for Daily Logs
                cat_name = item.get('category', 'Personal') # Default if missing
                cat_id = category_map.get(cat_name)
                # If category missing in map, maybe create or default? For now, skip or default.
                # Since we migrated "Personal", we hope it's there.
                if not cat_id and 'Personal' in category_map:
                     cat_id = category_map['Personal']

                if acc_id:
                    date_val = item.get('date') or datetime.now().strftime('%Y-%m-%d')
                    cursor.execute("""
                        INSERT INTO paid_expenses
                        (id, user_id, month_id, account_id, category_id, reason, amount, expense_date, is_daily_log)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                        ON DUPLICATE KEY UPDATE reason=VALUES(reason), amount=VALUES(amount), category_id=VALUES(category_id)
                    """, (str(item['id']), user_id, month_id, acc_id, cat_id, item['reason'], item['amount'], date_val))

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

    def update_long_pending(self, user_id, item_data):
        """Updates a long-pending debt/payment item."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            query = """
                UPDATE long_pending
                SET reason = %s, total_amount = %s, category = %s
                WHERE user_id = %s AND id = %s
            """
            cursor.execute(query, (
                item_data['reason'],
                item_data['totalAmount'],
                item_data.get('category'),
                user_id,
                item_data['id']
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

    # --- Admin Operations ---

    def get_all_users_with_stats(self):
        """Retrieves all users with summary stats for the admin dashboard."""
        conn = self.get_connection()
        if not conn: return []
        try:
            cursor = conn.cursor(dictionary=True)
            query = """
                SELECT
                    u.id, u.name, u.email, u.phone, u.registration_method,
                    u.is_active, u.is_admin, u.created_at,
                    (SELECT COUNT(*) FROM months WHERE user_id = u.id) as month_count,
                    (SELECT COUNT(*) FROM paid_expenses WHERE user_id = u.id) as total_transactions
                FROM users u
                ORDER BY u.created_at DESC
            """
            cursor.execute(query)
            users = cursor.fetchall()
            for u in users:
                if u['created_at']:
                    u['created_at'] = u['created_at'].strftime('%Y-%m-%d %H:%M')
            return users
        finally:
            conn.close()

    def toggle_user_status(self, user_id):
        """Deactivates/Reactivates a user."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_active = NOT is_active WHERE id = %s", (user_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def toggle_admin_status(self, user_id):
        """Promotes/Demotes a user from admin status."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_admin = NOT is_admin WHERE id = %s", (user_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def delete_user_cascading(self, user_id):
        """Permanently deletes a user and all their data."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            # Deletion is simplified because of CASCADE constraints in schema
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def get_system_stats(self):
        """Retrieves global system statistics."""
        conn = self.get_connection()
        if not conn: return {}
        try:
            cursor = conn.cursor(dictionary=True)
            stats = {}
            cursor.execute("SELECT COUNT(*) as total FROM users")
            stats['total_users'] = cursor.fetchone()['total']

            cursor.execute("SELECT COUNT(*) as active FROM users WHERE is_active = TRUE")
            stats['active_users'] = cursor.fetchone()['active']

            cursor.execute("SELECT COUNT(*) as total FROM months")
            stats['total_months'] = cursor.fetchone()['total']

            # Sum of ALL expenses (Paid + Personal)
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) as total FROM paid_expenses
            """)
            res = cursor.fetchone()['total']
            stats['total_expenditure'] = float(res) if res else 0.0

            # Total Transactions count
            cursor.execute("""
                SELECT COUNT(*) as total FROM paid_expenses
            """)
            stats['total_transactions'] = cursor.fetchone()['total']

            return stats
        finally:
            conn.close()

    # --- System Settings ---

    def get_system_setting(self, key, default=None):
        """Retrieves a specific system setting by key."""
        conn = self.get_connection()
        if not conn: return default
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT setting_value FROM system_settings WHERE setting_key = %s", (key,))
            row = cursor.fetchone()
            return row[0] if row else default
        finally:
            conn.close()

    def update_system_setting(self, key, value):
        """Updates or creates a system setting."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            query = "INSERT INTO system_settings (setting_key, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)"
            cursor.execute(query, (key, value))
            conn.commit()
            return True
        except Error as e:
            print(f"Error updating system setting: {e}")
            return False
        finally:
            conn.close()

    def get_all_system_settings(self):
        """Retrieves all global system settings."""
        conn = self.get_connection()
        if not conn: return {}
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT setting_key, setting_value FROM system_settings")
            return {row[0]: row[1] for row in cursor.fetchall()}
        finally:
            conn.close()
