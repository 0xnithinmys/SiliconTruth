import sys
import pymupdf as fitz
doc = fitz.open(sys.argv[1])
pg = int(sys.argv[2])
print(doc[pg - 1].get_text()[: int(sys.argv[3]) if len(sys.argv) > 3 else 1400])
doc.close()
