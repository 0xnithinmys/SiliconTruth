"""T-095 — the /goal acceptance script.

Muse Code's `update_goal` cannot clear until this exits 0. That is the thing
that stops an agent generating plausible-looking C, declaring the task done,
and moving on.

Runs the full chain and reports WHICH stage failed, because "it didn't work"
sends an agent in circles:

    1. Z3 register audit            (invariant #1)
    2. CMSIS-SVD structural validate
    3. svd2rust + cargo build       (skipped if the toolchain is absent)
    4. arm-none-eabi-gcc -Werror    (skipped if the toolchain is absent)
    5. Renode MMIO oracle           (invariant #2; skipped if Renode is absent)

Stages that need a toolchain SKIP locally and RUN in the Modal container. A skip
is reported distinctly from a pass -- a green run that silently skipped the
emulator is exactly the false confidence this script exists to prevent.

Usage:
    python .muse/goals/verify_all_hardware_checks.py <ir.json> [--strict]

    --strict  treat SKIP as failure (use this in the Modal container and in CI)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from silicontruth.ir.schema import PeripheralIR  # noqa: E402
from silicontruth.oracle.renode_oracle import evaluate  # noqa: E402
from silicontruth.synth.hal_c_emitter import emit_hal  # noqa: E402
from silicontruth.synth.renode_peripheral import (  # noqa: E402
    emit_peripheral,
    emit_repl,
    emit_resc,
)
from silicontruth.synth.svd_emitter import emit_svd, validate_svd  # noqa: E402
from silicontruth.verify.z3_register_audit import audit  # noqa: E402


class Outcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class StageResult:
    name: str
    outcome: Outcome
    detail: str = ""


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, (p.stdout + p.stderr)[-4000:]
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]}: timed out after {timeout}s"


def stage_z3(ir: PeripheralIR) -> StageResult:
    result = audit(ir)
    if not result.passed:
        return StageResult(
            "z3_register_audit",
            Outcome.FAIL,
            f"{len(result.violations)} violation(s): "
            + "; ".join(str(v) for v in result.violations[:5]),
        )
    if not ir.verified_registers:
        return StageResult("z3_register_audit", Outcome.FAIL, "no verified registers")
    return StageResult(
        "z3_register_audit",
        Outcome.PASS,
        f"{len(ir.verified_registers)} registers proved in {result.elapsed_ms:.1f}ms",
    )


def stage_svd(ir: PeripheralIR, workdir: Path) -> StageResult:
    try:
        xml_text = emit_svd(ir)
    except Exception as e:
        return StageResult("svd_emit", Outcome.FAIL, f"{type(e).__name__}: {e}")
    (workdir / "chip.svd").write_text(xml_text, encoding="utf-8")
    v = validate_svd(xml_text)
    if not v.ok:
        return StageResult("svd_validate", Outcome.FAIL, "; ".join(v.errors[:5]))
    return StageResult("svd_validate", Outcome.PASS, f"{len(xml_text)} bytes, schema-clean")


def stage_svd2rust(workdir: Path) -> StageResult:
    if not shutil.which("svd2rust"):
        return StageResult("svd2rust", Outcome.SKIP, "svd2rust not on PATH")
    code, out = _run(["svd2rust", "-i", "chip.svd"], cwd=workdir)
    if code != 0:
        return StageResult("svd2rust", Outcome.FAIL, out[-1500:])
    if not shutil.which("cargo"):
        return StageResult("cargo_build", Outcome.SKIP, "cargo not on PATH")
    code, out = _run(["cargo", "build"], cwd=workdir)
    return (
        StageResult("cargo_build", Outcome.PASS, "PAC builds")
        if code == 0
        else StageResult("cargo_build", Outcome.FAIL, out[-1500:])
    )


def stage_c_compile(ir: PeripheralIR, workdir: Path) -> StageResult:
    try:
        hal = emit_hal(ir)
    except Exception as e:
        return StageResult("hal_emit", Outcome.FAIL, f"{type(e).__name__}: {e}")

    name = ir.peripheral.lower()
    (workdir / f"{name}_hal.h").write_text(hal.header, encoding="utf-8")
    (workdir / f"{name}_hal.c").write_text(hal.source, encoding="utf-8")

    gcc = shutil.which("arm-none-eabi-gcc")
    if not gcc:
        return StageResult(
            "arm_gcc_werror",
            Outcome.SKIP,
            f"arm-none-eabi-gcc not on PATH (emitted {hal.errata_count} errata workaround(s))",
        )
    code, out = _run(
        [
            gcc, "-mcpu=cortex-m4", "-mthumb", "-nostdlib",
            "-Wall", "-Werror", "-c", f"{name}_hal.c", "-o", f"{name}_hal.o",
        ],
        cwd=workdir,
    )
    return (
        StageResult("arm_gcc_werror", Outcome.PASS, "compiles clean")
        if code == 0
        else StageResult("arm_gcc_werror", Outcome.FAIL, out[-1500:])
    )


def stage_renode(ir: PeripheralIR, workdir: Path) -> StageResult:
    try:
        (workdir / "peripheral_mock.py").write_text(emit_peripheral(ir), encoding="utf-8")
        (workdir / "platform.repl").write_text(emit_repl(ir), encoding="utf-8")
        (workdir / "run_test.resc").write_text(emit_resc(ir), encoding="utf-8")
    except Exception as e:
        return StageResult("renode_emit", Outcome.FAIL, f"{type(e).__name__}: {e}")

    # The generated model runs inside Renode's interpreter; catch syntax errors
    # here rather than as a confusing failure three layers down.
    try:
        compile((workdir / "peripheral_mock.py").read_text(encoding="utf-8"),
                "peripheral_mock.py", "exec")
    except SyntaxError as e:
        return StageResult("renode_emit", Outcome.FAIL, f"generated model is invalid Python: {e}")

    if not shutil.which("renode"):
        return StageResult("renode_oracle", Outcome.SKIP, "renode not on PATH")
    if not (workdir / "test_firmware.elf").exists():
        return StageResult("renode_oracle", Outcome.SKIP, "no test_firmware.elf to boot")

    code, out = _run(
        ["renode", "--disable-xwt", "--console", "-e", "include @run_test.resc"],
        cwd=workdir,
        timeout=180,
    )
    verdict = evaluate(out, base_address=ir.base_address)
    return (
        StageResult("renode_oracle", Outcome.PASS, verdict.summary())
        if verdict.passed
        else StageResult("renode_oracle", Outcome.FAIL, verdict.to_json())
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ir", type=Path, help="PeripheralIR JSON")
    ap.add_argument("--strict", action="store_true", help="treat SKIP as failure")
    ap.add_argument("--workdir", type=Path, default=None)
    args = ap.parse_args()

    if not args.ir.exists():
        print(f"FAIL  no such IR file: {args.ir}")
        return 2

    ir = PeripheralIR.model_validate_json(args.ir.read_text(encoding="utf-8"))
    tmp = args.workdir or Path(tempfile.mkdtemp(prefix="silicontruth-goal-"))
    tmp.mkdir(parents=True, exist_ok=True)

    print(f"{ir.chip} / {ir.peripheral}   workdir: {tmp}\n")

    results: list[StageResult] = [stage_z3(ir)]
    if results[0].outcome is Outcome.PASS:
        results.append(stage_svd(ir, tmp))
        if results[-1].outcome is Outcome.PASS:
            results.append(stage_svd2rust(tmp))
        results.append(stage_c_compile(ir, tmp))
        results.append(stage_renode(ir, tmp))

    width = max(len(r.name) for r in results)
    for r in results:
        print(f"  {r.outcome.value:<5} {r.name:<{width}}  {r.detail}")

    failed = [r for r in results if r.outcome is Outcome.FAIL]
    skipped = [r for r in results if r.outcome is Outcome.SKIP]

    print()
    if failed:
        print(f"GOAL BLOCKED: {len(failed)} stage(s) failed: {', '.join(r.name for r in failed)}")
        return 1
    if skipped and args.strict:
        print(
            f"GOAL BLOCKED (--strict): {len(skipped)} stage(s) skipped: "
            + ", ".join(r.name for r in skipped)
        )
        return 1
    if skipped:
        print(
            f"GOAL CLEARED with {len(skipped)} skipped stage(s): "
            + ", ".join(r.name for r in skipped)
        )
        print("  Those stages need the Modal container. Run with --strict there.")
        return 0
    print("GOAL CLEARED: every stage passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
