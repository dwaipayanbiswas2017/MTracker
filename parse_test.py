import os
import xml.etree.ElementTree as ET
from datetime import datetime

EXTRACT_PATH = '/tmp/xlsx_extract'

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

def parse_all():
    ss = get_shared_strings()
    sheets = get_sheet_mapping()
    
    relevant_sheets = []
    for s in sheets:
        name = s['name']
        if '-25' in name or '-26' in name or name in ['FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL']:
            relevant_sheets.append(s)
            
    def sheet_sort_key(s):
        name = s['name']
        try:
            if '-' in name: return datetime.strptime(name, '%b-%y')
            else: return datetime.strptime(name, '%b').replace(year=2026)
        except: return datetime.now()
            
    relevant_sheets.sort(key=sheet_sort_key)
    
    long_pending_state = {}
    
    for s in relevant_sheets:
        month_name = s['name']
        try:
            if '-' in month_name: dt = datetime.strptime(month_name, '%b-%y')
            else: dt = datetime.strptime(month_name, '%b').replace(year=2026)
            month_key = dt.strftime('%Y-%m')
        except:
            continue
            
        print(f"\n--- {month_key} ({month_name}) ---")
        rows = parse_sheet(s['path'], ss)
        
        # Sections: 
        # 1. Main Paid
        # 2. Pending
        # 3. Personal
        # 4. Long Pending (row >= 70)
        
        section = 'paid'
        paid = []
        pending = []
        personal = []
        current_long_pending = {}
        
        for r_idx in sorted(rows.keys()):
            row = rows[r_idx]
            if r_idx < 3: continue
            
            val_a = str(row.get('A', '')).upper().strip()
            
            if val_a == 'PENDING':
                section = 'pending'
                continue
            elif val_a == 'PERSONAL EXPENSES' or val_a == 'BANGALORE EXPENSES' or val_a == 'BANGALORE EXPENSE':
                section = 'personal'
                continue
            elif val_a == 'TOTAL' or 'TOTAL EXPENSE' in val_a:
                continue
                
            if r_idx >= 70:
                section = 'long_pending'
                
            reason = row.get('A')
            if section == 'personal':
                reason = row.get('G') # In personal section, G is reason, I is amount
                amt = row.get('I')
            else:
                amt = row.get('D')
                
            if not reason or not amt or reason.upper() == 'PAYMENT REASON': continue
            if reason.upper() in ['TYPE', 'COLOR CODE', 'TOTAL']: continue
            
            try: amount = float(amt)
            except: continue
            if amount <= 0: continue
            
            if section == 'paid':
                if 'BANGALORE EXPENSE' not in reason.upper():
                    paid.append((reason, amount))
                else:
                    print(f"    Skipping cumulative Bangalore Expense: {amount}")
            elif section == 'personal':
                personal.append((reason, amount))
            elif section == 'pending':
                pending.append((reason, amount))
            elif section == 'long_pending':
                current_long_pending[reason] = amount
                
        print(f"  Paid: {len(paid)}")
        print(f"  Personal: {len(personal)}")
        print(f"  Pending: {len(pending)}")
        
        # Process Long Pending State
        for name, amt in current_long_pending.items():
            if name not in long_pending_state:
                print(f"  [New Long Pending] {name}: {amt}")
                long_pending_state[name] = amt
            else:
                prev_amt = long_pending_state[name]
                if amt < prev_amt:
                    paid_amt = prev_amt - amt
                    print(f"  [Long Pending Payment] {name}: Paid {paid_amt}, Remaining: {amt}")
                    long_pending_state[name] = amt
        
        # Check for completed long pendings
        for name in list(long_pending_state.keys()):
            if name not in current_long_pending:
                paid_amt = long_pending_state[name]
                print(f"  [Long Pending Completed] {name}: Paid {paid_amt}")
                del long_pending_state[name]

if __name__ == '__main__':
    if not os.path.exists(EXTRACT_PATH):
        os.system(f"mkdir -p {EXTRACT_PATH} && unzip -q Expense_report.xlsx -d {EXTRACT_PATH}")
    parse_all()