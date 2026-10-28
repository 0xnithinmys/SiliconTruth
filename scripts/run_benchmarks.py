#!/usr/bin/env python3
"""Score the pipeline across the synthetic suite, and print a scorecard.

Every number traces to a chip's ground_truth.json. The scorecard is
labelled SYNTHETIC wherever it is shown, because these pages were drawn by
the same project that reads them and that is not evidence about real
silicon -- it is a regression instrument.

What is measured, per register:

  fields_exact   name, msb and lsb all matching ground truth
  offset         the printed offset parsed correctly
  reset          the printed reset value parsed correctly
  z3             the arithmetic gate's verdict
  names          every returned name actually printed on the page
  grid           every field under the column the page prints it in

And per chip, errata linked versus errata that must be linked, plus any
spurious links -- an over-eager linker injects workarounds corresponding
to nothing real, which is just a different way of shipping a wrong driver.

The exit code is non-zero if any chip has a FALSE NEGATIVE: a wrong read
that every gate passed. That is the one result that invalidates the
project's claim, so it fails the run rather than appearing in a table.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silicontruth.bench.suite import SUITE, by_slug
from silicontruth.ingest.pdf_render import extract_spans
from silicontruth.ir.errata_linker import apply_to_ir, extract_errata
from silicontruth.ir.extractor import ExtractionError, extract_register, to_ir
from silicontruth.models.provider import ProviderError, Truncated, get_provider
from silicontruth.verify.grid_corroboration import GridStatus, corroborate_grid
from silicontruth.verify.text_corroboration import Corroboration, corroborate_register
from silicontruth.verify.z3_register_audit import audit


def score_register(got, truth_reg: dict) -> dict:
    want = {
        (f["name"].upper(), f["msb"], f["lsb"])
        for f in truth_reg["fields"]
        if not f["reserved"]
    }
    have = {
        (f.name.upper(), f.msb, f.lsb) for f in got.fields if not f.reserved
    }
    return {
        "fields_total": len(want),
        "fields_exact": len(want & have),
        "missed": sorted(n for n, _, _ in (want - have)),
        "spurious": sorted(n for n, _, _ in (have - want)),
        "offset_ok": got.offset == truth_reg["offset"],
        "reset_ok": got.reset_value == truth_reg["reset_value"],
        "width_ok": got.width == truth_reg["width"],
    }


def run_chip(spec, root: Path, dpi: int, max_tokens: int, provider) -> dict:
    d = root / spec.slug
    truth = json.loads((d / "ground_truth.json").read_text(encoding="utf-8"))
    pdf = d / "datasheet.pdf"

    started = time.perf_counter()
    reports, per_register = [], []
    for i, truth_reg in enumerate(truth["registers"], start=1):
        try:
            rep = extract_register(
                provider, pdf, i, dpi=dpi, width=truth_reg["width"],
                max_tokens=max_tokens,
            )
        except (ExtractionError, Truncated, ProviderError) as e:
            per_register.append({
                "register": truth_reg["name"], "read": False,
                "error": f"{type(e).__name__}: {str(e)[:150]}",
            })
            continue
        reports.append(rep)
        s = score_register(rep.register, truth_reg)
        s.update(register=truth_reg["name"], read=True, page=i)
        per_register.append(s)

    if not reports:
        return {
            "chip": spec.slug, "read_any": False, "registers": per_register,
            "elapsed_s": round(time.perf_counter() - started, 1),
        }

    ir = to_ir(
        reports, chip=spec.chip, peripheral=spec.peripheral,
        base_address=spec.base_address,
    )
    z3 = audit(ir)

    names_ok, grid_ok, grid_unavailable = True, True, False
    gate_detail: list[str] = []
    for rep in reports:
        page = rep.register.provenance.page
        spans = extract_spans(str(pdf), page)
        n = corroborate_register(rep.register, spans)
        if not n.passed:
            names_ok = False
            gate_detail += [str(v) for v in n.violations[:3]]
        g = corroborate_grid(rep.register, spans)
        if g.status is GridStatus.UNAVAILABLE:
            grid_unavailable = True
        elif not g.passed:
            grid_ok = False
            gate_detail += [str(v) for v in g.violations[:3]]

    # Errata
    errata = {"linked": 0, "required": 0, "spurious": [], "rejected": 0}
    errata_pdf = d / "errata.pdf"
    if errata_pdf.exists():
        must = {e["errata_id"] for e in truth["errata"] if e["must_link"]}
        errata["required"] = len(must)
        try:
            link = extract_errata(provider, ir, errata_pdf, 1, dpi=dpi,
                                  max_tokens=max_tokens * 2)
            apply_to_ir(ir, link)
            got_ids = set(link.applied_ids)
            errata["linked"] = len(must & got_ids)
            errata["spurious"] = sorted(got_ids - must)
            errata["rejected"] = len(link.rejected)
            errata["missed"] = sorted(must - got_ids)
        except (ProviderError, Truncated) as e:
            errata["error"] = str(e)[:150]

    total = sum(r.get("fields_total", 0) for r in per_register if r.get("read"))
    exact = sum(r.get("fields_exact", 0) for r in per_register if r.get("read"))
    read_correct = (
        exact == total
        and all(r.get("offset_ok") and r.get("reset_ok")
                for r in per_register if r.get("read"))
        and all(r.get("read") for r in per_register)
    )
    gates_pass = z3.passed and names_ok and grid_ok

    return {
        "chip": spec.slug,
        "read_any": True,
        "registers": per_register,
        "fields_total": total,
        "fields_exact": exact,
        "read_correct": read_correct,
        "z3": z3.passed,
        "names": names_ok,
        "grid": "n/a" if grid_unavailable else grid_ok,
        "gates_pass": gates_pass,
        "false_negative": (not read_correct) and gates_pass,
        "gate_detail": gate_detail[:6],
        "errata": errata,
        "elapsed_s": round(time.perf_counter() - started, 1),
        "z3_ms": round(z3.elapsed_ms, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="benchmarks/suite", type=Path)
    ap.add_argument("--chips", nargs="*", default=None)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--max-tokens", type=int, default=12288)
    ap.add_argument("--out", default="benchmarks/scorecard.json", type=Path)
    args = ap.parse_args()

    specs = [by_slug(c) for c in args.chips] if args.chips else SUITE
    provider = get_provider()
    print(f"provider: {provider.capabilities.name} "
          f"({provider.capabilities.vision_model})  dpi={args.dpi}")
    print("SYNTHETIC SUITE -- drawn by this project; not real silicon.\n")

    results = []
    for spec in specs:
        print(f"  {spec.slug} ...", flush=True)
        r = run_chip(spec, args.root, args.dpi, args.max_tokens, provider)
        results.append(r)

    print()
    hdr = (f"{'chip':10s} {'fields':>9s}  {'off':>4s} {'rst':>4s}  "
           f"{'z3':>5s} {'names':>5s} {'grid':>5s}  {'errata':>7s}  {'s':>5s}")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        if not r["read_any"]:
            print(f"{r['chip']:10s} {'no read':>9s}")
            continue
        regs = [x for x in r["registers"] if x.get("read")]
        off = sum(1 for x in regs if x["offset_ok"])
        rst = sum(1 for x in regs if x["reset_ok"])
        e = r["errata"]
        print(
            f"{r['chip']:10s} {r['fields_exact']:>4d}/{r['fields_total']:<4d} "
            f" {off}/{len(regs):<2d} {rst}/{len(regs):<2d}  "
            f"{str(r['z3']):>5s} {str(r['names']):>5s} {str(r['grid']):>5s}  "
            f"{e['linked']:>3d}/{e['required']:<3d}  {r['elapsed_s']:>5.1f}"
        )

    ok = [r for r in results if r["read_any"]]
    fn = [r for r in ok if r["false_negative"]]
    tot = sum(r["fields_total"] for r in ok)
    exact = sum(r["fields_exact"] for r in ok)
    el = sum(r["errata"]["linked"] for r in ok)
    er = sum(r["errata"]["required"] for r in ok)
    spurious = sum(len(r["errata"]["spurious"]) for r in ok)

    print()
    if tot:
        print(f"  fields exact : {exact}/{tot} ({100 * exact / tot:.0f}%)")
    if er:
        print(f"  errata linked: {el}/{er} ({100 * el / er:.0f}%), "
              f"{spurious} spurious")

    for r in ok:
        if not r["read_correct"] and not r["gates_pass"]:
            print(f"  {r['chip']}: wrong read, CAUGHT by the gates")
            for d in r["gate_detail"][:2]:
                print(f"      {d}")

    print()
    if fn:
        print(f"  {len(fn)} FALSE NEGATIVE(S): "
              + ", ".join(r["chip"] for r in fn))
        print("  A wrong read that every gate passed. This is the one result")
        print("  that invalidates the project's claim; it fails the run.")
    else:
        print("  0 false negatives: no chip had a wrong read that the gates")
        print("  passed. That is the property the project claims.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"synthetic": True, "dpi": args.dpi, "chips": results},
                   indent=2),
        encoding="utf-8",
    )
    print(f"  wrote {args.out}")
    return 1 if fn else 0


if __name__ == "__main__":
    raise SystemExit(main())
