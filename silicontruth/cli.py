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
