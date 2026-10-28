"""Ground truth from the vendor SVD. Peripheral-level <name> only.

A naive regex matched RESETS instead of UART0, because RESETS has a FIELD
called UART0. Matching the name that sits directly under <peripheral> is the
whole fix, and the base address is the check that caught it.
"""
import re, sys, json

def peripherals(xml):
    out = {}
    for m in re.finditer(r"<peripheral\b[^>]*>(.*?)</peripheral>", xml, re.S):
        body = m.group(1)
        # The peripheral's own name is the first <name> before any <registers>.
        head = body.split("<registers>")[0]
        nm = re.search(r"<name>([^<]+)</name>", head)
        if not nm:
            continue
        base = re.search(r"<baseAddress>([^<]+)</baseAddress>", head)
        regs = {}
        for r in re.finditer(r"<register>(.*?)</register>", body, re.S):
            rb = r.group(1)
            rn = re.search(r"<name>([^<]+)</name>", rb)
            off = re.search(r"<addressOffset>([^<]+)</addressOffset>", rb)
            if not rn or not off:
                continue
            fields = {}
            for f in re.finditer(r"<field>(.*?)</field>", rb, re.S):
                fb = f.group(1)
                fn = re.search(r"<name>([^<]+)</name>", fb)
                br = re.search(r"<bitRange>\[(\d+):(\d+)\]</bitRange>", fb)
                if fn and br:
                    fields[fn.group(1)] = (int(br.group(1)), int(br.group(2)))
            regs[rn.group(1)] = {"offset": int(off.group(1), 16), "fields": fields}
        out[nm.group(1)] = {"base": int(base.group(1), 16) if base else None, "regs": regs}
    return out

if __name__ == "__main__":
    xml = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    p = peripherals(xml)
    want = sys.argv[2]
    d = p[want]
    print(f"{want} base=0x{d['base']:08X} registers={len(d['regs'])}")
    for rn, r in list(d["regs"].items()):
        fs = ", ".join(f"{n}[{a}:{b}]" for n, (a, b) in list(r["fields"].items())[:4])
        print(f"  {rn:10} +0x{r['offset']:02X} fields={len(r['fields']):2}  {fs}")
    print("total fields:", sum(len(r["fields"]) for r in d["regs"].values()))
