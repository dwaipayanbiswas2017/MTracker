import os
import xml.etree.ElementTree as ET

EXTRACT_PATH = '/tmp/xlsx_extract'
ss = [ "".join([node.text for node in si.findall('.//ns:t', {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}) if node.text]) for si in ET.parse(os.path.join(EXTRACT_PATH, 'xl/sharedStrings.xml')).getroot().findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si') ]

path = os.path.join(EXTRACT_PATH, 'xl/worksheets/sheet45.xml')
tree = ET.parse(path)
ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
for row in tree.getroot().findall('.//ns:row', ns):
    r_idx = int(row.get('r'))
    if r_idx >= 14 and r_idx < 30:
        row_data = {}
        for cell in row.findall('ns:c', ns):
            r = cell.get('r')
            col = "".join([c for c in r if not c.isdigit()])
            t = cell.get('t')
            v_node = cell.find('ns:v', ns)
            val = v_node.text if v_node is not None else None
            if t == 's' and val is not None:
                val = ss[int(val)]
            row_data[col] = val
        print(f"Row {r_idx}: G={row_data.get('G')}, H={row_data.get('H')}, I={row_data.get('I')}")
