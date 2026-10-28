"""Generate every artifact from one verified IR, with per-artifact status.

WHY THIS IS NOT A WORKTREE FAN-OUT
==================================
The plan called for generating the four artifacts across four isolated
Muse Code worktrees in parallel. That is the right shape for *agentic*
code generation, where four agents write four files and must not tread on
each other.

It is the wrong shape here, and saying so is more useful than
implementing it anyway. These generators are deterministic pure functions
over the IR -- no model call, no network, no shared state. All four
finish in single-digit milliseconds, so there is nothing to parallelise
and nothing to isolate; worktrees would add process spawning and
reconciliation to hide latency that does not exist. More to the point,
using an agent to write the code would put a model back on the path
between the verified IR and the emitted driver, which is exactly the thing
the two invariants exist to prevent.

So this is the sequential path the plan listed as the fallback (T-100),
and it is the better design for this job rather than a concession.

WHAT IT ADDS over calling the emitters directly: one gate check for all of
them, per-artifact success/failure instead of an exception that kills the
whole run, and a single place that knows the file names. A failure in the
Rust emitter should not cost you the SVD that generated fine.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path

from silicontruth.ir.schema import PeripheralIR
from silicontruth.synth.hal_c_emitter import emit_hal
from silicontruth.synth.hal_rust_emitter import emit_rust
from silicontruth.synth.renode_peripheral import emit_peripheral, emit_repl, emit_resc
from silicontruth.synth.svd_emitter import emit_svd, validate_svd


class NothingVerified(RuntimeError):
    """The IR has no verified register, so nothing may be emitted.

    Not a warning. An IR that failed its gates must produce no artifacts at
    all -- an empty-but-valid SVD looks like a successful run.
    """


@dataclass
class Artifact:
    name: str
    ok: bool
    detail: str = ""
    content: str | None = None


@dataclass
class GenerationResult:
    artifacts: list[Artifact] = dc_field(default_factory=list)
    errata_applied: list[str] = dc_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.artifacts) and all(a.ok for a in self.artifacts)

    @property
    def failed(self) -> list[Artifact]:
        return [a for a in self.artifacts if not a.ok]

    def summary(self) -> str:
        good = sum(1 for a in self.artifacts if a.ok)
        return f"{good}/{len(self.artifacts)} artifact(s) generated"


def generate(ir: PeripheralIR, *, vendor: str = "") -> GenerationResult:
    """Emit every artifact. Never raises for one generator's failure.

    The caller is a CLI and a web UI; "the Rust emitter failed, here is why"
    is a result to display beside the three artifacts that succeeded, not an
    exception that discards them.
    """
    if not ir.verified_registers:
        raise NothingVerified(
            f"{ir.chip}/{ir.peripheral}: no verified registers; refusing to emit"
        )

    result = GenerationResult()
    name = ir.peripheral.lower()

    def attempt(filename: str, fn) -> None:
        try:
            result.artifacts.append(
                Artifact(name=filename, ok=True, content=fn())
            )
        except Exception as e:  # one generator's failure is not the run's
            result.artifacts.append(
                Artifact(name=filename, ok=False,
                         detail=f"{type(e).__name__}: {e}")
            )

    # --- CMSIS-SVD, validated structurally -------------------------------
    def svd() -> str:
        xml = emit_svd(ir, vendor=vendor)
        v = validate_svd(xml)
        if not v.ok:
            raise ValueError("; ".join(v.errors[:3]))
        return xml

    attempt("chip.svd", svd)

    # --- C HAL ------------------------------------------------------------
    try:
        hal = emit_hal(ir)
        result.artifacts.append(
            Artifact(name=f"{name}_hal.h", ok=True, content=hal.header)
        )
        result.artifacts.append(
            Artifact(name=f"{name}_hal.c", ok=True, content=hal.source)
        )
        result.errata_applied = list(hal.errata_applied)
    except Exception as e:
        result.artifacts.append(
            Artifact(name=f"{name}_hal.c", ok=False,
                     detail=f"{type(e).__name__}: {e}")
        )

    # --- Rust HAL ----------------------------------------------------------
    attempt(f"{name}_hal.rs", lambda: emit_rust(ir).source)

    # --- Renode model, platform and script ---------------------------------
    attempt("peripheral_mock.py", lambda: emit_peripheral(ir))
    attempt("platform.repl", lambda: emit_repl(ir))
    attempt("run_test.resc", lambda: emit_resc(ir))

    return result


def write(result: GenerationResult, out_dir: Path) -> list[Path]:
    """Write the artifacts that generated successfully.

    A failed artifact writes NOTHING rather than a truncated file: a partial
    driver on disk is indistinguishable from a complete one at a glance,
    which is how a half-generated HAL gets compiled and flashed.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for a in result.artifacts:
        if not a.ok or a.content is None:
            continue
        path = out_dir / a.name
        path.write_text(a.content, encoding="utf-8")
        written.append(path)
    return written
