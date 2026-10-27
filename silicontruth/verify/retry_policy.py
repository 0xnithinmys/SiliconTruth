"""T-071/T-072/T-073 — turn a Z3 unsat core into a targeted re-extraction.

THE LOOP
--------
    Z3 fails
      -> the violation names a register and a specific bit
      -> that maps to the field's Provenance bbox
      -> re-render that page region at 600 DPI
      -> re-crop just that row with a SAM box prompt
      -> re-ask the model for that ONE register
      -> re-audit
    ...at most MAX_RETRIES times, then mark UNVERIFIED and exclude from codegen.

WHY THIS WORKS AT ALL
---------------------
Because the failure is specific. "The IR is wrong somewhere" is unactionable;
"CR1 bit 31 is unaccounted for, and it came from page 2054 bbox (120,816,2280,842)"
tells you exactly which 26 pixels to look at again. That specificity is what the
unsat core buys, and it is why the gate tracks named assertions.

WHY WE STOP AT THREE
--------------------
If three re-reads at double resolution still disagree, the page is the problem,
not the sampling. Retrying further burns tokens to produce the same answer.
Marking it UNVERIFIED and showing that in the UI is the honest outcome: a visible
gap beats a silent wrong offset, especially for a tool whose wrong answer can
destroy hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from silicontruth.ir.schema import PeripheralIR, Provenance, Register
from silicontruth.verify.z3_register_audit import AuditResult, Violation, audit

MAX_RETRIES = 3
RETRY_DPI = 600

# How much to widen the failing field's bbox when re-cropping. A bitfield row is
# usually tight against its neighbours; a little context helps the model see the
# column headers it needs to read the row correctly.
BBOX_PAD_X = 40.0
BBOX_PAD_Y = 14.0

BBox = tuple[float, float, float, float]


class ReExtractor(Protocol):
    """Re-read one register from a higher-resolution crop.

    Injected rather than imported so the loop is testable without a model, and
    so the provider can be swapped (Meta, OpenRouter, ...) without touching this.
    """

    def __call__(
        self, register: Register, *, page: int, bbox: BBox, dpi: int
    ) -> Register | None: ...


@dataclass
class RetryAttempt:
    register: str
    attempt: int
    page: int
    bbox: BBox
    dpi: int
    violations_before: tuple[str, ...]
    repaired: bool


@dataclass
class RetryReport:
    attempts: list[RetryAttempt] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)
    abandoned: list[str] = field(default_factory=list)
    first_pass_rate: float = 0.0
    final_pass_rate: float = 0.0

    def summary(self) -> str:
        return (
            f"Z3 first pass {self.first_pass_rate:.0%} -> after retry "
            f"{self.final_pass_rate:.0%} "
            f"({len(self.repaired)} repaired, {len(self.abandoned)} abandoned, "
            f"{len(self.attempts)} re-extractions)"
        )


def locate_failure(reg: Register, violation: Violation) -> tuple[int, BBox]:
    """Map a violation to the page and bbox worth re-reading.

    Prefers the specific field the unsat core named; falls back to the register's
    own provenance when the violation is register-level (alignment, duplicate
    offset) rather than bit-level.
    """
    target: Provenance = reg.provenance

    if violation.fields:
        named = [f for f in reg.fields if f.name in violation.fields]
        if named:
            target = named[0].provenance
    elif violation.bit is not None:
        covering = [f for f in reg.fields if f.lsb <= violation.bit <= f.msb]
        if covering:
            target = covering[0].provenance
        else:
            # The bit is unaccounted for precisely because no field claims it.
            # Re-read the neighbours that bracket the hole.
            below = [f for f in reg.fields if f.msb < violation.bit]
            above = [f for f in reg.fields if f.lsb > violation.bit]
            neighbours = ([max(below, key=lambda f: f.msb)] if below else []) + (
                [min(above, key=lambda f: f.lsb)] if above else []
            )
            if neighbours:
                return _merge_bboxes([n.provenance for n in neighbours])

    return target.page, _pad(target.bbox)


def _pad(bbox: BBox) -> BBox:
    x0, y0, x1, y1 = bbox
    return (max(0.0, x0 - BBOX_PAD_X), max(0.0, y0 - BBOX_PAD_Y), x1 + BBOX_PAD_X, y1 + BBOX_PAD_Y)


def _merge_bboxes(provs: list[Provenance]) -> tuple[int, BBox]:
    page = provs[0].page
    xs0 = [p.bbox[0] for p in provs]
    ys0 = [p.bbox[1] for p in provs]
    xs1 = [p.bbox[2] for p in provs]
    ys1 = [p.bbox[3] for p in provs]
    return page, _pad((min(xs0), min(ys0), max(xs1), max(ys1)))


def scale_bbox(bbox: BBox, *, from_dpi: int, to_dpi: int) -> BBox:
    """Move a bbox between render resolutions. The retry re-renders at 600 DPI,
    so a 300 DPI bbox must be doubled or the crop lands in the wrong place."""
    k = to_dpi / from_dpi
    return (bbox[0] * k, bbox[1] * k, bbox[2] * k, bbox[3] * k)


def run_retry_loop(
    ir: PeripheralIR,
    re_extract: ReExtractor,
    *,
    max_retries: int = MAX_RETRIES,
    retry_dpi: int = RETRY_DPI,
    base_dpi: int = 300,
    on_event: Callable[[RetryAttempt], None] | None = None,
) -> tuple[AuditResult, RetryReport]:
    """Audit, repair what can be repaired, abandon the rest honestly."""
    first = audit(ir)
    total = max(len(ir.registers), 1)
    report = RetryReport(
        first_pass_rate=sum(1 for r in ir.registers if r.verified) / total
    )

    for reg in ir.registers:
        if reg.verified:
            continue

        for attempt in range(1, max_retries + 1):
            violations = [v for v in first.violations if v.register == reg.name]
            if not violations:
                violations = (
                    [
                        Violation(
                            register=reg.name,
                            constraint="unknown",
                            detail=reg.unverified_reason or "unverified",
                        )
                    ]
                )

            page, bbox = locate_failure(reg, violations[0])
            hi_bbox = scale_bbox(bbox, from_dpi=base_dpi, to_dpi=retry_dpi)

            replacement = re_extract(reg, page=page, bbox=hi_bbox, dpi=retry_dpi)

            repaired = False
            if replacement is not None:
                idx = ir.registers.index(reg)
                previous = ir.registers[idx]
                ir.registers[idx] = replacement
                check = audit(ir)
                if replacement.verified:
                    repaired = True
                    reg = replacement
                else:
                    # Keep the better of the two rather than drifting further.
                    ir.registers[idx] = previous
                first = check

            record = RetryAttempt(
                register=reg.name,
                attempt=attempt,
                page=page,
                bbox=hi_bbox,
                dpi=retry_dpi,
                violations_before=tuple(str(v) for v in violations),
                repaired=repaired,
            )
            report.attempts.append(record)
            if on_event:
                on_event(record)

            if repaired:
                report.repaired.append(reg.name)
                break
        else:
            target = ir.register_by_name(reg.name)
            if target is not None:
                target.verified = False
                target.unverified_reason = (
                    f"{target.unverified_reason or 'unverified'} "
                    f"(abandoned after {max_retries} re-extractions at {retry_dpi} DPI)"
                )
            report.abandoned.append(reg.name)

    final = audit(ir, mark=False)
    # Re-mark without clobbering the abandonment reasons we just wrote.
    for r in ir.registers:
        if r.name in report.abandoned:
            r.verified = False
    report.final_pass_rate = sum(1 for r in ir.registers if r.verified) / total
    return final, report
