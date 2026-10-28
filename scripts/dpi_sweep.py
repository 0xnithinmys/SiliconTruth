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
from silicontruth.verify.text_corroboration import Corroboration, corroborate_register
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
    # The text layer is DPI-independent: it comes from the PDF, not the
    # render, which is exactly why it can corroborate a degraded read.
    from silicontruth.ingest.pdf_render import extract_spans

    spans = extract_spans(args.pdf, 1)
    reg_width = truth["register"]["width"]
    provider = get_provider()
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    print(f"provider: {provider.capabilities.name}")
    print(f"{'DPI':>5}  {'px':>10}  {'exact':>7}  {'widths':>7}  "
          f"{'Z3':>5}  {'names':>6}  verdict")
    print("-" * 84)

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
            print(f"{dpi:>5}  {row['px']:>10}  {'--':>7}  {'--':>7}  "
                  f"{'n/a':>5}  {'n/a':>6}  no IR produced (safe)")
            continue

        got = {
            (f.name, f.msb, f.lsb) for f in rep.register.fields if not f.reserved
        }
        exact = len(want & got)
        width_sum = sum(f.msb - f.lsb + 1 for f in rep.register.fields)

        ir = to_ir([rep], chip="synthetic", peripheral="USART1",
                   base_address=truth["peripheral"]["base_address"])
        result = audit(ir)

        # Both gates. Z3 proves arithmetic; corroboration checks that each
        # name was actually printed. The second exists because the first
        # cannot catch a consistent relabeling, which is what broke here.
        names = corroborate_register(rep.register, spans)
        gate_ok = result.passed and names.passed

        correct = exact == len(want) and width_sum == reg_width
        if correct and gate_ok:
            verdict = "correct, gates agree"
        elif not correct and not gate_ok:
            caught = "z3" if not result.passed else "names"
            verdict = f"WRONG, caught by {caught}"
        elif not correct and gate_ok:
            verdict = "WRONG, GATES MISSED IT  <-- false negative"
        else:
            verdict = "correct but a gate rejected it (conservative)"

        row.update(
            read_ok=True,
            exact=exact,
            of=len(want),
            width_sum=width_sum,
            z3="PASS" if result.passed else "FAIL",
            names="PASS" if names.passed else (
                "n/a" if names.status is Corroboration.UNAVAILABLE else "FAIL"
            ),
            violations=[str(v) for v in result.violations][:4]
            + [str(v) for v in names.violations][:4],
            # Record the actual fields, so a future failure can be diagnosed
            # without re-running inference. Omitting this cost a whole extra
            # round trip the first time.
            fields=[[f.name, f.msb, f.lsb] for f in rep.register.fields],
            verdict=verdict,
        )
        rows.append(row)
        print(f"{dpi:>5}  {row['px']:>10}  {exact:>3}/{len(want):<3}  "
              f"{width_sum:>3}/{reg_width:<3}  {row['z3']:>5}  "
              f"{row['names']:>6}  {verdict}")
        for v in row["violations"][:2]:
            print(f"{'':>42}  {v}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")

    false_negatives = [r for r in rows if "false negative" in r.get("verdict", "")]
    wrong_reads = [
        r for r in rows if r.get("read_ok") and r.get("exact", 0) != r.get("of", 0)
    ]
    refused = [r for r in rows if not r.get("read_ok")]

    print()
    if false_negatives:
        print(f"  {len(false_negatives)} FALSE NEGATIVE(S): the read was wrong and")
        print("  the gate passed it. This is the most serious failure this")
        print("  project can have and must be fixed before any accuracy claim.")
    elif wrong_reads:
        print(f"  {len(wrong_reads)} wrong read(s), all caught by the gate, 0 false")
        print("  negatives. That is the property the project claims.")
    else:
        # Say exactly what was and was not tested. Claiming "no false
        # negatives" from a run that produced no wrong reads would be
        # citing an experiment that never took place.
        print("  No wrong reads occurred at these resolutions, so this run does")
        print("  NOT exercise the false-negative case. It shows only that the")
        print("  read stayed correct down to the lowest DPI that produced one.")
        print("  The gate's ability to catch a wrong read is evidenced instead")
        print("  by tests/test_z3_corruptions.py, which injects 10 deliberate")
        print("  corruptions and requires all 10 to be named.")
    if refused:
        print()
        for r in refused:
            detail = r.get("detail", "")
            why = ("the reasoning pass exhausted the token budget"
                   if "finish_reason=length" in detail
                   else "the response was unusable")
            print(f"  {r['dpi']} DPI: no IR produced -- {why}.")
        print("  A read that produces nothing is a SAFE failure: no code is")
        print("  generated from it. It is not the model judging the page")
        print("  illegible, which it never claims to do.")
    print(f"  wrote {args.out}")
    return 1 if false_negatives else 0


if __name__ == "__main__":
    raise SystemExit(main())
