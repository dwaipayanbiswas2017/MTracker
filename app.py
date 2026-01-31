import csv
import io
import random
import time
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash, session
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from database_controller import DatabaseController
import dotenv
import os

# Load environment variables from .env file
dotenv.load_dotenv()
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this in production
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'profile_pics')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit

# Database Configuration
DB_CONFIG = {
    'host': os.getenv('host'),
    'user': os.getenv('user'),
    'password': os.getenv('password'),
    'database': os.getenv('database')
}

print(f"DB_Config: {DB_CONFIG}")

db = DatabaseController(DB_CONFIG)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = None # Disable default login message

# --- User Management ---

class User(UserMixin):
    def __init__(self, id, name, password_hash, email=None, phone=None, registration_method='email', profile_pic_path=None, currency_pref='INR', default_account_id=None, is_admin=False):
        self.id = id
        self.name = name
        self.password_hash = password_hash
        self.email = email
        self.phone = phone
        self.registration_method = registration_method
        self.profile_pic_path = profile_pic_path
        self.currency_pref = currency_pref
        self.default_account_id = default_account_id
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    u = db.get_user_by_id(user_id)
    if u:
        return User(
            user_id,
            u['name'],
            u['password_hash'],
            u.get('email'),
            u.get('phone'),
            u.get('registration_method', 'email'),
            u.get('profile_pic_path'),
            u.get('currency_pref', 'INR'),
            u.get('default_account_id'),
            u.get('is_admin', False)
        )
    return None

# --- Data Management ---
def parse_month_date(date_str):
    formats = [
        '%b-%y',       # Nov-25
        '%b-%Y',       # Nov-2025
        '%B-%y',       # November-25
        '%B-%Y',       # November-2025
        '%m-%Y',       # 11-2025
        '%m-%y',       # 11-25
        '%Y-%m',       # 2025-11
        '%b %y',       # Nov 25
        '%b %Y',       # Nov 2025
    ]

    # Try as provided
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass

    # Try Title Case (for NOV-25 -> Nov-25)
    date_str_title = date_str.title()
    for fmt in formats:
        try:
            return datetime.strptime(date_str_title, fmt)
        except ValueError:
            pass

    return None

# --- Auth Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form['username']
        password = request.form['password']

        user_data = db.get_user_by_identifier(identifier)

        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(
                user_data['id'],
                user_data['name'],
                user_data['password_hash'],
                user_data.get('email'),
                user_data.get('phone'),
                user_data.get('registration_method', 'email'),
                user_data.get('profile_pic_path'),
                user_data.get('currency_pref', 'INR'),
                user_data.get('default_account_id'),
                user_data.get('is_admin', False)
            )
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid Email/Phone or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        identifier = request.form['username']
        password = request.form['password']

        if db.get_user_by_identifier(identifier):
            flash('Email or Phone number already registered')
            return redirect(url_for('register'))

        user_id = str(datetime.now().timestamp())
        password_hash = generate_password_hash(password)

        email = identifier if '@' in identifier else None
        phone = identifier if '@' not in identifier else None
        reg_method = 'email' if '@' in identifier else 'phone'

        if db.create_user(user_id, name, password_hash, email, phone, reg_method):
            user = User(user_id, name, password_hash, email, phone, reg_method, is_admin=False)
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Error creating account. Please try again.')

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- Routes ---
@app.route('/')
@login_required
def index():
    return render_template('index.html', name=current_user.name, user=current_user)

@app.route('/api/categories', methods=['GET'])
@login_required
def get_categories():
    categories = db.get_categories(current_user.id)
    return jsonify(categories)

@app.route('/api/categories/update', methods=['POST'])
@login_required
def update_category():
    old_name = request.json.get('old_name')
    new_name = request.json.get('new_name')
    if not old_name or not new_name:
        return jsonify({"status": "error", "message": "Both old and new category names required"}), 400

    if db.update_category(current_user.id, old_name, new_name):
        categories = db.get_categories(current_user.id)
        return jsonify({"status": "success", "categories": categories})
    return jsonify({"status": "error", "message": "Could not update category (check if name is unique)"}), 500

@app.route('/api/categories', methods=['POST'])
@login_required
def add_category():
    new_cat = request.json.get('category')
    if not new_cat:
        return jsonify({"status": "error", "message": "Category name required"}), 400

    if db.add_category(current_user.id, new_cat):
        categories = db.get_categories(current_user.id)
        return jsonify({"status": "success", "categories": categories})
    return jsonify({"status": "error", "message": "Could not add category"}), 500

