"""SiliconTruth command line.

    silicontruth pipeline <manual.pdf>           PDF -> driver -> emulated, one run
    silicontruth verify   <ir.json>              Z3 gate only
    silicontruth build    <ir.json> -o <dir>     full deterministic pipeline
    silicontruth emulate  <ir.json>              compile + run it in Docker
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
import subprocess
import sys
from pathlib import Path

from silicontruth.errors import UserError
from silicontruth.ir.schema import PeripheralIR
# One name for the container tag, so `emulate --image`, `pipeline --image` and
# `doctor` cannot drift apart and report three different images.
from silicontruth.oracle.docker_oracle import IMAGE as DOCKER_IMAGE
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

    errata_rejected: list = []
    if args.errata:
        try:
            link = extract_errata(provider, ir, args.errata, args.errata_page,
                                  dpi=args.dpi)
        except ProviderError as e:
            print(f"  errata  {RED}{e}{RESET}")
            return 3
        apply_to_ir(ir, link)
        errata_rejected = list(link.rejected)
        print(f"  errata  {len(link.rules)} applied, {len(link.rejected)} rejected")
        for r in link.rules:
            print(f"         {GREEN}+{RESET} [{r.errata_id}] {r.constraint.value} "
                  f"on {r.affected_register} {dict(r.params)}")
        for r in link.rejected:
            print(f"         {DIM}-{RESET} {r}")

    # Record the perception half. Without this the replay UI can only ever
    # show codegen, which is the half that was never in question.
    if not args.no_record:
        from silicontruth.replay.recorder import EventKind, Recorder, write_index

        with Recorder(args.fixtures, chip=args.chip, peripheral=args.peripheral,
                      base_address=args.base) as rec:
            for page in args.pages:
                rec.record(EventKind.PAGE_RENDER, page=page, dpi=args.dpi)
            for reg in ir.registers:
                pv = reg.provenance
                rec.record(
                    EventKind.IR_EXTRACTED,
                    register=reg.name,
                    offset=reg.offset,
                    width=reg.width,
                    reset_value=reg.reset_value,
                    fields=len(reg.fields),
                    page=pv.page,
                    bbox=list(pv.bbox),
                    mask_id=pv.mask_id,
                    verified=reg.verified,
                )
            rec.record(
                EventKind.Z3_AUDIT,
                passed=result.passed,
                elapsed_ms=result.elapsed_ms,
                registers=result.registers_checked,
                violations=[str(v) for v in result.violations],
            )
            rec.record(
                EventKind.NAME_AUDIT,
                status=names.status.value,
                passed=names.passed,
                checked=names.checked,
                reason=names.reason,
                violations=[str(v) for v in names.violations],
            )
            rec.record(
                EventKind.GRID_AUDIT,
                passed=not grid_violations and not grid_unavailable,
                status=("unavailable" if grid_unavailable
                        else "violations" if grid_violations
                        else "corroborated"),
                reason="; ".join(grid_unavailable[:1]),
                violations=[str(v) for v in grid_violations],
            )
            if args.errata:
                rec.record(
                    EventKind.ERRATA_LINKED,
                    applied=[
                        {
                            "errata_id": r.errata_id,
                            "title": r.title,
                            "register": r.affected_register,
                            "constraint": r.constraint.value,
                            "params": dict(r.params),
                            "page": r.provenance.page,
                        }
                        for r in ir.errata
                    ],
                    rejected=[str(r) for r in errata_rejected],
                )
        write_index(args.fixtures)

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
                  peripheral=ir.peripheral, base_address=ir.base_address,
                  enabled=not args.no_record, append=True) as rec:
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

        # One orchestrator emits every artifact, so a failure in one
        # generator costs only that artifact rather than the whole run --
        # and so the Rust HAL is actually included, which it was not when
        # each emitter was called by hand here.
        from silicontruth.orchestrate.generate import NothingVerified, generate, write

        try:
            gen = generate(ir, vendor=args.vendor)
        except NothingVerified as e:
            print(f"  {RED}{e}{RESET}")
            return 1

        written = write(gen, out)
        for a in gen.artifacts:
            if a.ok:
                rec.write_artifact(a.name, a.content or "")
        rec.record(EventKind.HAL_EMITTED, errata=gen.errata_applied)

        for a in gen.artifacts:
            mark = f"{GREEN}ok{RESET}" if a.ok else f"{RED}FAIL{RESET}"
            size = f"{len(a.content or '')} B" if a.ok else a.detail
            print(f"  {mark:<14} {a.name:<20} {size}")

        print(f"  {len(written)} file(s) -> {out}")
        if gen.errata_applied:
            print(f"  errata  {len(gen.errata_applied)} workaround(s) injected: "
                  f"{', '.join(gen.errata_applied)}")
        if gen.failed:
            print(f"  {RED}{len(gen.failed)} artifact(s) failed; "
                  f"nothing was written for them{RESET}")

        if not shutil.which("renode"):
            print(f"  {DIM}renode not on PATH; run the execution gate with "
                  f"`silicontruth emulate` (Docker){RESET}")

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


def cmd_emulate(args: argparse.Namespace) -> int:
    """The keystone gate, run locally in Docker.

    This is the stage that was never executed: `emit_resc` has always loaded
    test_firmware.elf and nothing produced one. Now something does, so the
    claim "executed in emulation" can be made or refused on evidence."""
    from silicontruth.oracle.docker_oracle import run as docker_run, to_payload

    ir = _load(args.ir)
    hal = emit_hal(ir)

    print(f"{ir.chip} / {ir.peripheral}")
    print(f"  {DIM}image {args.image}{RESET}")

    result = docker_run(
        ir, hal.source, hal.header, args.workdir, image=args.image,
        timeout=args.timeout,
    )

    c = result.compiled
    print(f"  compile {GREEN + 'PASS' + RESET if c.ok else RED + 'FAIL' + RESET}")
    if not c.ok:
        print((c.stderr or c.stdout).strip()[-2000:])
        return 2

    verdict = result.verdict
    assert verdict is not None  # compile passed, so emulate ran
    print(render_bus_trace(verdict, ir.base_address))
    print()
    colour = GREEN if verdict.passed else RED
    print(f"  emulate {colour}{verdict.summary()}{RESET}")
    print(f"  {DIM}log -> {args.workdir / 'renode.log'}{RESET}")

    if not args.no_record:
        with Recorder(args.fixtures, chip=args.chip or ir.chip.lower(),
                      peripheral=ir.peripheral, base_address=ir.base_address,
                      append=True) as rec:
            # The raw log, so the UI can show the bus trace it was judged on
            # rather than a summary of it.
            rec.record(
                EventKind.RENODE_TRACE,
                text=(result.emulated.stdout if result.emulated else ""),
            )
            rec.record(EventKind.VERDICT, **to_payload(result))
        write_index(args.fixtures)
        print(f"  replay  recorded -> {args.fixtures}")

    return verdict.exit_code


def cmd_pipeline(args: argparse.Namespace) -> int:
    """PDF in, emulated driver out, recorded as ONE run.

    The three stages already append to the same fixtures directory, so this is
    a composition rather than a fourth implementation of the pipeline: it
    calls the same `extract`, `build` and `emulate` the CLI exposes, and any
    fix to one of them lands here for free.

    It exists because that chain is what a user actually wants and what the
    web UI has to drive. Asking anyone to run three commands and hand-carry
    `out/ir.json` between them was the reason the product looked like three
    tools instead of one.

    Stages run in order and stop at the first failure. The run is still
    recorded up to that point: a run that died at the Z3 gate is a result,
    and throwing it away would hide exactly the thing worth seeing.
    """
    ir_path = args.out_dir / "ir.json"

    stages: list[tuple[str, argparse.Namespace]] = [
        ("extract", argparse.Namespace(
            pdf=args.pdf, pages=args.pages, chip=args.chip,
            peripheral=args.peripheral, base=args.base, errata=args.errata,
            errata_page=args.errata_page, dpi=args.dpi,
            max_tokens=args.max_tokens, provider=args.provider,
            fixtures=args.fixtures, no_record=args.no_record,
            segment=args.segment, out=ir_path,
        )),
        ("build", argparse.Namespace(
            ir=ir_path, out=args.out_dir, fixtures=args.fixtures,
            chip=args.chip, vendor=args.vendor, no_record=args.no_record,
        )),
        ("emulate", argparse.Namespace(
            ir=ir_path, workdir=args.out_dir / "emulate", image=args.image,
            timeout=args.timeout, fixtures=args.fixtures, chip=args.chip,
            no_record=args.no_record,
        )),
    ]

    fns = {"extract": cmd_extract, "build": cmd_build, "emulate": cmd_emulate}
    for name, ns in stages:
        if name == "emulate" and args.skip_emulate:
            print(f"\n{DIM}-- emulate skipped --{RESET}")
            continue
        print(f"\n{DIM}-- {name} --{RESET}")
        rc = fns[name](ns)
        if rc != 0:
            print(f"\n{RED}pipeline stopped at {name} (exit {rc}){RESET}")
            return rc

    print(f"\n{GREEN}pipeline complete{RESET}  {DIM}{args.out_dir}{RESET}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """What a PDF is, as JSON, before anyone commits to reading it.

    Exists for the web form. Asking for page 412 of a 2-page manual used to
    be discovered by starting a run, calling an inference provider and
    failing partway through; the form can now say so the moment the file is
    chosen. PyMuPDF is the authority on the page count, so the answer comes
    from the same library that will later render the page rather than from a
    second PDF parser in another language that could disagree.
    """
    import json

    from silicontruth.ingest.pdf_render import page_count

    print(json.dumps({"pages": page_count(args.pdf)}))
    return 0


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

    # Docker first, because it is now the answer to "how do I run the emulate
    # gate" on an ordinary machine. Reporting the host toolchain as MISSING
    # while a working container sat beside it sent the user off to deploy
    # Modal when they did not have to.
    print("\n  emulate gate (compile + Renode)")
    if not shutil.which("docker"):
        print(f"    {YELLOW}MISS{RESET} docker  {DIM}needed by `silicontruth emulate`{RESET}")
    else:
        from silicontruth.oracle.docker_oracle import IMAGE

        print(f"    {GREEN}OK{RESET}   docker")
        built = subprocess.run(
            ["docker", "image", "inspect", IMAGE], capture_output=True, text=True
        ).returncode == 0
        if built:
            print(f"    {GREEN}OK{RESET}   image {IMAGE}")
            print(f"    {DIM}`silicontruth emulate <ir.json>` runs the gate here, "
                  f"with no account anywhere{RESET}")
        else:
            print(f"    {YELLOW}MISS{RESET} image {IMAGE}")
            print(f"    {DIM}build it: docker build -f silicontruth/oracle/Dockerfile "
                  f"-t {IMAGE} silicontruth/oracle/{RESET}")

    print("\n  native toolchain on the host (optional; the container carries its own)")
    for tool in ("arm-none-eabi-gcc", "renode", "sigrok-cli", "cargo", "svd2rust"):
        path = shutil.which(tool)
        print(f"    {GREEN}OK{RESET}   {tool}" if path else
              f"    {DIM}--   {tool}  (in the container){RESET}")

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
    print("    The compile and emulate gates run locally in Docker via `emulate`,")
    print("    or hosted on Modal. Neither needs a toolchain on this machine.")
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
    p.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    p.add_argument("--no-record", action="store_true")
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

    p = sub.add_parser("pipeline",
                       help="PDF -> IR -> driver -> emulated, as one run")
    p.add_argument("pdf", type=Path)
    p.add_argument("--pages", type=int, nargs="+", required=True)
    p.add_argument("--chip", required=True)
    p.add_argument("--peripheral", required=True)
    p.add_argument("--base", type=lambda x: int(x, 0), required=True)
    p.add_argument("--errata", type=Path, default=None)
    p.add_argument("--errata-page", type=int, default=1)
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--provider", default=None)
    p.add_argument("--segment", action="store_true")
    p.add_argument("--vendor", default="")
    p.add_argument("--image", default=DOCKER_IMAGE)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--skip-emulate", action="store_true",
                   help="stop after codegen; for a machine with no Docker")
    p.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    p.add_argument("--no-record", action="store_true")
    p.add_argument("-o", "--out-dir", type=Path, default=Path("out/pipeline"))
    p.set_defaults(fn=cmd_pipeline)

    p = sub.add_parser("oracle", help="judge a Renode trace")
    p.add_argument("trace", type=Path)
    p.add_argument("--base", type=lambda s: int(s, 0), default=0)
    p.add_argument("--allow-silent", action="store_true")
    p.set_defaults(fn=cmd_oracle)

    p = sub.add_parser("emulate", help="compile and run the driver in Docker")
    p.add_argument("ir", type=Path)
    p.add_argument("--workdir", type=Path, default=Path("out/emulate"))
    p.add_argument("--image", default=DOCKER_IMAGE)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    p.add_argument("--chip", default=None)
    p.add_argument("--no-record", action="store_true")
    p.set_defaults(fn=cmd_emulate)

    p = sub.add_parser("probe", help="page count of a PDF, as JSON")
    p.add_argument("pdf", type=Path)
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("replay", help="list recorded runs")
    p.add_argument("fixtures", type=Path, nargs="?", default=Path("fixtures"))
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("doctor", help="what is installed, what is blocked")
    p.set_defaults(fn=cmd_doctor)

    return ap


def app(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except UserError as e:
        # One line, no stack. A UserError means the input was wrong, and a
        # traceback for that buries the only sentence worth reading -- which
        # is exactly what happened to "page 412 out of range ... (2 pages)",
        # printed in the middle of forty frames of Python internals and
        # relayed verbatim into the browser.
        #
        # Everything else keeps its traceback, because everything else is a
        # defect and the stack is the useful part.
        print(f"{RED}error{RESET} {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(app())
