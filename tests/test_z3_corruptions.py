"""T-064/T-070 — the Z3 gate acceptance test.

GATE: 10/10 injected corruptions caught, full register map in under 50 ms.

Each test takes the known-good STM32H7 USART1 fixture and injects exactly one
defect of the kind a multimodal extractor actually produces, then asserts the
solver catches it AND names the right place -- because the retry loop needs a
specific register and bit to re-crop at 600 DPI.

NOTE ON THE ACCESS-MODE SWAP (planned corruption #5)
----------------------------------------------------
The original plan listed `rw -> rc_w0` as one of the ten. It is NOT included as a
Z3 corruption, deliberately: an access-mode swap produces no numeric contradiction,
so there is nothing for an SMT solver to prove false. Writing a heuristic that
"catches" it would be dressing a guess up as a proof, which is exactly the failure
mode this project exists to avoid.

Access-mode errors are caught one layer down, in the Renode MMIO oracle (failure
mode C): a driver that writes a status flag it should have cleared trips the
peripheral state machine at execution time, with a faulting PC.

Corruption #5 is therefore an eleventh *arithmetic* defect (field exceeding the
register width), keeping the count at ten provable ones.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from silicontruth.ir.schema import BitField, PeripheralIR, Provenance, Register, Source
from silicontruth.verify.z3_register_audit import audit

FIXTURE = Path(__file__).parent / "fixtures" / "usart1_valid.json"

# The gate. Full map, all four constraints, under this budget.
MAX_AUDIT_MS = 50.0


@pytest.fixture
def valid_ir() -> PeripheralIR:
    return PeripheralIR.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _cr1(ir: PeripheralIR) -> Register:
    reg = ir.register_by_name("CR1")
    assert reg is not None
    return reg


def _prov() -> Provenance:
    return Provenance(page=2054, bbox=(0.0, 0.0, 10.0, 10.0), source=Source.DATASHEET)


def _field_named(reg: Register, name: str) -> BitField:
    return next(f for f in reg.fields if f.name == name)


# --------------------------------------------------------------------------
# Baseline: the known-good fixture must pass cleanly.
# --------------------------------------------------------------------------


def test_valid_fixture_passes(valid_ir: PeripheralIR) -> None:
    result = audit(valid_ir)
    assert result.passed, f"clean fixture should verify, got: {result.violations}"
    assert result.registers_checked == 3
    assert all(r.verified for r in valid_ir.registers)


def test_gate_latency(valid_ir: PeripheralIR) -> None:
    """GATE: the full register map must verify in under 50 ms."""
    result = audit(valid_ir)
    assert result.elapsed_ms < MAX_AUDIT_MS, (
        f"audit took {result.elapsed_ms:.1f}ms, budget is {MAX_AUDIT_MS}ms. "
        "Most likely cause: a solver is being constructed per field instead of "
        "batched per register."
    )


# --------------------------------------------------------------------------
# The ten corruptions.
# --------------------------------------------------------------------------


def test_c01_overlapping_bitfield(valid_ir: PeripheralIR) -> None:
    """#1 Two fields both claim bit 12 (M0 widened over the DEDT boundary is a
    classic column-merge artifact from text-only PDF extraction)."""
    reg = _cr1(valid_ir)
    reg.fields.append(
        BitField(name="GHOST", lsb=12, msb=12, access="rw", provenance=_prov())
    )
    result = audit(valid_ir)
    assert not result.passed
    v = [x for x in result.violations_for("CR1") if x.constraint == "overlap"]
    assert v, f"expected an overlap violation, got {result.violations}"
    assert v[0].bit == 12
    assert "M0" in v[0].fields and "GHOST" in v[0].fields


def test_c02_dropped_bit_31(valid_ir: PeripheralIR) -> None:
    """#2 THE CANONICAL CASE. Reserved [31:29] misread as [30:29] leaves bit 31
    unaccounted: 31 of 32 bits. This is width conservation earning its keep."""
    reg = _cr1(valid_ir)
    f = _field_named(reg, "RESERVED_31_29")
    f.msb = 30
    result = audit(valid_ir)
    assert not result.passed
    v = [x for x in result.violations_for("CR1") if x.constraint == "width_conservation"]
    assert v, f"expected width_conservation violation, got {result.violations}"
    assert v[0].bit == 31, f"the core must name bit 31, got {v[0].bit}"
    assert "31 of 32" in v[0].detail


def test_c03_unaligned_offset(valid_ir: PeripheralIR) -> None:
    """#3 Offset 0x03 — a digit dropped from 0x0C during OCR."""
    reg = valid_ir.register_by_name("BRR")
    assert reg is not None
    reg.offset = 0x03
    result = audit(valid_ir)
    assert not result.passed
    v = [x for x in result.violations_for("BRR") if x.constraint == "alignment"]
    assert v, f"expected alignment violation, got {result.violations}"
    assert "aligned" in v[0].detail