@app.route('/api/accounts', methods=['GET'])
@login_required
def get_accounts():
    accounts = db.get_accounts(current_user.id)
    return jsonify(accounts)

@app.route('/api/accounts/update', methods=['POST'])
@login_required
def update_account():
    old_name = request.json.get('old_name')
    new_name = request.json.get('new_name')
    if not old_name or not new_name:
        return jsonify({"status": "error", "message": "Both old and new account names required"}), 400

    if db.update_account(current_user.id, old_name, new_name):
        accounts = db.get_accounts(current_user.id)
        return jsonify({"status": "success", "accounts": accounts})
    return jsonify({"status": "error", "message": "Could not update account (check if name is unique)"}), 500

@app.route('/api/accounts', methods=['POST'])
@login_required
def add_account():
    new_acc = request.json.get('account')
    if not new_acc:
        return jsonify({"status": "error", "message": "Account name required"}), 400

    if db.add_account(current_user.id, new_acc):
        accounts = db.get_accounts(current_user.id)
        return jsonify({"status": "success", "accounts": accounts})
    return jsonify({"status": "error", "message": "Could not add account"}), 500

@app.route('/api/months', methods=['GET'])
@login_required
def get_months():
    months = db.get_months(current_user.id)

    def sort_key(m):
        d = parse_month_date(m)
        return d if d else datetime.min

    months.sort(key=sort_key)

    current_month_str = datetime.now().strftime('%Y-%m')

    # Check if current month exists
    now = datetime.now()
    current_month_exists = False
    for m in months:
        d = parse_month_date(m)
        if d and d.year == now.year and d.month == now.month:
            current_month_exists = True
            break

    if not current_month_exists:
        months.append(current_month_str)
        months.sort(key=sort_key)

    return jsonify(months)

@app.route('/api/month/<month_id>', methods=['GET'])
@login_required
def get_month_data(month_id):
    month_data = db.get_month_data(current_user.id, month_id)

    if month_data:
        return jsonify(month_data)

    # ---[ AUTO-CREATE MONTH LOGIC ]---
    # If month_id doesn't exist, create it on the fly.
    new_month_date = parse_month_date(month_id)
    if not new_month_date:
        return jsonify({"status": "error", "message": "Invalid month format"}), 400

    db.create_month(current_user.id, month_id, copy_pending=True)
    month_data = db.get_month_data(current_user.id, month_id)

    if month_data:
        return jsonify(month_data)

    return jsonify({"status": "error", "message": "Could not create month data"}), 500

@app.route('/api/save', methods=['POST'])
@login_required
def save_month_data():
    req = request.json
    month_id = req.get('id')
    month_data = req.get('data')

    if db.save_month_data(current_user.id, month_id, month_data):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Could not save month data"}), 500

@app.route('/api/create_month', methods=['POST'])
@login_required
def create_month():
    req = request.json
    month_input = req.get('month_input') # Expected format: YYYY-MM
    copy_pending = req.get('copy_pending', False)

    if not month_input:
        return jsonify({"status": "error", "message": "Month selection required"}), 400

    # Validate format YYYY-MM
    try:
        datetime.strptime(month_input, '%Y-%m')
        new_month_id = month_input
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid date format"}), 400

    # Check if month already exists
    existing_months = db.get_months(current_user.id)
    if new_month_id in existing_months:
         return jsonify({"status": "error", "message": f"Month {new_month_id} already exists"}), 400

    db.create_month(current_user.id, new_month_id, copy_pending)
    new_data = db.get_month_data(current_user.id, new_month_id)

    if new_data:
        return jsonify({"status": "success", "data": new_data, "id": new_month_id})
    return jsonify({"status": "error", "message": "Could not create month"}), 500

@app.route('/api/delete_month', methods=['POST'])
@login_required
def delete_month():
    month_id = request.json.get('id')
    if db.delete_month(current_user.id, month_id):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Could not delete month"}), 500

