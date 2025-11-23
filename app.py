import os
import json
import csv
import io
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this in production
DATA_DIR = 'data'
USERS_FILE = 'users.json'

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- User Management ---

class User(UserMixin):
    def __init__(self, id, name, username, password_hash):
        self.id = id
        self.name = name
        self.username = username
        self.password_hash = password_hash

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

@login_manager.user_loader
def load_user(user_id):
    users = load_users()
    if user_id in users:
        u = users[user_id]
        # Handle missing 'name' for old users
        name = u.get('name', u['username'])
        return User(user_id, name, u['username'], u['password_hash'])
    return None

# --- Data Management ---
def get_user_data_file():
    return os.path.join(DATA_DIR, f"{current_user.id}.json")

def load_data():
    if not current_user.is_authenticated:
        return {}

    filepath = get_user_data_file()
    if not os.path.exists(filepath):
        # Initialize with default categories
        return {"categories": ["Bills", "Food", "Family", "EMI", "CC", "Other"]}

    with open(filepath, 'r') as f:
        data = json.load(f)
        # Ensure categories exist
        if "categories" not in data:
            data["categories"] = ["Bills", "Food", "Family", "EMI", "CC", "Other"]
        # Ensure accounts exist
        if "accounts" not in data:
            data["accounts"] = ["Cash", "Bank"]
        return data

def save_data(data):
    if not current_user.is_authenticated:
        return
    filepath = get_user_data_file()
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=4)

# --- Auth Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_users()

        # Simple lookup (username as key for simplicity in this file-based system)
        # Ideally we store by ID, but let's use username as ID for simplicity or search
        user_data = None
        user_id = None

        for uid, u in users.items():
            if u['username'] == username:
                user_data = u
                user_id = uid
                break

        if user_data and check_password_hash(user_data['password_hash'], password):
            name = user_data.get('name', username)
            user = User(user_id, name, username, user_data['password_hash'])
            login_user(user)
            return redirect(url_for('index'))

        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = request.form['password']
        users = load_users()

        for u in users.values():
            if u['username'] == username:
                flash('Username already exists')
                return redirect(url_for('register'))

        user_id = str(datetime.now().timestamp())
        users[user_id] = {
            'name': name,
            'username': username,
            'password_hash': generate_password_hash(password)
        }
        save_users(users)

        # Log them in
        user = User(user_id, name, username, users[user_id]['password_hash'])
        login_user(user)
        return redirect(url_for('index'))

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
    return render_template('index.html', name=current_user.name)

@app.route('/api/categories', methods=['GET'])
@login_required
def get_categories():
    data = load_data()
    return jsonify(data.get('categories', []))

@app.route('/api/categories', methods=['POST'])
@login_required
def add_category():
    new_cat = request.json.get('category')
    if not new_cat:
        return jsonify({"status": "error", "message": "Category name required"}), 400

    data = load_data()
    if new_cat not in data['categories']:
        data['categories'].append(new_cat)
        save_data(data)

    return jsonify({"status": "success", "categories": data['categories']})

@app.route('/api/accounts', methods=['GET'])
@login_required
def get_accounts():
    data = load_data()
    return jsonify(data.get('accounts', []))

@app.route('/api/accounts', methods=['POST'])
@login_required
def add_account():
    new_acc = request.json.get('account')
    if not new_acc:
        return jsonify({"status": "error", "message": "Account name required"}), 400

    data = load_data()
    if new_acc not in data['accounts']:
        data['accounts'].append(new_acc)
        save_data(data)

    return jsonify({"status": "success", "accounts": data['accounts']})

@app.route('/api/months', methods=['GET'])
@login_required
def get_months():
    data = load_data()
    # Filter out non-month keys like 'categories' and '_longPending'
    months = [k for k in data.keys() if k not in ['categories', '_longPending']]
    return jsonify(months)

@app.route('/api/month/<month_id>', methods=['GET'])
@login_required
def get_month_data(month_id):
    data = load_data()
    return jsonify(data.get(month_id, {}))

@app.route('/api/save', methods=['POST'])
@login_required
def save_month_data():
    req = request.json
    month_id = req.get('id')
    month_data = req.get('data')

    all_data = load_data()
    all_data[month_id] = month_data
    save_data(all_data)
    return jsonify({"status": "success"})

@app.route('/api/create_month', methods=['POST'])
@login_required
def create_month():
    req = request.json
    new_month_id = req.get('new_month_id')
    prev_month_id = req.get('prev_month_id')
    copy_pending = req.get('copy_pending', False)

    all_data = load_data()

    if new_month_id in all_data:
        return jsonify({"status": "error", "message": "Month already exists"}), 400

    prev_data = all_data.get(prev_month_id, {})

    # Calculate Previous Closing Balance per Account
    # Opening + Income - (Paid + Personal)

    # 1. Get Opening Balances
    prev_opening = prev_data.get('openingBalance', {})
    if isinstance(prev_opening, (int, float)):
        # Legacy support: assume 'Cash' if it was a single number
        prev_opening = {'Cash': float(prev_opening)}

    # 2. Initialize Closing with Opening
    closing_balances = prev_opening.copy()

    # 3. Add Income
    for inc in prev_data.get('income', []):
        acc = inc.get('account', 'Cash') # Default to Cash if missing
        closing_balances[acc] = closing_balances.get(acc, 0) + float(inc.get('amount', 0))

    # 4. Subtract Paid Expenses
    for exp in prev_data.get('paidExpenses', []):
        acc = exp.get('account', 'Cash')
        closing_balances[acc] = closing_balances.get(acc, 0) - float(exp.get('amount', 0))

    # 5. Subtract Personal Expenses
    for pers in prev_data.get('personalExpenses', []):
        acc = pers.get('account', 'Cash')
        closing_balances[acc] = closing_balances.get(acc, 0) - float(pers.get('amount', 0))

    new_data = {
        "income": [],
        "openingBalance": closing_balances,
        "paidExpenses": [],
        "personalExpenses": [],
        "pendingExpenses": []
    }

    if copy_pending:
        # Copy pending items from previous month
        new_data['pendingExpenses'] = prev_data.get('pendingExpenses', [])

    all_data[new_month_id] = new_data
    save_data(all_data)

    return jsonify({"status": "success", "data": new_data})

