import re, sys
import pymupdf as fitz
doc = fitz.open(sys.argv[1])
pat = re.compile(r"UART:\s*(UART\w+)\s*Register")
off = re.compile(r"Offset:\s*(0x[0-9A-Fa-f]+)")
for i in range(400, 450):
    t = doc[i].get_text()
    for m in pat.finditer(t):
        tail = t[m.end(): m.end() + 120]
        o = off.search(tail)
        print(f"p.{i+1:4}  {m.group(1):14} offset={o.group(1) if o else '?'}")
doc.close()
