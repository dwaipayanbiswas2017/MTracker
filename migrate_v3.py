import os
import xml.etree.ElementTree as ET
from datetime import datetime
import time
from database_controller import DatabaseController
import dotenv

dotenv.load_dotenv()

DB_CONFIG = {
    'host': os.getenv('host'),
    'user': os.getenv('user'),
    'password': os.getenv('password'),
    'database': os.getenv('database')
}
db = DatabaseController(DB_CONFIG)
USER_ID = '1768237004.771031'
EXTRACT_PATH = '/tmp/xlsx_extract'
DEFAULT_ACC_ID = 1 # SBI-6594
SAVINGS_ACC_ID = 2 # SBI-2390

def get_shared_strings():
    ss_path = os.path.join(EXTRACT_PATH, 'xl/sharedStrings.xml')
    tree = ET.parse(ss_path)
    root = tree.getroot()
    ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    strings = []
    for si in root.findall('ns:si', ns):
        text = "".join([node.text for node in si.findall('.//ns:t', ns) if node.text])
        strings.append(text)
    return strings

def get_sheet_mapping():
    workbook_path = os.path.join(EXTRACT_PATH, 'xl/workbook.xml')
    tree = ET.parse(workbook_path)
    root = tree.getroot()
    ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    sheets = []
    for sheet in root.findall('.//ns:sheet', ns):
        sheets.append({
            'name': sheet.get('name'),
            'rId': sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        })
    rels_path = os.path.join(EXTRACT_PATH, 'xl/_rels/workbook.xml.rels')
    tree_rels = ET.parse(rels_path)
    ns_rels = {'ns': 'http://schemas.openxmlformats.org/package/2006/relationships'}
    rel_map = {rel.get('Id'): rel.get('Target') for rel in tree_rels.getroot().findall('ns:Relationship', ns_rels)}
    for s in sheets:
        s['path'] = os.path.join(EXTRACT_PATH, 'xl', rel_map[s['rId']])
    return sheets

def parse_date(date_str, month_key):
    formats = ['%d-%m-%Y', '%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y']
    if date_str:
        for fmt in formats:
            try: return datetime.strptime(date_str, fmt).strftime('%Y-%m-%d')
            except: pass
    return f"{month_key}-01"

def get_cat_id(cursor, cat_name):
    if not cat_name: cat_name = 'Other'
    cursor.execute("SELECT id FROM categories WHERE user_id = %s AND category_name = %s", (USER_ID, cat_name))
    row = cursor.fetchone()
    if row: return row[0]
    cursor.execute("INSERT INTO categories (user_id, category_name) VALUES (%s, %s)", (USER_ID, cat_name))
    return cursor.lastrowid

def parse_sheet(path, shared_strings):
    tree = ET.parse(path)
    ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    rows = {}
    for row in tree.getroot().findall('.//ns:row', ns):
        r_idx = int(row.get('r'))
        row_data = {}
        for cell in row.findall('ns:c', ns):
            col = "".join([c for c in cell.get('r') if not c.isdigit()])
            v_node = cell.find('ns:v', ns)
            val = v_node.text if v_node is not None else None
            if cell.get('t') == 's' and val is not None:
                val = shared_strings[int(val)]
            row_data[col] = val
        rows[r_idx] = row_data
    return rows

