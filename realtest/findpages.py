"""Locate the pages that carry a peripheral's register descriptions."""
import sys
import pymupdf as fitz

pdf, needles = sys.argv[1], sys.argv[2].split(",")
doc = fitz.open(pdf)
print("pages:", doc.page_count)
hits = {}
for i in range(doc.page_count):
    t = doc[i].get_text()
    found = [n for n in needles if n in t]
    if found:
        hits[i + 1] = found
for pg, f in list(hits.items())[:40]:
    print(f"  p.{pg:4}  {','.join(f)[:70]}")
doc.close()
