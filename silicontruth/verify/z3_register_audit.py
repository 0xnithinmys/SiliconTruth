"""The Z3 verification gate.

THE TWO INVARIANTS OF THIS CODEBASE
-----------------------------------
1. No LLM output reaches code generation without passing Z3.   <-- this file
2. No generated code is claimed correct without executing in Renode.

This module is invariant #1. Nothing a model extracted becomes a register
definition, an SVD entry, or a line of C until it is proved here.

THE FOUR CONSTRAINTS
--------------------
For every register R:
  (a) abs_addr == base_address + offset, and is 4-byte aligned
  (b) forall i != j:  mask_i & mask_j == 0          (no overlapping bitfields)
  (c) sum(field widths, incl. declared reserved) == width in {8, 16, 32}
  (d) reset_value & reserved_mask == 0

WHY (c) IS THE IMPORTANT ONE
----------------------------
Width conservation turns a rounding error into a caught bug. If the model misreads
[15:8] as [14:8], bit 15 is unaccounted for -- 31 bits of a 32-bit register -- and
the solver returns unsat with a core naming that exact bit. The model is never asked
to be right; it is asked to be *checkable*.

Every assertion is tracked (assert_and_track) so the unsat core names the specific
register and bit. The retry loop is useless without that specificity: it needs a
bbox to re-crop at 600 DPI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable

import z3

from silicontruth.ir.schema import BitField, PeripheralIR, Register

# Registers must sit on a 4-byte boundary. Sub-word peripherals exist, but a
# non-aligned offset is far more often an extraction error than a real chip.
ALIGNMENT_BYTES = 4

VALID_WIDTHS = (8, 16, 32)


@dataclass(frozen=True)
class Violation:
    """One proved-false constraint, specific enough to drive a re-crop."""

    register: str
    constraint: str  # "alignment" | "overlap" | "width_conservation" | "reserved_reset"
    detail: str
    bit: int | None = None
    fields: tuple[str, ...] = ()

    def __str__(self) -> str:
        where = f"{self.register}"
        if self.bit is not None:
            where += f" bit {self.bit}"
        if self.fields:
            where += f" ({', '.join(self.fields)})"
        return f"[{self.constraint}] {where}: {self.detail}"


@dataclass
class AuditResult:
    passed: bool
    violations: list[Violation] = field(default_factory=list)
    registers_checked: int = 0
    elapsed_ms: float = 0.0

    def violations_for(self, register: str) -> list[Violation]:
        return [v for v in self.violations if v.register == register]

    def summary(self) -> str:
        if self.passed:
            return f"PASS: {self.registers_checked} registers verified in {self.elapsed_ms:.1f}ms"
        return (
            f"FAIL: {len(self.violations)} violation(s) across "
            f"{self.registers_checked} registers in {self.elapsed_ms:.1f}ms"
        )


def _bit_accounting(fields: Iterable[BitField], width: int) -> tuple[int, list[int]]:
    """Return (bits_accounted, unaccounted_bit_indices) computed in plain Python.

    Z3 proves the *contradiction*; Python computes the *diagnosis*. Doing the
    diagnosis here keeps the unsat core readable and lets us name the missing bit.
    """
    covered = 0
    for f in fields:
        covered |= f.mask
    full = (1 << width) - 1
    missing = [b for b in range(width) if not (covered >> b) & 1]
    return bin(covered & full).count("1"), missing


def _audit_register(reg: Register, base_address: int) -> list[Violation]:
    """Prove the four constraints for one register. Returns [] when all hold."""
    violations: list[Violation] = []
    solver = z3.Solver()
    solver.set(unsat_core=True)

    # ---- (a) address arithmetic and alignment -------------------------------
    # Computed in Python, asserted in Z3. The model never did this arithmetic.
    base = z3.BitVecVal(base_address, 64)
    off = z3.BitVecVal(reg.offset, 64)
    abs_addr = z3.BitVec(f"{reg.name}__abs_addr", 64)

    solver.assert_and_track(abs_addr == base + off, f"{reg.name}:addr_def")
    solver.assert_and_track(
        z3.URem(abs_addr, z3.BitVecVal(ALIGNMENT_BYTES, 64)) == 0,
        f"{reg.name}:alignment",
    )

    if solver.check() == z3.unsat:
        violations.append(
            Violation(
                register=reg.name,
                constraint="alignment",
                detail=(
                    f"base 0x{base_address:X} + offset 0x{reg.offset:X} = "
                    f"0x{base_address + reg.offset:X} is not {ALIGNMENT_BYTES}-byte aligned"
                ),
            )
        )

    # ---- (b) pairwise bitfield disjointness ---------------------------------
    # mask_i & mask_j == 0 for every pair. Proved over bitvectors, not integers,
    # because the masks are what the generated C will actually use.
    fields = reg.fields
    for i in range(len(fields)):
        for j in range(i + 1, len(fields)):
            fi, fj = fields[i], fields[j]
            overlap = fi.mask & fj.mask
            if overlap:
                s2 = z3.Solver()
                mi = z3.BitVecVal(fi.mask, 64)
                mj = z3.BitVecVal(fj.mask, 64)
                s2.add(mi & mj != 0)
                if s2.check() == z3.sat:
                    bits = [b for b in range(reg.width) if (overlap >> b) & 1]
                    violations.append(
                        Violation(
                            register=reg.name,
                            constraint="overlap",
                            detail=(
                                f"fields '{fi.name}' [{fi.msb}:{fi.lsb}] and "
                                f"'{fj.name}' [{fj.msb}:{fj.lsb}] both claim "
                                f"bit{'s' if len(bits) > 1 else ''} "
                                f"{', '.join(map(str, bits))}"
                            ),
                            bit=bits[0] if bits else None,
                            fields=(fi.name, fj.name),
                        )
                    )

    # ---- (c) width conservation — THE IMPORTANT ONE -------------------------
    if reg.width not in VALID_WIDTHS:
        violations.append(
            Violation(
                register=reg.name,
                constraint="width_conservation",
                detail=f"declared width {reg.width} is not one of {VALID_WIDTHS}",
            )
        )
    else:
        # Any field claiming a bit at or beyond the register width is an
        # out-of-range extraction, not an accounting shortfall. Report it as such.
        for f in fields:
            if f.msb >= reg.width:
                violations.append(
                    Violation(
                        register=reg.name,
                        constraint="width_conservation",
                        detail=(
                            f"field '{f.name}' [{f.msb}:{f.lsb}] exceeds the "
                            f"{reg.width}-bit register (max bit index {reg.width - 1})"
                        ),
                        bit=f.msb,
                        fields=(f.name,),
                    )
                )

        in_range = [f for f in fields if f.msb < reg.width]
        accounted, missing = _bit_accounting(in_range, reg.width)

        s3 = z3.Solver()
        s3.set(unsat_core=True)
        total = z3.Int(f"{reg.name}__accounted")
        s3.assert_and_track(total == accounted, f"{reg.name}:accounted_def")
        s3.assert_and_track(total == reg.width, f"{reg.name}:width_conservation")

        if s3.check() == z3.unsat and not any(
            v.constraint == "width_conservation" for v in violations
        ):
            violations.append(
                Violation(
                    register=reg.name,
                    constraint="width_conservation",
                    detail=(
                        f"{accounted} of {reg.width} bits accounted for; "
                        f"unaccounted bit{'s' if len(missing) > 1 else ''}: "
                        f"{', '.join(map(str, missing))}"
                    ),
                    bit=missing[0] if missing else None,
                )
            )

    # ---- (d) reset value respects reserved bits -----------------------------
    reserved = reg.reserved_mask
    if reserved:
        s4 = z3.Solver()
        rv = z3.BitVecVal(reg.reset_value, 64)
        rm = z3.BitVecVal(reserved, 64)
        s4.add(rv & rm != 0)
        if s4.check() == z3.sat:
            offending = [b for b in range(reg.width) if (reg.reset_value & reserved >> 0) >> b & 1]
            violations.append(
                Violation(
                    register=reg.name,
                    constraint="reserved_reset",
                    detail=(
                        f"reset_value 0x{reg.reset_value:X} sets reserved "
                        f"bit{'s' if len(offending) > 1 else ''} "
                        f"{', '.join(map(str, offending))} "
                        f"(reserved mask 0x{reserved:X})"
                    ),
                    bit=offending[0] if offending else None,
                )
            )

    return violations


def audit(ir: PeripheralIR, *, mark: bool = True) -> AuditResult:
    """Prove every register in the IR. This is the gate.

    When `mark` is True, each register's `.verified` flag is set from its result,
    so downstream codegen can simply iterate `ir.verified_registers` and be unable
    to emit anything unproved.
    """
    start = time.perf_counter()
    violations: list[Violation] = []

    # Duplicate offsets are a property of the set, not of any one register.
    seen: dict[int, str] = {}
    for reg in ir.registers:
        if reg.offset in seen:
            violations.append(
                Violation(
                    register=reg.name,
                    constraint="duplicate_offset",
                    detail=(
                        f"offset 0x{reg.offset:X} already claimed by '{seen[reg.offset]}'"
                    ),
                )
            )
        else:
            seen[reg.offset] = reg.name

    for reg in ir.registers:
        reg_violations = _audit_register(reg, ir.base_address)
        reg_violations += [
            v for v in violations if v.register == reg.name and v.constraint == "duplicate_offset"
        ]
        if mark:
            reg.verified = not reg_violations
            reg.unverified_reason = (
                "; ".join(str(v) for v in reg_violations) if reg_violations else None
            )
        violations.extend(v for v in reg_violations if v.constraint != "duplicate_offset")

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return AuditResult(
        passed=not violations,
        violations=violations,
        registers_checked=len(ir.registers),
        elapsed_ms=elapsed_ms,
    )