@app.route('/api/delete_month', methods=['POST'])
@login_required
def delete_month():
    month_id = request.json.get('id')
    all_data = load_data()
    if month_id in all_data:
        del all_data[month_id]
        save_data(all_data)
    return jsonify({"status": "success"})

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
    all_data = load_data()
    all_data[month_id] = {
        "income": [{'id': 'csv-import', 'source': 'CSV Import', 'amount': income}],
        "openingBalance": opening_balance,
        "paidExpenses": paid_expenses,
        "pendingExpenses": pending_expenses,
        "personalExpenses": personal_expenses
    }
    save_data(all_data)

    return jsonify({"status": "success", "data": all_data[month_id]})

# --- Long Pending Payments (Global) ---
@app.route('/api/long_pending', methods=['GET'])
@login_required
def get_all_long_pending():
    data = load_data()
    return jsonify(data.get('_longPending', []))

@app.route('/api/long_pending', methods=['POST'])
@login_required
def add_long_pending():
    req = request.json
    all_data = load_data()

    if '_longPending' not in all_data:
        all_data['_longPending'] = []

    new_item = {
        "id": req.get('id'),
        "reason": req.get('reason'),
        "totalAmount": float(req.get('totalAmount')),
        "paidAmount": float(req.get('paidAmount', 0)),
        "remainingAmount": float(req.get('totalAmount')) - float(req.get('paidAmount', 0)),
        "category": req.get('category', ''),
        "createdDate": req.get('createdDate', datetime.now().strftime('%Y-%m-%d')),
        "status": "active"
    }

    all_data['_longPending'].append(new_item)
    save_data(all_data)

    return jsonify({"status": "success", "data": new_item})

@app.route('/api/long_pending/<item_id>', methods=['DELETE'])
@login_required
def delete_long_pending(item_id):
    all_data = load_data()
    long_pending = all_data.get('_longPending', [])
    all_data['_longPending'] = [item for item in long_pending if str(item.get('id')) != str(item_id)]
    save_data(all_data)
    return jsonify({"status": "success"})

@app.route('/api/long_pending/<item_id>/partial_payment', methods=['POST'])
@login_required
def make_partial_payment(item_id):
    req = request.json
    payment_amount = float(req.get('amount', 0))
    month_id = req.get('month_id')

    if payment_amount <= 0:
        return jsonify({"status": "error", "message": "Payment amount must be positive"}), 400

    if not month_id:
        return jsonify({"status": "error", "message": "Month ID required"}), 400

    all_data = load_data()

    if month_id not in all_data:
        return jsonify({"status": "error", "message": "Month not found"}), 404

    long_pending = all_data.get('_longPending', [])
    item_found = False

    for item in long_pending:
        if str(item.get('id')) == str(item_id):
            if payment_amount > item['remainingAmount']:
                return jsonify({"status": "error", "message": "Payment exceeds remaining amount"}), 400

            item['paidAmount'] += payment_amount
            item['remainingAmount'] -= payment_amount

            if item['remainingAmount'] <= 0:
                item['status'] = 'completed'

            # Add to month's paid expenses
            if 'paidExpenses' not in all_data[month_id]:
                all_data[month_id]['paidExpenses'] = []

            payment_entry = {
                "id": f"lp-{item_id}-{int(datetime.now().timestamp())}",
                "reason": f"Partial: {item['reason']}",
                "category": "Long Pending",
                "date": datetime.now().strftime('%Y-%m-%d'),
                "amount": payment_amount,
                "mode": req.get('mode', 'Online'),
                "isLongPending": True,
                "linkedId": item_id
            }

            all_data[month_id]['paidExpenses'].append(payment_entry)
            item_found = True
            break

    if not item_found:
        return jsonify({"status": "error", "message": "Item not found"}), 404

    save_data(all_data)
    return jsonify({"status": "success"})

@app.route('/api/month/<month_id>/expense/<expense_id>', methods=['DELETE'])
@login_required
def delete_expense(month_id, expense_id):
    all_data = load_data()
    if month_id not in all_data:
        return jsonify({"status": "error", "message": "Month not found"}), 404

    month_data = all_data[month_id]
    paid_expenses = month_data.get('paidExpenses', [])

    expense_to_delete = None
    new_paid_expenses = []

    for exp in paid_expenses:
        if str(exp.get('id')) == str(expense_id):
            expense_to_delete = exp
        else:
            new_paid_expenses.append(exp)

    if not expense_to_delete:
        return jsonify({"status": "error", "message": "Expense not found"}), 404

    # If it's a long pending payment, reverse the transaction
    if expense_to_delete.get('isLongPending') and expense_to_delete.get('linkedId'):
        linked_id = expense_to_delete.get('linkedId')
        amount = float(expense_to_delete.get('amount', 0))

        long_pending = all_data.get('_longPending', [])
        for item in long_pending:
            if str(item.get('id')) == str(linked_id):
                item['paidAmount'] -= amount
                item['remainingAmount'] += amount
                item['status'] = 'active' # Re-activate if it was completed
                break

    all_data[month_id]['paidExpenses'] = new_paid_expenses
    save_data(all_data)

    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')