# --- CSV Import Logic ---
@app.route('/api/import', methods=['POST'])
@login_required
def import_csv():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    month_id = request.form.get('month_id')

    if not month_id:
        return jsonify({"error": "Month ID required"}), 400

    stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
    csv_input = csv.reader(stream)
    rows = list(csv_input)

    # Initialize data buckets
    paid_expenses = []
    pending_expenses = []
    personal_expenses = []
    income = 0
    opening_balance = 0

    # Parsing Flags & Section Headers
    section = None # 'paid', 'pending', 'personal'

    for i, row in enumerate(rows):
        # normalize row for check
        clean_row = [str(cell).strip() for cell in row]
        first_cell = clean_row[0] if len(clean_row) > 0 else ""

        # --- Detect Sections ---
        if "TOTAL EXPENSE LIST" in first_cell or "PAYMENT REASON" in first_cell and section is None:
            section = 'paid'
            continue

        if "PENDING" in first_cell:
            section = 'pending'
            continue

        if "Personal Expenses" in first_cell:
            section = 'personal'
            continue

        # --- Extract Header Info (Right Side of Sheet) ---
        # Look for "INCOME IN CURRENT MONTH:" usually in column I or J (index 8 or 9)
        for col_idx, cell in enumerate(clean_row):
            if "INCOME IN CURRENT MONTH" in str(cell):
                try:
                    income = float(clean_row[col_idx+1].replace(',', ''))
                except: pass
            if "AVAILABLE FROM PREVIOUS MONTH" in str(cell):
                try:
                    opening_balance = float(clean_row[col_idx+1].replace(',', ''))
                except: pass

        # --- Parse Rows based on Section ---
        # Skip header rows inside sections
        if first_cell in ["PAYMENT REASON", "Type", ""]:
            continue

        try:
            if section == 'paid':
                # Format: Reason, Category, Date, Amount
                if len(clean_row) >= 4 and clean_row[3]:
                    amt = float(clean_row[3].replace(',', ''))
                    if amt > 0:
                        paid_expenses.append({
                            "id": i,
                            "reason": clean_row[0],
                            "category": clean_row[1],
                            "date": clean_row[2],
                            "amount": amt,
                            "mode": "Online" # Default
                        })

            elif section == 'pending':
                # Format: Reason, Category, Mode, Amount
                if len(clean_row) >= 4 and clean_row[3]:
                    amt = float(clean_row[3].replace(',', ''))
                    pending_expenses.append({
                        "id": i,
                        "reason": clean_row[0],
                        "category": clean_row[1],
                        "amount": amt,
                        "mode": clean_row[2]
                    })

            elif section == 'personal':
                # Format: Type/Reason, Date, Amount (Often in cols 6,7,8 or similar, dependent on sheet shift)
                # Looking at your CSV, Personal table is often shifted right.
                # Let's try to find numeric value in rightmost cols for this section
                # Typically: Type (col 6/7), Date, Amount
                # Simple heuristic: Find the non-empty cells
                non_empty = [c for c in clean_row if c]
                if len(non_empty) >= 2:
                    # Assume last is amount, first is reason
                    try:
                        amt = float(non_empty[-1].replace(',', ''))
                        reason = non_empty[0]
                        personal_expenses.append({
                            "id": i,
                            "reason": reason,
                            "date": "",
                            "amount": amt
                        })
                    except: pass
        except ValueError:
            continue

    # Merge into DB
    month_data = {
        "income": [{'id': 'csv-import', 'source': 'CSV Import', 'amount': income, 'account': 'Cash'}],
        "openingBalance": {'Cash': opening_balance},
        "paidExpenses": paid_expenses,
        "pendingExpenses": pending_expenses,
        "personalExpenses": personal_expenses
    }

    if db.sync_bulk_data(current_user.id, month_id, month_data):
        return jsonify({"status": "success", "data": month_data})

    return jsonify({"status": "error", "message": "Could not import CSV data"}), 500

# --- Long Pending Payments (Global) ---
@app.route('/api/long_pending', methods=['GET'])
@login_required
def get_all_long_pending():
    long_pending = db.get_long_pending(current_user.id)
    return jsonify(long_pending)

@app.route('/api/long_pending', methods=['POST'])
@login_required
def add_long_pending():
    req = request.json

    new_item = {
        "id": req.get('id') or str(datetime.now().timestamp()),
        "reason": req.get('reason'),
        "totalAmount": float(req.get('totalAmount')),
        "paidAmount": float(req.get('paidAmount', 0)),
        "category": req.get('category', 'General'),
        "createdDate": req.get('createdDate', datetime.now().strftime('%Y-%m-%d'))
    }

    if db.add_long_pending(current_user.id, new_item):
        return jsonify({"status": "success", "data": new_item})
    return jsonify({"status": "error", "message": "Could not add long pending item"}), 500