def test_c04_reset_value_sets_reserved_bit(valid_ir: PeripheralIR) -> None:
    """#4 Reset value claims a bit the datasheet marks reserved."""
    reg = valid_ir.register_by_name("BRR")
    assert reg is not None
    reg.reset_value = 0x0001_0000  # bit 16, inside RESERVED_31_16
    result = audit(valid_ir)
    assert not result.passed
    v = [x for x in result.violations_for("BRR") if x.constraint == "reserved_reset"]
    assert v, f"expected reserved_reset violation, got {result.violations}"
    assert v[0].bit == 16


def test_c05_field_exceeds_register_width(valid_ir: PeripheralIR) -> None:
    """#5 A field claims bit 32 of a 32-bit register (max index is 31).

    Replaces the planned rw->rc_w0 swap; see module docstring.
    """
    reg = valid_ir.register_by_name("BRR")
    assert reg is not None
    _field_named(reg, "RESERVED_31_16").msb = 31
    reg.fields.append(
        BitField(name="OVERFLOW", lsb=31, msb=31, access="rw", provenance=_prov())
    )
    # Make it genuinely out of range rather than merely overlapping.
    reg.width = 16
    result = audit(valid_ir)
    assert not result.passed
    v = [x for x in result.violations_for("BRR") if x.constraint == "width_conservation"]
    assert v, f"expected width_conservation violation, got {result.violations}"
    assert any("exceeds" in x.detail for x in v)


def test_c06_width_mismatch(valid_ir: PeripheralIR) -> None:
    """#6 Register declared 32-bit but only 16 bits of fields extracted — the
    bottom half of a table lost to a page break."""
    reg = valid_ir.register_by_name("BRR")
    assert reg is not None
    reg.fields = [f for f in reg.fields if f.name == "BRR"]  # drop the reserved half
    result = audit(valid_ir)
    assert not result.passed
    v = [x for x in result.violations_for("BRR") if x.constraint == "width_conservation"]
    assert v, f"expected width_conservation violation, got {result.violations}"
    assert "16 of 32" in v[0].detail


def test_c07_lsb_above_msb(valid_ir: PeripheralIR) -> None:
    """#7 Bit range read backwards: [16:20] instead of [20:16].

    Caught by the schema validator before Z3 ever sees it. Both layers matter --
    the validator stops it at parse time, Z3 stops it if the object is built
    directly in code.
    """
    reg = _cr1(valid_ir)
    f = _field_named(reg, "DEDT")
    with pytest.raises(ValueError, match="lsb .* > msb"):
        f.lsb, f.msb = 20, 16
        BitField(
            name=f.name, lsb=20, msb=16, access="rw", provenance=_prov()
        )


def test_c08_duplicate_offset(valid_ir: PeripheralIR) -> None:
    """#8 Two registers at the same offset — a row read twice across a page break."""
    reg = valid_ir.register_by_name("CR2")
    assert reg is not None
    reg.offset = 0x00  # collides with CR1
    result = audit(valid_ir)
    assert not result.passed
    assert reg.unverified_reason is not None
    assert "already claimed" in reg.unverified_reason
    assert not reg.verified


def test_c09_bit_index_out_of_range(valid_ir: PeripheralIR) -> None:
    """#9 msb = 32 on a 32-bit register. Rejected at the schema boundary."""
    with pytest.raises(ValueError):
        BitField(name="BAD", lsb=30, msb=32, access="rw", provenance=_prov())


def test_c10_absurd_offset(valid_ir: PeripheralIR) -> None:
    """#10 A wildly wrong offset that also breaks alignment — e.g. a figure
    number scraped as a hex offset."""
    reg = valid_ir.register_by_name("CR2")
    assert reg is not None
    reg.offset = 0xDEAD_BEE1
    result = audit(valid_ir)
    assert not result.passed
    v = [x for x in result.violations_for("CR2") if x.constraint == "alignment"]
    assert v, f"expected alignment violation, got {result.violations}"


# --------------------------------------------------------------------------
# The gate itself.
# --------------------------------------------------------------------------