def migrate_all():
    ss = get_shared_strings()
    sheets = get_sheet_mapping()
    
    relevant_sheets = []
    for s in sheets:
        name = s['name']
        if '-25' in name or '-26' in name:
            relevant_sheets.append(s)
            
    def sheet_sort_key(s):
        name = s['name']
        try: return datetime.strptime(name, '%b-%y')
        except: return datetime.now()
            
    relevant_sheets.sort(key=sheet_sort_key)
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    long_pending_state = {}
    
    for s in relevant_sheets:
        month_name = s['name']
        dt = datetime.strptime(month_name, '%b-%y')
        month_key = dt.strftime('%Y-%m')
            
        print(f"\n--- Porting {month_key} ({month_name}) ---")
        rows = parse_sheet(s['path'], ss)
        
        cursor.execute("SELECT id FROM months WHERE user_id = %s AND month_key = %s", (USER_ID, month_key))
        existing_month = cursor.fetchone()
        if not existing_month:
            year, month_num = map(int, month_key.split('-'))
            cursor.execute("INSERT INTO months (user_id, month_key, year, month) VALUES (%s, %s, %s, %s)", (USER_ID, month_key, year, month_num))
            month_id = cursor.lastrowid
            conn.commit()
        else:
            month_id = existing_month[0]
            
        opening_balance = 0
        income_val = 0
        if 1 in rows and 'L' in rows[1]:
            try: opening_balance = float(rows[1]['L'])
            except: pass
        if 2 in rows and 'L' in rows[2]:
            try: income_val = float(rows[2]['L'])
            except: pass

        cursor.execute("REPLACE INTO opening_balances (user_id, month_id, account_id, amount) VALUES (%s, %s, %s, %s)", (USER_ID, month_id, DEFAULT_ACC_ID, opening_balance))
        if income_val > 0:
            cursor.execute("INSERT INTO income (id, user_id, month_id, account_id, source, amount) VALUES (%s, %s, %s, %s, 'Salary/Excel', %s)", (f"inc-{month_id}-{int(time.time()*1000)}", USER_ID, month_id, DEFAULT_ACC_ID, income_val))

        section = 'paid'
        current_long_pending = {}
        
        for r_idx in sorted(rows.keys()):
            row = rows[r_idx]
            if r_idx < 3: continue
            
            val_a = str(row.get('A', '')).upper().strip()
            if val_a == 'PENDING':
                section = 'pending'
                continue
            
            if r_idx >= 70:
                section = 'long_pending'
            
            # --- DAILY EXPENSES LOGIC (Columns G & I) ---
            # As requested, do NOT port these into Paid Expenses. The web app will sum them and double count.
            # We skip columns G & I entirely because their sum is already included in the cumulative 
            # "Bangalore Expense" or "Personal Expense" entries in columns A & D.
            
            # --- MAIN EXPENSES LOGIC (Columns A & D) ---
            reason = row.get('A')
            cat_name = row.get('B')
            date_str = row.get('C')
            amount_str = row.get('D')
                
            if not reason or not amount_str or reason.upper() == 'PAYMENT REASON': continue
            if reason.upper() in ['TYPE', 'COLOR CODE', 'TOTAL', 'TOTAL EXPENSE']: continue
            
            try: amount = float(amount_str)
            except: continue
            if amount <= 0: continue
            
            exp_date = parse_date(date_str, month_key)
            
            if section == 'paid':
                if reason.upper() == 'SAVINGS':
                    cat_id = get_cat_id(cursor, 'Savings')
                    cursor.execute("""
                        INSERT INTO paid_expenses (id, user_id, month_id, account_id, category_id, reason, amount, expense_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (f"sav-exp-{r_idx}-{int(time.time()*10000)}", USER_ID, month_id, DEFAULT_ACC_ID, cat_id, reason, amount, exp_date))
                    cursor.execute("""
                        INSERT INTO income (id, user_id, month_id, account_id, source, amount, income_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (f"sav-inc-{r_idx}-{int(time.time()*10000)}", USER_ID, month_id, SAVINGS_ACC_ID, 'Savings Transfer', amount, exp_date))
                else:
                    # Note: We now INCLUDE Bangalore Expense/Personal Expenses from column A/D
                    # This ensures the cumulative total is correct!
                    cat_id = get_cat_id(cursor, cat_name)
                    cursor.execute("""
                        INSERT INTO paid_expenses (id, user_id, month_id, account_id, category_id, reason, amount, expense_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (f"exp-{r_idx}-{int(time.time()*10000)}", USER_ID, month_id, DEFAULT_ACC_ID, cat_id, reason, amount, exp_date))
                    
            elif section == 'pending':
                cat_id = get_cat_id(cursor, cat_name)
                cursor.execute("""
                    INSERT INTO pending_expenses (id, user_id, month_id, category_id, reason, amount, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                """, (f"pend-{r_idx}-{int(time.time()*10000)}", USER_ID, month_id, cat_id, reason, amount))
                
            elif section == 'long_pending':
                current_long_pending[reason] = amount
                
        # --- LONG PENDING LOGIC ---
        for name, amt in current_long_pending.items():
            if name not in long_pending_state:
                print(f"  [New Long Pending] {name}: {amt}")
                lp_id = f"lp-{month_id}-{int(time.time()*10000)}"
                cursor.execute("""
                    INSERT INTO long_pending (id, user_id, reason, total_amount, category, created_date)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (lp_id, USER_ID, name, amt, 'General', f"{month_key}-01"))
                long_pending_state[name] = {'id': lp_id, 'amount': amt}
            else:
                prev_state = long_pending_state[name]
                prev_amt = prev_state['amount']
                lp_id = prev_state['id']
                if amt < prev_amt:
                    paid_amt = prev_amt - amt
                    print(f"  [Long Pending Payment] {name}: Paid {paid_amt}, Remaining: {amt}")
                    conn.commit() # Commit pending inserts first
                    db.make_partial_payment(USER_ID, lp_id, month_key, paid_amt, 'SBI-6594', 'online')
                    long_pending_state[name]['amount'] = amt
                    
        for name in list(long_pending_state.keys()):
            if name not in current_long_pending:
                prev_state = long_pending_state[name]
                paid_amt = prev_state['amount']
                lp_id = prev_state['id']
                print(f"  [Long Pending Completed] {name}: Paid {paid_amt}")
                conn.commit() # Commit pending inserts first
                db.make_partial_payment(USER_ID, lp_id, month_key, paid_amt, 'SBI-6594', 'online')
                del long_pending_state[name]

        conn.commit()

    conn.close()

if __name__ == '__main__':
    migrate_all()
