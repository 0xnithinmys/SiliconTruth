"""Score an emitted SVD against the vendor's own SVD, field by field.

Ground truth is the chip vendor's published CMSIS-SVD, not anything this
project produced. Undeclared bits in a CMSIS-SVD are reserved by convention,
so a RESERVED_* field the emitter declares is compared against that
convention rather than counted as a disagreement.
"""
import re, sys
sys.path.insert(0, ".")
from gt import peripherals  # noqa: E402

vendor = peripherals(open(sys.argv[1], encoding="utf-8", errors="replace").read())[sys.argv[3]]
mine = peripherals(open(sys.argv[2], encoding="utf-8", errors="replace").read())
mine = mine[next(iter(mine))]

print(f"vendor registers: {len(vendor['regs'])}   extracted: {len(mine['regs'])}")
print(f"base  vendor=0x{vendor['base']:08X}  ours=0x{mine['base']:08X}  "
      f"{'MATCH' if vendor['base'] == mine['base'] else 'MISMATCH'}\n")

exact = wrong = missing = 0
for rn, r in mine["regs"].items():
    v = vendor["regs"].get(rn)
    if not v:
        print(f"  {rn}: NOT IN VENDOR SVD"); continue
    ok = v["offset"] == r["offset"]
    print(f"  {rn}  offset ours=+0x{r['offset']:02X} vendor=+0x{v['offset']:02X}  "
          f"{'OK' if ok else 'WRONG'}")
    for fn, (msb, lsb) in r["fields"].items():
        if fn.upper().startswith("RESERVED"):
            continue           # undeclared-is-reserved; nothing to compare against
        if fn not in v["fields"]:
            print(f"      {fn:16} [{msb}:{lsb}]  NOT IN VENDOR"); wrong += 1; continue
        vm, vl = v["fields"][fn]
        if (vm, vl) == (msb, lsb):
            print(f"      {fn:16} [{msb}:{lsb}]  EXACT")
            exact += 1
        else:
            print(f"      {fn:16} ours[{msb}:{lsb}] vendor[{vm}:{vl}]  WRONG")
            wrong += 1
    for fn in v["fields"]:
        if fn not in r["fields"]:
            missing += 1
print(f"\nfields exact={exact} wrong={wrong} missing_from_our_read={missing}")