@app.route('/api/long_pending/update', methods=['POST'])
@login_required
def update_long_pending():
    req = request.json
    try:
        item_data = {
            "id": req.get('id'),
            "reason": req.get('reason'),
            "totalAmount": float(req.get('totalAmount')),
            "category": req.get('category')
        }
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid amount format"}), 400

    if not item_data['id']:
        return jsonify({"status": "error", "message": "Item ID required"}), 400

    if db.update_long_pending(current_user.id, item_data):
         return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Could not update item"}), 500

@app.route('/api/long_pending/<item_id>', methods=['DELETE'])
@login_required
def delete_long_pending(item_id):
    if db.delete_long_pending(current_user.id, item_id):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Could not delete long pending item"}), 500

@app.route('/api/long_pending/<item_id>/partial_payment', methods=['POST'])
@login_required
def make_partial_payment(item_id):
    req = request.json
    payment_amount = float(req.get('amount', 0))
    month_id = req.get('month_id')
    account = req.get('account')
    mode = req.get('mode', 'Online')

    if payment_amount <= 0:
        return jsonify({"status": "error", "message": "Payment amount must be positive"}), 400

    if not month_id:
        return jsonify({"status": "error", "message": "Month ID required"}), 400

    if db.make_partial_payment(current_user.id, item_id, month_id, payment_amount, account, mode):
        return jsonify({"status": "success"})

    return jsonify({"status": "error", "message": "Could not process partial payment"}), 500

@app.route('/api/month/<month_id>/expense/<expense_id>', methods=['DELETE'])
@login_required
def delete_expense(month_id, expense_id):
    if db.delete_expense(current_user.id, month_id, expense_id):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Could not delete expense"}), 500

@app.route('/api/update_password', methods=['POST'])
@login_required
def update_password():
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    if not new_password or len(new_password) < 6:
        return jsonify({"status": "error", "message": "New password must be at least 6 characters long."}), 400

    if new_password != confirm_password:
        return jsonify({"status": "error", "message": "Passwords do not match."}), 400

    is_verified = False
    if current_password and check_password_hash(current_user.password_hash, current_password):
        is_verified = True
    elif session.get('pwd_verified_via_otp'):
        is_verified = True
        session.pop('pwd_verified_via_otp', None)

    if not is_verified:
        return jsonify({"status": "error", "message": "Identity verification failed."}), 403

    password_hash = generate_password_hash(new_password)
    if db.update_user(current_user.id, password_hash=password_hash):
        return jsonify({"status": "success", "message": "Password updated successfully!"})

    return jsonify({"status": "error", "message": "Failed to update password."}), 500

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        name = request.form.get('name')
        currency_pref = request.form.get('currency_pref', 'INR')
        default_account_id = request.form.get('default_account_id')

        # We keep email/phone in the form for fallback, but they are disabled if handled by OTP
        # and identifying registration method, so we should be careful.
        # Actually, the requirement says "User can update email and phone both with proper OTP verification".
        # This implies we should handle them specifically.

        if db.update_user(
            current_user.id,
            name=name,
            profile_pic_path=None, # will be updated if file present
            currency_pref=currency_pref,
            default_account_id=default_account_id if default_account_id else None
        ):
            # Re-handle profile pic specifically since we skipped it above for DB call simplicity
            if 'profile_pic' in request.files:
                file = request.files['profile_pic']
                if file and file.filename != '':
                    filename = secure_filename(f"{current_user.id}_{file.filename}")
                    rel_path = os.path.join('uploads', 'profile_pics', filename)
                    full_path = os.path.join(app.root_path, 'static', rel_path)
                    file.save(full_path)
                    db.update_user(current_user.id, profile_pic_path=os.path.join('static', rel_path).replace('\\', '/'))

            flash('Profile updated successfully', 'success')
        else:
            flash('Error updating profile', 'danger')

        return redirect(url_for('profile'))

    accounts = db.get_accounts(current_user.id)
    return render_template('profile.html', user=current_user, accounts=accounts)

