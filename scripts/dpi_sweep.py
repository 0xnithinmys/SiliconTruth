#!/usr/bin/env python3
"""Find the resolution at which the read breaks -- and check the gate notices.

The synthetic fixture at 200 DPI is read correctly by the naive baseline
and by SiliconTruth alike, so it does not discriminate between them. That
is an honest result and it is recorded as such.

The interesting question is therefore not "who reads a clean page better"
but "what happens when the page is NOT clean", which is the normal case
for a scanned reference manual. This sweep degrades the input until the
read fails and reports, at each step, the thing that actually matters:

    not whether the read was right, but whether we KNEW.

A row where the read is wrong and Z3 says PASS would be a false negative
in the gate and the most serious possible result for this project. A row
where the read is wrong and Z3 says FAIL is the system working.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silicontruth.ingest.pdf_render import render_page
from silicontruth.ir.extractor import (
    EXTRACTION_SCHEMA,
    PROMPT_PATH,
    ExtractionError,
    build_register,
    to_ir,
)
from silicontruth.models.provider import ProviderError, Truncated, get_provider
from silicontruth.verify.z3_register_audit import audit


def truth_set(truth: dict) -> set[tuple[str, int, int]]:
    return {
        (f["name"], f["msb"], f["lsb"])
        for f in truth["fields"]
        if not f["reserved"]
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="benchmarks/synthetic/synthetic_usart.pdf")
    ap.add_argument("--truth", default="benchmarks/synthetic/ground_truth.json")
    ap.add_argument("--dpi", type=int, nargs="+", default=[200, 120, 90, 72, 50])
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--out", default="benchmarks/synthetic/dpi_sweep.json")
    args = ap.parse_args()

    truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))
    want = truth_set(truth)
    reg_width = truth["register"]["width"]
    provider = get_provider()
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    print(f"provider: {provider.capabilities.name}")
    print(f"{'DPI':>5}  {'px':>10}  {'exact':>7}  {'widths':>7}  {'Z3':>6}  verdict")
    print("-" * 68)

    rows = []
    for dpi in args.dpi:
        page = render_page(args.pdf, 1, dpi=dpi)
        uri = "data:image/png;base64," + base64.b64encode(page.png).decode()
        row: dict = {"dpi": dpi, "px": f"{page.width}x{page.height}"}

        try:
            raw = provider.extract(
                prompt, schema=EXTRACTION_SCHEMA, images=[uri],
                max_tokens=args.max_tokens,
            )
            rep = build_register(raw, page=1, bbox=(0, 0, page.width, page.height))
        except (ExtractionError, Truncated, ProviderError) as e:
            # A refused read is a SAFE failure: nothing is generated from it.
            row.update(read_ok=False, z3="n/a", verdict="read refused (safe)",
                       detail=str(e)[:160])
            rows.append(row)
            print(f"{dpi:>5}  {row['px']:>10}  {'--':>7}  {'--':>7}  {'n/a':>6}  "
                  f"read refused -- nothing generated (safe)")
            continue

        got = {
            (f.name, f.msb, f.lsb) for f in rep.register.fields if not f.reserved
        }
        exact = len(want & got)
        width_sum = sum(f.msb - f.lsb + 1 for f in rep.register.fields)

        ir = to_ir([rep], chip="synthetic", peripheral="USART1",
                   base_address=truth["peripheral"]["base_address"])
        result = audit(ir)

        correct = exact == len(want) and width_sum == reg_width
        if correct and result.passed:
            verdict = "correct, gate agrees"
        elif not correct and not result.passed:
            verdict = "WRONG, gate caught it"
        elif not correct and result.passed:
            verdict = "WRONG, GATE MISSED IT  <-- false negative"
        else:
            verdict = "correct but gate rejected it (conservative)"

        row.update(
            read_ok=True,
            exact=exact,
            of=len(want),
            width_sum=width_sum,
            z3="PASS" if result.passed else "FAIL",
            violations=[str(v) for v in result.violations][:4],
            verdict=verdict,
        )
        rows.append(row)
        print(f"{dpi:>5}  {row['px']:>10}  {exact:>3}/{len(want):<3}  "
              f"{width_sum:>3}/{reg_width:<3}  {row['z3']:>6}  {verdict}")
        for v in row["violations"][:2]:
            print(f"{'':>34}  {v}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")

    false_negatives = [r for r in rows if "false negative" in r.get("verdict", "")]
    print()
    if false_negatives:
        print(f"  {len(false_negatives)} FALSE NEGATIVE(S): the read was wrong and")
        print("  the gate passed it. This is the most serious failure this")
        print("  project can have and must be fixed before any accuracy claim.")
    else:
        print("  No false negatives: every wrong read was either refused or")
        print("  failed by Z3. That is the property the project actually claims.")
    print(f"  wrote {args.out}")
    return 1 if false_negatives else 0


if __name__ == "__main__":
    raise SystemExit(main())
