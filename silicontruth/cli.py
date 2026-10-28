"""SiliconTruth command line.

    silicontruth verify   <ir.json>              Z3 gate only
    silicontruth build    <ir.json> -o <dir>     full deterministic pipeline
    silicontruth oracle   <trace.log>            judge a Renode trace
    silicontruth replay   <fixtures/>            list recorded runs
    silicontruth doctor                          what is installed, what is blocked

`build` runs everything that does not need a model: audit, retry bookkeeping,
SVD, C HAL, Renode peripheral, platform and script, and records the run as
JSONL for Keyless Replay.

The perception half (PDF -> IR) needs an inference provider. `doctor` says
plainly whether one is reachable instead of failing deep in a pipeline.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from silicontruth.ir.schema import PeripheralIR
from silicontruth.oracle.renode_oracle import evaluate, render_bus_trace
from silicontruth.replay.recorder import EventKind, Recorder, iter_runs, write_index
from silicontruth.synth.hal_c_emitter import emit_hal
from silicontruth.synth.renode_peripheral import emit_peripheral, emit_repl, emit_resc
from silicontruth.synth.svd_emitter import emit_svd, validate_svd
from silicontruth.verify.z3_register_audit import audit

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def _load(path: Path) -> PeripheralIR:
    if not path.exists():
        sys.exit(f"no such IR file: {path}")
    return PeripheralIR.model_validate_json(path.read_text(encoding="utf-8"))


def cmd_verify(args: argparse.Namespace) -> int:
    ir = _load(args.ir)
    result = audit(ir)
    print(f"{ir.chip} / {ir.peripheral}")
    print(result.summary())
    for v in result.violations:
        print(f"  {RED}x{RESET} {v}")
    for reg in ir.verified_registers:
        print(f"  {GREEN}OK{RESET} {reg.name:<8} @ +0x{reg.offset:02X}  "
              f"{len([f for f in reg.fields if not f.reserved])} fields")
    for reg in ir.unverified_registers:
        print(f"  {YELLOW}??{RESET} {reg.name:<8} UNVERIFIED: {reg.unverified_reason}")
    return 0 if result.passed else 1


def cmd_extract(args: argparse.Namespace) -> int:
    """PDF -> IR. The perception half: this is the only command that
    needs an inference provider.

    Deliberately stops at the IR and writes it to disk rather than running
    straight on to codegen. The IR is the contract, and being able to read
    the machine's answer before anything is generated from it is the
    difference between a pipeline you can audit and one you have to trust.
    Run `silicontruth build` on the result to go the rest of the way.
    """
    from silicontruth.ir.errata_linker import apply_to_ir, extract_errata
    from silicontruth.ir.extractor import ExtractionError, extract_register, to_ir
    from silicontruth.models.provider import ProviderError, get_provider

    from silicontruth.models.provider import load_env

    env = load_env()
    try:
        provider = get_provider(args.provider)
    except ProviderError as e:
        print(f"{RED}no usable inference provider: {e}{RESET}")
        print(f"{DIM}  `silicontruth doctor` shows what is configured.{RESET}")
        return 3

    caps = provider.capabilities
    print(f"provider  {caps.name}  ({caps.vision_model})")

    reports = []
    for page in args.pages:
        # Each page yields one or more regions to read. Without --segment
        # that is the whole page, which is what the pipeline has always
        # done and still works; with it, SAM locates the tables first so a
        # dense page is read one table at a time instead of all at once.
        crops: list = [None]
        if args.segment:
            from silicontruth.ingest.pdf_render import render_page
            from silicontruth.ingest.sam_segmenter import (
                SegmentationError, pad, segment_page,
            )

            try:
                rendered = render_page(args.pdf, page, dpi=args.dpi)
                regions = segment_page(
                    rendered,
                    api_key=env.get("MODEL_API_KEY", ""),
                    base_url=env.get("META_API_BASE", "https://api.meta.ai/v1"),
                    model=env.get("SAM_MODEL", "sam-3.1"),
                )
                if regions:
                    crops = [pad(r) for r in regions]
                    print(f"  p.{page:<4} {DIM}segmented into "
                          f"{len(crops)} region(s){RESET}")
                else:
                    # No detection is a normal outcome, not a failure. Falling
                    # back to the whole page keeps a page with an unusual
                    # layout working instead of silently yielding nothing.
                    print(f"  p.{page:<4} {DIM}no regions detected; "
                          f"reading the whole page{RESET}")
            except SegmentationError as e:
                print(f"  p.{page:<4} {YELLOW}segmentation unavailable "
                      f"({e}); reading the whole page{RESET}")

        for crop in crops:
            try:
                rep = extract_register(
                    provider, args.pdf, page, bbox=crop.bbox if crop else None,
                    dpi=args.dpi, max_tokens=args.max_tokens,
                    mask_id=crop.mask_id if crop else None,
                )
            except ExtractionError as e:
                # An unusable read on one region must not discard the others.
                print(f"  p.{page:<4} {RED}unusable: {e}{RESET}")
                continue
            except ProviderError as e:
                print(f"  p.{page:<4} {RED}{e}{RESET}")
                return 3
                reports.append(rep)
            r = rep.register
            print(f"  p.{page:<4} {r.name} @ +0x{r.offset:02X}  "
                  f"{len(r.fields)} fields")
            for w in rep.warnings:
                print(f"         {YELLOW}warn{RESET} {w}")

    if not reports:
        print(f"{RED}nothing extracted; refusing to write an empty IR{RESET}")
        return 1

    ir = to_ir(
        reports,
        chip=args.chip,
        peripheral=args.peripheral,
        base_address=args.base,
    )

    # The gates run here, before anything is written, so the IR on disk
    # always carries an honest verified flag rather than an optimistic one.
    result = audit(ir)
    print(f"  z3      {result.summary()}")
    for v in result.violations:
        print(f"         {RED}{v}{RESET}")

    # Z3 proves arithmetic. It cannot catch a consistent relabeling -- an
    # invented field with the others slid down to keep the bit partition
    # complete satisfies all four constraints, and did so three times in
    # the DPI sweep. Name corroboration is the orthogonal check.
    from silicontruth.ingest.pdf_render import extract_spans
    from silicontruth.verify.text_corroboration import Corroboration, corroborate

    spans_by_page = {p: extract_spans(args.pdf, p) for p in args.pages}
    names = corroborate(ir, spans_by_page)
    print(f"  names   {names.summary()}")
    for v in names.violations:
        print(f"         {RED}{v}{RESET}")
    if names.status is Corroboration.UNAVAILABLE:
        print(f"         {YELLOW}this page has no text layer, so the check could "
              f"not run{RESET}")

    # Third gate: the printed grid's own coordinates. Name corroboration
    # catches an invented field; it cannot catch two real names swapped
    # between two columns, because both are printed. The column can.
    from silicontruth.verify.grid_corroboration import GridStatus, corroborate_grid

    grid_violations = []
    grid_unavailable: list[str] = []
    for reg in ir.registers:
        g = corroborate_grid(reg, spans_by_page.get(reg.provenance.page, []))
        if g.status is GridStatus.UNAVAILABLE:
            grid_unavailable.append(f"{reg.name}: {g.reason}")
        grid_violations.extend(g.violations)
    if grid_violations:
        print(f"  grid    FAIL: {len(grid_violations)} bit(s) disagree with the "
              f"printed grid")
        for v in grid_violations[:5]:
            print(f"         {RED}{v}{RESET}")
    elif grid_unavailable:
        # Not a pass. But also not a failure: a partial reconstruction that
        # reported disagreements would block correct reads, which is worse.
        print(f"  grid    {DIM}UNAVAILABLE: {grid_unavailable[0]}{RESET}")
    else:
        print("  grid    PASS: every field sits under the column the page prints")

    # A register is verified only if EVERY gate passes. UNAVAILABLE does not
    # count as a pass: a check that could not run has not been satisfied.
    # The grid check is the exception -- it is advisory, because its
    # reconstruction depends on a layout no vendor guarantees. It can fail a
    # read, but its absence does not block one.
    passed = result.passed and names.passed and not grid_violations
    reasons = (
        [str(v) for v in result.violations]
        + [str(v) for v in names.violations]
        + [str(v) for v in grid_violations]
    )
    if names.status is Corroboration.UNAVAILABLE:
        reasons.append(f"name corroboration unavailable: {names.reason}")
    for reg in ir.registers:
        reg.verified = passed
        if not passed:
            reg.unverified_reason = "; ".join(reasons)[:300]

    if args.errata:
        try:
            link = extract_errata(provider, ir, args.errata, args.errata_page,
                                  dpi=args.dpi)
        except ProviderError as e:
            print(f"  errata  {RED}{e}{RESET}")
            return 3
        apply_to_ir(ir, link)
        print(f"  errata  {len(link.rules)} applied, {len(link.rejected)} rejected")
        for r in link.rules:
            print(f"         {GREEN}+{RESET} [{r.errata_id}] {r.constraint.value} "
                  f"on {r.affected_register} {dict(r.params)}")
        for r in link.rejected:
            print(f"         {DIM}-{RESET} {r}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(ir.model_dump_json(indent=2), encoding="utf-8")
    print(f"  ir      -> {args.out}")
    if not passed:
        print(f"  {YELLOW}every register is marked UNVERIFIED; `build` will "
              f"refuse to emit from this IR{RESET}")
    return 0 if passed else 1


def cmd_build(args: argparse.Namespace) -> int:
    ir = _load(args.ir)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    with Recorder(args.fixtures, chip=args.chip or ir.chip.lower(),
                  peripheral=ir.peripheral, enabled=not args.no_record) as rec:
        result = audit(ir)
        rec.record(
            EventKind.Z3_AUDIT,
            passed=result.passed,
            elapsed_ms=result.elapsed_ms,
            registers=result.registers_checked,
            violations=[str(v) for v in result.violations],
        )
        print(f"{ir.chip} / {ir.peripheral}")
        print(f"  z3      {result.summary()}")

        if not ir.verified_registers:
            print(f"  {RED}nothing verified; refusing to emit{RESET}")
            return 1
        if result.violations:
            print(f"  {YELLOW}{len(ir.unverified_registers)} register(s) excluded "
                  f"from codegen{RESET}")

        svd = emit_svd(ir, vendor=args.vendor)
        v = validate_svd(svd)
        (out / "chip.svd").write_text(svd, encoding="utf-8")
        rec.write_artifact("chip.svd", svd)
        print(f"  svd     {'valid' if v.ok else 'INVALID: ' + '; '.join(v.errors[:3])}"
              f"  -> {out / 'chip.svd'}")
        if not v.ok:
            return 1

        hal = emit_hal(ir)
        name = ir.peripheral.lower()
        (out / f"{name}_hal.h").write_text(hal.header, encoding="utf-8")
        (out / f"{name}_hal.c").write_text(hal.source, encoding="utf-8")
        rec.write_artifact(f"{name}_hal.h", hal.header)
        rec.write_artifact(f"{name}_hal.c", hal.source)
        rec.record(EventKind.HAL_EMITTED, errata=hal.errata_applied)
        print(f"  hal     {hal.errata_count} errata workaround(s) injected"
              f"  -> {out / (name + '_hal.c')}")

        periph = emit_peripheral(ir)
        (out / "peripheral_mock.py").write_text(periph, encoding="utf-8")
        (out / "platform.repl").write_text(emit_repl(ir), encoding="utf-8")
        (out / "run_test.resc").write_text(emit_resc(ir), encoding="utf-8")
        rec.write_artifact("peripheral_mock.py", periph)
        print(f"  renode  model + platform + script  -> {out}")

        if not shutil.which("renode"):
            print(f"  {DIM}renode not on PATH; run the oracle in the Modal container{RESET}")

    if not args.no_record:
        write_index(args.fixtures)
        print(f"  replay  recorded -> {args.fixtures}")
    return 0


def cmd_oracle(args: argparse.Namespace) -> int:
    text = args.trace.read_text(encoding="utf-8") if args.trace.exists() else sys.stdin.read()
    verdict = evaluate(text, base_address=args.base, require_transactions=not args.allow_silent)
    print(render_bus_trace(verdict, args.base))
    print()
    colour = GREEN if verdict.passed else RED
    print(f"{colour}{verdict.summary()}{RESET}")
    print(verdict.to_json())
    return verdict.exit_code


def cmd_replay(args: argparse.Namespace) -> int:
    runs = list(iter_runs(args.fixtures))
    if not runs:
        print(f"no recorded runs under {args.fixtures}")
        return 1
    for name, path in runs:
        size = path.stat().st_size
        print(f"  {name:<12} {size:>8,} bytes  {path}")
    idx = write_index(args.fixtures)
    print(f"\nindex -> {idx}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    print("SiliconTruth environment\n")

    print("  deterministic layer (no credentials needed)")
    for mod in ("z3", "pydantic", "pymupdf", "cv2"):
        try:
            __import__(mod)
            print(f"    {GREEN}OK{RESET}   {mod}")
        except ImportError:
            print(f"    {RED}MISS{RESET} {mod}")

    print("\n  native toolchain (needed for the compile and emulate gates)")
    for tool in ("arm-none-eabi-gcc", "renode", "sigrok-cli", "cargo", "svd2rust"):
        path = shutil.which(tool)
        print(f"    {GREEN}OK{RESET}   {tool}" if path else
              f"    {YELLOW}MISS{RESET} {tool}  {DIM}(provided by the Modal container){RESET}")

    print("\n  inference providers")
    try:
        from silicontruth.models.provider import available_backends, load_env

        env = load_env()
        found = available_backends(env)
        if not found:
            print(f"    {YELLOW}none configured{RESET}  set a key in .env")
        for b in found:
            print(f"    {GREEN}key{RESET}  {b}")
        if "meta" in found:
            print(f"    {DIM}note: a key alone is not access; run scripts/smoke_api.py{RESET}")
    except Exception as e:
        print(f"    {RED}error{RESET} {e}")

    print("\n  what this means")
    print("    The Z3 gate, SVD/HAL/Renode generation and the MMIO oracle run now.")
    print("    PDF -> IR needs a working inference provider.")
    print("    The compile and emulate gates need the Modal container.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="silicontruth", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("verify", help="run the Z3 gate")
    p.add_argument("ir", type=Path)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("extract", help="PDF -> IR (needs an inference provider)")
    p.add_argument("pdf", type=Path)
    p.add_argument("--pages", type=int, nargs="+", required=True,
                   help="1-indexed PDF pages holding register descriptions")
    p.add_argument("--chip", required=True)
    p.add_argument("--peripheral", required=True)
    p.add_argument("--base", type=lambda x: int(x, 0), required=True,
                   help="peripheral base address; never asked of the model")
    p.add_argument("--errata", type=Path, default=None,
                   help="errata PDF to cross-reference")
    p.add_argument("--errata-page", type=int, default=1)
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--max-tokens", type=int, default=8192,
                   help="completion budget. Spark is a reasoning model and "
                        "spends most of this before emitting anything, so a "
                        "value that is too low looks like a dead endpoint")
    p.add_argument("--provider", default=None)
    p.add_argument("--segment", action="store_true",
                   help="use SAM 3.1 to locate tables and read them one at a "
                        "time. Worth it on dense multi-register pages; the "
                        "whole-page path works without it")
    p.add_argument("-o", "--out", type=Path, default=Path("out/ir.json"))
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("build", help="full deterministic pipeline")
    p.add_argument("ir", type=Path)
    p.add_argument("-o", "--out", type=Path, default=Path("out"))
    p.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    p.add_argument("--chip", default=None)
    p.add_argument("--vendor", default="")
    p.add_argument("--no-record", action="store_true")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("oracle", help="judge a Renode trace")
    p.add_argument("trace", type=Path)
    p.add_argument("--base", type=lambda s: int(s, 0), default=0)
    p.add_argument("--allow-silent", action="store_true")
    p.set_defaults(fn=cmd_oracle)

    p = sub.add_parser("replay", help="list recorded runs")
    p.add_argument("fixtures", type=Path, nargs="?", default=Path("fixtures"))
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("doctor", help="what is installed, what is blocked")
    p.set_defaults(fn=cmd_doctor)

    return ap


def app(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(app())