# --- Admin Routes ---

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('index'))

    users = db.get_all_users_with_stats()
    stats = db.get_system_stats()
    return render_template('admin.html', users=users, stats=stats)

@app.route('/admin/toggle_user/<user_id>', methods=['POST'])
@login_required
def admin_toggle_user(user_id):
    if not current_user.is_admin:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    if user_id == current_user.id:
        return jsonify({"status": "error", "message": "You cannot deactivate your own account."}), 400

    if db.toggle_user_status(user_id):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Could not toggle user status"}), 500

@app.route('/admin/toggle_admin/<user_id>', methods=['POST'])
@login_required
def admin_toggle_admin(user_id):
    if not current_user.is_admin:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    if user_id == str(current_user.id):
        return jsonify({"status": "error", "message": "You cannot remove your own admin status."}), 400

    if db.toggle_admin_status(user_id):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Could not toggle admin status"}), 500

@app.route('/admin/delete_user/<user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    if user_id == current_user.id:
        return jsonify({"status": "error", "message": "You cannot delete your own account."}), 400

    if db.delete_user_cascading(user_id):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Could not delete user"}), 500

# --- Jinja Filters ---

@app.template_filter('format_currency')
def format_currency_filter(value):
    try:
        return "{:,.0f}".format(value)
    except (ValueError, TypeError):
        return value

# For OTP storage (in production, use Redis or DB with expiry)
otp_storage = {}

@app.route('/api/verify_password', methods=['POST'])
@login_required
def verify_password():
    password = request.json.get('password')
    if not password:
        return jsonify({"status": "error", "message": "Password is required"}), 400

    if check_password_hash(current_user.password_hash, password):
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Incorrect password"}), 401

@app.route('/api/send_otp', methods=['POST'])
@login_required
def send_otp():
    new_identifier = request.json.get('identifier')

    # If a new identifier is provided, check if it's already in use
    if new_identifier:
        if not db.is_identifier_available(new_identifier, exclude_user_id=current_user.id):
            return jsonify({"status": "error", "message": "This email/phone is already registered to another account."}), 400
        target_info = f"New Identifier: {new_identifier}"
    else:
        if not current_user.email and not current_user.phone:
            return jsonify({"status": "error", "message": "No contact information found"}), 400
        target_info = f"Registered Email: {current_user.email}, Phone: {current_user.phone}"

    otp = str(random.randint(100000, 999999))
    otp_storage[current_user.id] = {
        "otp": otp,
        "expiry": time.time() + 300,
        "pending_identifier": new_identifier # Store if we are updating identifier
    }

    # Mocking sending
    targets = []
    if new_identifier:
        # If updating, send ONLY to the new one
        print(f"[MOCK] Sending Verification OTP {otp} to NEW identifier: {new_identifier}")
        targets.append("New Entry")
    else:
        # If just verifying for password change, send to existing
        if current_user.email:
            print(f"[MOCK] Sending OTP {otp} to Email: {current_user.email}")
            targets.append("Email")
        if current_user.phone:
            print(f"[MOCK] Sending OTP {otp} to SMS: {current_user.phone}")
            targets.append("SMS")

    return jsonify({"status": "success", "message": f"OTP sent to {target_info}", "target": ', '.join(targets)})

@app.route('/api/verify_otp', methods=['POST'])
@login_required
def verify_otp():
    user_otp = request.json.get('otp')
    if not user_otp:
        return jsonify({"status": "error", "message": "OTP is required"}), 400

    stored = otp_storage.get(current_user.id)
    if not stored:
        return jsonify({"status": "error", "message": "OTP session not found"}), 404

    if time.time() > stored['expiry']:
        del otp_storage[current_user.id]
        return jsonify({"status": "error", "message": "OTP expired"}), 400

    if stored['otp'] == user_otp:
        # If there's a pending identifier, update it in the database immediately
        pending_id = stored.get('pending_identifier')
        if pending_id:
            if '@' in pending_id:
                db.update_user(current_user.id, email=pending_id)
            else:
                db.update_user(current_user.id, phone=pending_id)
            del otp_storage[current_user.id]
            return jsonify({"status": "success", "message": "Identity updated successfully", "type": "identifier_update"})

        session['pwd_verified_via_otp'] = True
        return jsonify({"status": "success", "message": "Verification successful", "type": "password_verification"})

    return jsonify({"status": "error", "message": "Invalid OTP"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')