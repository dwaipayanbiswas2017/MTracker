import mysql.connector
from mysql.connector import Error
from datetime import datetime
import json
import os
import subprocess
import gzip
import shutil

_MYSQLDUMP_PATH = shutil.which('mysqldump') or '/usr/bin/mysqldump'
_MYSQL_PATH = shutil.which('mysql') or '/usr/bin/mysql'

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
                SELECT i.id, i.source, i.amount, i.notes, a.account_name as account
                FROM income i
                JOIN accounts a ON i.account_id = a.id
                WHERE i.month_id = %s
            """
            cursor.execute(query_inc, (month_id,))
            income = cursor.fetchall()
            for r in income: r['amount'] = float(r['amount'])

            # 4. Get Paid Expenses (Excluding daily logs to prevent duplication in frontend arrays)
            query_pe = """
                SELECT pe.id, pe.reason, pe.amount, pe.expense_date as date, pe.notes,
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
                    notes = item.get('notes')
                    cursor.execute("INSERT INTO income (id, user_id, month_id, account_id, source, amount, notes) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                                 (str(item['id']), user_id, month_id, acc_id, item['source'], item['amount'], notes))

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
                    notes = item.get('notes')
                    cursor.execute("""
                        INSERT INTO paid_expenses (id, user_id, month_id, account_id, category_id, reason, amount, expense_date, is_daily_log, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s)
                        ON DUPLICATE KEY UPDATE reason=VALUES(reason), amount=VALUES(amount), category_id=VALUES(category_id), notes=VALUES(notes)
                    """, (str(item['id']), user_id, month_id, acc_id, cat_id, item['reason'], item['amount'], item['date'], notes))

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

            # If this expense was created via a fund transfer, also delete linked income entry
            if expense['notes'] and expense['notes'].startswith('__transfer__:'):
                transfer_id = expense['notes'].split(':')[1]
                cursor.execute("DELETE FROM income WHERE month_id = %s AND notes = %s",
                               (expense['month_id'], f'__transfer__:{transfer_id}'))

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

    def get_admin_users_with_email(self):
        """Returns admin users who have an email address set."""
        conn = self.get_connection()
        if not conn: return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, name, email FROM users WHERE is_admin = 1 AND email IS NOT NULL AND email != ''"
            )
            return cursor.fetchall()
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

    # --- Personal Access Tokens (MCP Auth) ---

    def create_pat(self, user_id, name, scope='read_write'):
        """
        Creates a new Personal Access Token for a user.
        Returns the token_id and the raw token value (to show once).
        """
        import hashlib, secrets, time
        conn = self.get_connection()
        if not conn: return None
        try:
            token_value = 'mt_live_' + secrets.token_hex(32)
            token_hash = hashlib.sha256(token_value.encode()).hexdigest()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT COUNT(*) as cnt FROM personal_access_tokens WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            token_id = f"{user_id}_pat{row['cnt'] + 1}"
            cursor.execute("""
                INSERT INTO personal_access_tokens (id, user_id, token_hash, name, scope)
                VALUES (%s, %s, %s, %s, %s)
            """, (token_id, user_id, token_hash, name, scope))
            conn.commit()
            return {"id": token_id, "token": token_value, "name": name, "scope": scope}
        except Exception as e:
            print(f"Error creating PAT: {e}")
            return None
        finally:
            conn.close()

    def validate_pat(self, token_value):
        """
        Validates a Personal Access Token.
        Returns user_id dict if valid, None otherwise.
        """
        import hashlib
        if not token_value or not token_value.startswith('mt_live_'):
            return None
        conn = self.get_connection()
        if not conn: return None
        try:
            token_hash = hashlib.sha256(token_value.encode()).hexdigest()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT pat.user_id, u.name as user_name, pat.scope
                FROM personal_access_tokens pat
                JOIN users u ON pat.user_id = u.id AND u.is_active = TRUE
                WHERE pat.token_hash = %s AND (pat.expires_at IS NULL OR pat.expires_at > NOW()) AND pat.revoked = FALSE
            """, (token_hash,))
            return cursor.fetchone()
        finally:
            conn.close()

    def list_pats(self, user_id):
        """Lists all non-revoked PATs for a user."""
        conn = self.get_connection()
        if not conn: return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT id, name, scope, created_at, expires_at, last_used_at
                FROM personal_access_tokens
                WHERE user_id = %s AND revoked = FALSE
                ORDER BY created_at DESC
            """, (user_id,))
            return cursor.fetchall()
        finally:
            conn.close()

    def revoke_pat(self, user_id, pat_id):
        """Revokes a Personal Access Token."""
        conn = self.get_connection()
        if not conn: return False
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE personal_access_tokens SET revoked = TRUE WHERE id = %s AND user_id = %s", (pat_id, user_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def update_pat_last_used(self, pat_id):
        """Updates the last_used_at timestamp for a PAT."""
        conn = self.get_connection()
        if not conn: return
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE personal_access_tokens SET last_used_at = NOW() WHERE id = %s", (pat_id,))
            conn.commit()
        finally:
            conn.close()

    # --- Database Backup & Restore ---

    def get_backup_dir(self):
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        return backup_dir

    def create_backup(self, user_id=None):
        """
        Creates a compressed mysqldump backup.
        Returns the filename on success, None on failure.
        """
        backup_dir = self.get_backup_dir()
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f"mtracker_backup_{timestamp}.sql.gz"
        filepath = os.path.join(backup_dir, filename)

        host = self.config.get('host', 'localhost')
        user = self.config.get('user', 'root')
        password = self.config.get('password', '')
        database = self.config.get('database', 'mtracker')

        try:
            cmd = [
                _MYSQLDUMP_PATH,
                f'--host={host}',
                f'--user={user}',
                f'--password={password}',
                '--single-transaction',
                '--routines',
                '--triggers',
                '--force',
                database
            ]
            result = subprocess.run(cmd, check=False, capture_output=True, timeout=300)
            if result.returncode != 0 and len(result.stdout) == 0:
                err_msg = result.stderr.decode(errors='replace') if result.stderr else 'unknown error'
                print(f"[Backup] mysqldump failed: {err_msg}")
                return None
            with gzip.open(filepath, 'wb') as f:
                f.write(result.stdout)

            # --force can return non-zero if views have issues, but data is valid
            if result.returncode not in (0, 2) and len(result.stdout) == 0:
                err_msg = result.stderr.decode(errors='replace') if result.stderr else 'unknown error'
                print(f"[Backup] mysqldump failed: {err_msg}")
                return None

            self.log_audit(user_id or 'system', 'INSERT', 'backup', filename,
                           {'action': 'backup_created', 'size': os.path.getsize(filepath)},
                           origin='web')
            return filename
        except subprocess.TimeoutExpired:
            print(f"[Backup] Timed out during mysqldump")
            return None
        except Exception as e:
            print(f"[Backup] Error: {e}")
            return None

    def list_backups(self):
        """Returns a list of backup files sorted newest-first."""
        backup_dir = self.get_backup_dir()
        try:
            files = []
            for f in os.listdir(backup_dir):
                if f.startswith('mtracker_backup_') and f.endswith('.sql.gz'):
                    filepath = os.path.join(backup_dir, f)
                    stat = os.stat(filepath)
                    files.append({
                        'filename': f,
                        'size': stat.st_size,
                        'created': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })
            files.sort(key=lambda x: x['created'], reverse=True)
            return files
        except Exception as e:
            print(f"[Backup] Error listing backups: {e}")
            return []

    def restore_backup(self, filename, user_id=None):
        """
        Restores the database from a compressed backup file.
        WARNING: This will OVERWRITE the current database.
        Returns True on success.
        """
        backup_dir = self.get_backup_dir()
        filepath = os.path.join(backup_dir, filename)

        if not os.path.exists(filepath):
            return False

        host = self.config.get('host', 'localhost')
        user = self.config.get('user', 'root')
        password = self.config.get('password', '')
        database = self.config.get('database', 'mtracker')

        try:
            # Read decompressed content into memory first (gzip.GzipFile stdin
            # doesn't pipe correctly with subprocess)
            with gzip.open(filepath, 'rb') as f:
                sql_content = f.read()

            cmd = [
                _MYSQL_PATH,
                f'--host={host}',
                f'--user={user}',
                f'--password={password}',
                '--force',
                database
            ]
            result = subprocess.run(cmd, input=sql_content, capture_output=True, timeout=600)
            if result.returncode != 0:
                err = result.stderr.decode(errors='replace') if result.stderr else 'unknown error'
                self._backup_log(f"Restore failed: {err}")
                return False

            self.log_audit(user_id or 'system', 'UPDATE', 'backup_restore', filename,
                           {'action': 'database_restored'}, origin='web')
            return True
        except subprocess.TimeoutExpired:
            self._backup_log("Timed out during restore")
            return False
        except Exception as e:
            self._backup_log(f"Restore error: {e}")
            return False

    def delete_backup(self, filename):
        """Deletes a backup file. Returns True on success."""
        backup_dir = self.get_backup_dir()
        filepath = os.path.join(backup_dir, filename)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                return True
            return False
        except Exception as e:
            print(f"[Backup] Delete error: {e}")
            return False

    @staticmethod
    def _backup_log(msg):
        """Write backup log line to logs/backup_scheduler.log."""
        import os as _os
        log_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'logs')
        _os.makedirs(log_dir, exist_ok=True)
        log_path = _os.path.join(log_dir, 'backup_scheduler.log')
        try:
            with open(log_path, 'a') as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
        except Exception:
            pass

    def get_backup_schedule(self):
        """
        Returns the backup schedule config from system_settings,
        including the computed next_backup datetime.
        """
        enabled = self.get_system_setting('backup_enabled', '0') == '1'
        backup_time = self.get_system_setting('backup_time', '02:00')
        last_run = self.get_system_setting('backup_last_run', '')
        email_enabled = self.get_system_setting('backup_email_enabled', '0') == '1'
        next_backup = None

        if enabled:
            try:
                hour, minute = map(int, backup_time.split(':'))
                now = datetime.now()
                candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

                # If today's slot has passed or already ran, push to tomorrow
                if candidate <= now or last_run == now.strftime('%Y-%m-%d'):
                    from datetime import timedelta
                    candidate += timedelta(days=1)
                    # Handle DST transitions: replace again after adding a day
                    candidate = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)

                next_backup = candidate.strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, AttributeError):
                pass

        return {
            'enabled': enabled,
            'backup_time': backup_time,
            'last_run': last_run,
            'next_backup': next_backup,
            'email_enabled': email_enabled
        }

    def set_backup_schedule(self, enabled, backup_time, email_enabled=False):
        """Saves the backup schedule to system_settings."""
        self.update_system_setting('backup_enabled', '1' if enabled else '0')
        self.update_system_setting('backup_time', backup_time)
        self.update_system_setting('backup_email_enabled', '1' if email_enabled else '0')

    def check_and_run_scheduled_backup(self):
        """
        Checks if a scheduled backup is due and runs it.
        Uses atomic INSERT ... ON DUPLICATE KEY UPDATE to prevent
        duplicate backups from concurrent workers.
        Returns filename on success, None if skipped/failed.
        """
        schedule = self.get_backup_schedule()
        if not schedule['enabled']:
            self._backup_log("Skipped — backup is disabled")
            return None

        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        last_run = schedule.get('last_run', '')

        if last_run == today_str:
            self._backup_log("Skipped — already ran today")
            return None

        try:
            hour, minute = map(int, schedule['backup_time'].split(':'))
            if now.hour < hour or (now.hour == hour and now.minute < minute):
                self._backup_log(f"Skipped — not yet time (scheduled {hour:02d}:{minute:02d}, now {now.hour:02d}:{now.minute:02d})")
                return None
        except (ValueError, AttributeError) as e:
            self._backup_log(f"Skipped — bad backup_time '{schedule['backup_time']}': {e}")
            return None

        # Atomically claim the backup slot
        conn = self.get_connection()
        if not conn:
            self._backup_log("Skipped — no DB connection")
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO system_settings (setting_key, setting_value)
                VALUES ('backup_last_run', %s)
                ON DUPLICATE KEY UPDATE
                    setting_value = IF(setting_value != %s, %s, setting_value)
            """, (today_str, today_str, today_str))
            affected = cursor.rowcount
            conn.commit()

            if affected == 0:
                self._backup_log("Skipped — another worker claimed the slot")
                return None
        except Exception as e:
            self._backup_log(f"Atomic check error: {e}")
            return None
        finally:
            conn.close()

        self._backup_log(f"Starting scheduled backup…")
        result = self.create_backup(user_id='system')
        if result:
            self._backup_log(f"Backup created: {result}")
        else:
            self._backup_log("Backup FAILED")
        return result

    # --- Audit Log ---

    def log_audit(self, user_id, action, table_name, record_id, details=None, origin='mcp'):
        """
        Writes an entry to the audit_log table.
        :param user_id: The user who performed the action
        :param action: 'INSERT', 'UPDATE', or 'DELETE'
        :param table_name: The table affected
        :param record_id: The record identifier
        :param details: Optional JSON-serializable dict with extra context
        :param origin: Source of the action ('mcp', 'web', etc.)
        """
        conn = self.get_connection()
        if not conn: return
        try:
            cursor = conn.cursor()
            details_json = json.dumps(details) if details else None
            cursor.execute("""
                INSERT INTO audit_log (user_id, table_name, record_id, action, new_values, origin)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, table_name, record_id, action, details_json, origin))
            conn.commit()
        except Exception as e:
            print(f"Error writing audit log: {e}")
        finally:
            conn.close()
