"""Compile and emulate locally, in Docker, with no account anywhere.

modal_app.py is the hosted path and needs a Modal token. This is the same two
stages against the same pinned image recipe, on a machine that has Docker and
nothing else. Both end at renode_oracle.evaluate, so a verdict from here and a
verdict from Modal mean exactly the same thing.

The command construction is kept pure and separate from the subprocess calls,
so the interesting part is unit-testable on a machine with no Docker at all,
which is the normal case for this repo's test suite.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from silicontruth.ir.schema import PeripheralIR
from silicontruth.oracle.renode_oracle import OracleVerdict, evaluate
from silicontruth.synth.renode_peripheral import emit_peripheral, emit_repl, emit_resc
from silicontruth.synth.test_firmware import emit_firmware, emit_linker_script

IMAGE = "silicontruth-oracle:1.15.3"
RENODE = "/opt/renode/renode"
# Where workdir is mounted inside the container. Referenced by the generated
# platform.repl, so it is a name rather than three string literals.
MOUNT = "/work"

# -Werror for the same reason modal_app gives: implicit declaration, integer
# truncation and discarded volatile are exactly how a wrong register access
# gets past review, so a warning has to be a failure or the gate is decorative.
#
# -nostartfiles because the firmware brings its own vector table and reset
# handler; newlib's crt0 would expect a runtime this platform does not have.
CFLAGS = [
    "-mcpu=cortex-m4",
    "-mthumb",
    "-Os",
    "-std=c11",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-Wconversion",
    "-ffreestanding",
    "-nostartfiles",
]


@dataclass(frozen=True)
class Stage:
    """One stage's outcome. A failure is a result to display, never an
    exception to swallow somewhere up the stack."""

    name: str
    ok: bool
    rc: int
    stdout: str
    stderr: str
    cmd: str


@dataclass(frozen=True)
class EmulationResult:
    compiled: Stage
    emulated: Stage | None
    verdict: OracleVerdict | None

    @property
    def passed(self) -> bool:
        return bool(self.compiled.ok and self.verdict is not None and self.verdict.passed)


def write_inputs(ir: PeripheralIR, hal_c: str, hal_h: str, workdir: Path) -> list[str]:
    """Lay out everything the container needs. Returns the file names written."""
    p = ir.peripheral.lower()
    files = {
        f"{p}_hal.h": hal_h,
        f"{p}_hal.c": hal_c,
        "main.c": emit_firmware(ir),
        "link.ld": emit_linker_script(),
        "peripheral_mock.py": emit_peripheral(ir),
        # An ABSOLUTE path for the Python peripheral, and the mount point is
        # why this is the caller's business rather than the emitter's.
        # Renode resolves a .resc's @paths relative to the script, but a
        # .repl's `filename:` relative to its own working directory, so the
        # bare name resolved for one and not the other -- "Could not find
        # source file for the script: peripheral_mock.py", with the platform
        # half-built and no MMIO at all. Modal mounts /tmp/renode and this
        # mounts /work, so neither can be the emitter's default.
        "platform.repl": emit_repl(ir, peripheral_file=f"{MOUNT}/peripheral_mock.py"),
        "run_test.resc": emit_resc(ir),
    }
    workdir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (workdir / name).write_text(text, encoding="utf-8")
    return sorted(files)


def compile_cmd(peripheral: str) -> list[str]:
    """Link a real ELF, not a pile of .o files.

    The previous container only ever passed -c, so `sysbus LoadELF
    @test_firmware.elf` in the generated .resc had nothing to load. That is
    the gap this module exists to close."""
    p = peripheral.lower()
    return [
        "arm-none-eabi-gcc",
        *CFLAGS,
        "-T",
        "link.ld",
        "-o",
        "test_firmware.elf",
        "main.c",
        f"{p}_hal.c",
    ]


def renode_cmd(script: str = "run_test.resc") -> list[str]:
    """--disable-xwt is mandatory. Without it Renode looks for a display, does
    not find one, and hangs instead of failing, which is indistinguishable from
    a slow run until the timeout fires."""
    return [RENODE, "--disable-xwt", "--console", "-e", f"include @{MOUNT}/{script}"]


def docker_cmd(workdir: Path, inner: list[str], image: str = IMAGE) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{workdir.resolve().as_posix()}:{MOUNT}",
        "-w",
        MOUNT,
        image,
        *inner,
    ]


def _run(cmd: list[str], name: str, timeout: int) -> Stage:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return Stage(name, False, 127, "", "docker not found on PATH", shlex.join(cmd))
    except subprocess.TimeoutExpired:
        return Stage(name, False, -1, "", f"timed out after {timeout}s", shlex.join(cmd))
    return Stage(
        name,
        p.returncode == 0,
        p.returncode,
        p.stdout[-20000:],
        p.stderr[-20000:],
        shlex.join(cmd),
    )


def run(
    ir: PeripheralIR,
    hal_c: str,
    hal_h: str,
    workdir: Path,
    *,
    image: str = IMAGE,
    timeout: int = 300,
) -> EmulationResult:
    """Compile, then emulate. A failed compile stops here: emulating an ELF
    that was never produced would report a missing trace as a driver fault."""
    write_inputs(ir, hal_c, hal_h, workdir)

    compiled = _run(
        docker_cmd(workdir, compile_cmd(ir.peripheral), image), "compile", timeout
    )
    if not compiled.ok:
        return EmulationResult(compiled, None, None)

    emulated = _run(docker_cmd(workdir, renode_cmd(), image), "emulate", timeout)
    log = emulated.stdout + "\n" + emulated.stderr
    (workdir / "renode.log").write_text(log, encoding="utf-8")
    verdict = evaluate(log, base_address=ir.base_address)
    return EmulationResult(compiled, emulated, verdict)


def to_payload(result: EmulationResult) -> dict[str, Any]:
    """The shape the recorder stores and the UI reads."""
    return {
        "compiled": result.compiled.ok,
        "passed": result.passed,
        "status": result.verdict.status.value if result.verdict else "NO_TRACE",
        "reason": result.verdict.summary() if result.verdict else result.compiled.stderr[-400:],
        "transactions": len(result.verdict.transactions) if result.verdict else 0,
    }