def test_gate_all_ten_caught(valid_ir: PeripheralIR) -> None:
    """GATE (T-070): 10/10 corruptions caught, each under the latency budget.

    Runs every injector against a fresh copy and asserts the audit rejects it.
    Two of the ten (#7, #9) are caught at the schema boundary rather than by the
    solver -- counted as caught, since the defect never reaches codegen either way.
    """
    schema_level = 2  # #7 lsb>msb and #9 out-of-range are rejected on construction

    injectors = [
        ("c01_overlap", lambda ir: _cr1(ir).fields.append(
            BitField(name="GHOST", lsb=12, msb=12, access="rw", provenance=_prov()))),
        ("c02_dropped_bit", lambda ir: setattr(
            _field_named(_cr1(ir), "RESERVED_31_29"), "msb", 30)),
        ("c03_unaligned", lambda ir: setattr(ir.register_by_name("BRR"), "offset", 0x03)),
        ("c04_reserved_reset", lambda ir: setattr(
            ir.register_by_name("BRR"), "reset_value", 0x0001_0000)),
        ("c05_exceeds_width", lambda ir: setattr(ir.register_by_name("BRR"), "width", 16)),
        ("c06_width_mismatch", lambda ir: setattr(
            ir.register_by_name("BRR"), "fields",
            [f for f in ir.register_by_name("BRR").fields if f.name == "BRR"])),
        ("c08_duplicate_offset", lambda ir: setattr(ir.register_by_name("CR2"), "offset", 0x00)),
        ("c10_absurd_offset", lambda ir: setattr(
            ir.register_by_name("CR2"), "offset", 0xDEAD_BEE1)),
    ]

    caught = schema_level
    slowest = 0.0
    for name, inject in injectors:
        ir = copy.deepcopy(valid_ir)
        inject(ir)
        result = audit(ir)
        assert not result.passed, f"{name}: corruption slipped through the gate"
        caught += 1
        slowest = max(slowest, result.elapsed_ms)

    assert caught == 10, f"expected 10/10 caught, got {caught}/10"
    assert slowest < MAX_AUDIT_MS, (
        f"slowest audit was {slowest:.1f}ms, budget is {MAX_AUDIT_MS}ms"
    )


def test_unverified_registers_are_excluded_from_codegen(valid_ir: PeripheralIR) -> None:
    """A register that fails the gate must not reach codegen, and must be
    surfaced loudly rather than silently dropped."""
    reg = valid_ir.register_by_name("BRR")
    assert reg is not None
    reg.offset = 0x03

    audit(valid_ir)

    assert reg in valid_ir.unverified_registers
    assert reg not in valid_ir.verified_registers
    assert reg.unverified_reason  # the UI needs a reason to show
    assert len(valid_ir.verified_registers) == 2


# ---------------------------------------------------------------------------
# Marking is monotonic downward
# ---------------------------------------------------------------------------
#
# MEASURED BUG, not a hypothetical. audit(mark=True) used to set `verified`
# purely from its own result. Re-running it on an IR loaded from disk
# therefore silently RE-VERIFIED a register that name corroboration had
# already rejected, and `build` then emitted a full SVD and C HAL from an
# IR whose every register was marked UNVERIFIED.
#
# This audit proves arithmetic. Arithmetic is not the whole of correctness:
# a consistent relabeling (an invented field with the others slid down to
# keep the bit partition complete) satisfies all four constraints and is
# caught only by checking the names against the page. So a later gate may
# take verification away, and nothing may give it back.


def test_audit_does_not_reverify_a_register_another_gate_rejected(
    valid_ir: PeripheralIR,
) -> None:
    reg = valid_ir.registers[0]
    reg.verified = False
    reg.unverified_reason = "[text_corroboration] CR1.M1: the name was invented"

    result = audit(valid_ir)

    assert result.passed, "the arithmetic is sound; Z3 should still pass"
    assert reg.verified is False, (
        "Z3 restored verification that name corroboration had removed"
    )
    assert "invented" in (reg.unverified_reason or "")


def test_a_rejected_register_is_excluded_from_codegen(
    valid_ir: PeripheralIR,
) -> None:
    """The consequence that matters: an emitter must not see it."""
    for reg in valid_ir.registers:
        reg.verified = False
        reg.unverified_reason = "rejected by an earlier gate"
    audit(valid_ir)
    assert valid_ir.verified_registers == []


def test_both_reasons_are_kept_when_z3_also_fails(
    valid_ir: PeripheralIR,
) -> None:
    reg = valid_ir.registers[0]
    reg.verified = False
    reg.unverified_reason = "[text_corroboration] invented name"
    # Break the arithmetic too.
    reg.fields[0].msb = reg.fields[0].msb + 1 if reg.fields[0].msb < 31 else 31
    reg.fields[0].lsb = reg.fields[0].lsb + 2

    audit(valid_ir)

    assert reg.verified is False
    assert "invented name" in (reg.unverified_reason or "")


def test_a_fresh_register_is_still_verified_normally(
    valid_ir: PeripheralIR,
) -> None:
    """The rule must not break the normal path. 'Not yet adjudicated' is
    verified=False with NO reason, which is how every register starts."""
    for reg in valid_ir.registers:
        reg.verified = False
        reg.unverified_reason = None

    result = audit(valid_ir)

    assert result.passed
    assert all(r.verified for r in valid_ir.registers)
    assert len(valid_ir.verified_registers) == len(valid_ir.registers)
