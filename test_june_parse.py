import os
import xml.etree.ElementTree as ET

EXTRACT_PATH = '/tmp/xlsx_extract'
ss = [ "".join([node.text for node in si.findall('.//ns:t', {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}) if node.text]) for si in ET.parse(os.path.join(EXTRACT_PATH, 'xl/sharedStrings.xml')).getroot().findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si') ]

path = os.path.join(EXTRACT_PATH, 'xl/worksheets/sheet52.xml')
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
            val = ss[int(val)]
        row_data[col] = val
    rows[r_idx] = row_data

section = 'paid'
for r_idx in sorted(rows.keys()):
    row = rows[r_idx]
    if r_idx < 3: continue
    
    val_a = str(row.get('A', '')).upper().strip()
    if val_a == 'PENDING':
        section = 'pending'
        continue
    
    if r_idx >= 70:
        section = 'long_pending'
    
    reason = row.get('A')
    cat_name = row.get('B')
    date_str = row.get('C')
    amount_str = row.get('D')
        
    if not reason or not amount_str or reason.upper() == 'PAYMENT REASON': 
        print(f"Row {r_idx} skipped due to missing reason/amount: {reason}, {amount_str}")
        continue
    if reason.upper() in ['TYPE', 'COLOR CODE', 'TOTAL', 'TOTAL EXPENSE']: 
        print(f"Row {r_idx} skipped due to excluded word: {reason}")
        continue
    
    try: amount = float(amount_str)
    except: 
        print(f"Row {r_idx} skipped due to float parse fail: {amount_str}")
        continue
        
    if amount <= 0: 
        print(f"Row {r_idx} skipped due to zero amount")
        continue
    
    print(f"Row {r_idx}: Inserted! section={section}, reason={reason}, amount={amount}")
