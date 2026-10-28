"""Tests for the Rust HAL emitter.

Same three rules as the C emitter, because they are properties of the
project rather than of a language: an unverified register reaches no
output, a clock-enable erratum becomes a link-time requirement rather than
an invented write, and a forbidden value is refused at the write.

Rust makes two of them stronger, and those strengths are asserted here:
`Result` is `#[must_use]`, so a discarded refusal is a compiler warning;
and every MMIO access sits in exactly one `unsafe` block with its safety
argument written beside it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from silicontruth.ir.schema import (
    ErrataConstraint,
    ErrataRule,
    PeripheralIR,
    Provenance,
    Source,
)
from silicontruth.synth.hal_rust_emitter import RustEmitError, emit_rust
from silicontruth.verify.z3_register_audit import audit

FIXTURE = Path(__file__).parent / "fixtures" / "usart1_valid.json"


def errata_prov(page: int = 19) -> Provenance:
    return Provenance(
        page=page, bbox=(0.0, 0.0, 10.0, 10.0), source=Source.ERRATA,
        errata_id="x",
    )


@pytest.fixture()
def ir() -> PeripheralIR:
    obj = PeripheralIR.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    result = audit(obj)
    assert result.passed, [str(v) for v in result.violations]
    for reg in obj.registers:
        reg.verified = True
    return obj


def rule(constraint: ErrataConstraint, register: str = "CR1", **params) -> ErrataRule:
    return ErrataRule(
        errata_id="2.0.0",
        title="Test erratum",
        affected_register=register,
        constraint=constraint,
        params=params,
        provenance=errata_prov(),
    )


# --- the gate -------------------------------------------------------------


def test_nothing_is_emitted_without_a_verified_register(ir: PeripheralIR) -> None:
    """An empty-but-valid module looks like a successful run, which is
    worse than a refusal."""
    for reg in ir.registers:
        reg.verified = False
    with pytest.raises(RustEmitError):
        emit_rust(ir)


def test_unverified_registers_are_absent_but_documented(ir: PeripheralIR) -> None:
    ir.registers[1].verified = False
    ir.registers[1].unverified_reason = "width_conservation: bit 7 unaccounted"
    src = emit_rust(ir).source
    name = ir.registers[1].name
    assert f"{name}_OFFSET" not in src
    # Absence must be a documented decision, not an oversight.
    assert "FAILED verification" in src
    assert name in src
    assert "bit 7 unaccounted" in src


# --- the delay, which is where a silent omission hides --------------------


def test_delay_emits_a_real_instruction_not_a_compiler_fence(
    ir: PeripheralIR,
) -> None:
    """REGRESSION. The first version emitted
    `for _ in 0..16 { compiler_fence(SeqCst) }`.

    compiler_fence is a compile-time barrier that emits NO instruction, so
    a loop whose body is only a fence has no runtime effect and is removed
    outright -- silently deleting a mandatory hardware delay while looking
    like it applied one.
    """
    ir.errata.append(rule(ErrataConstraint.DELAY_CYCLES_AFTER_WRITE, cycles=16))
    src = emit_rust(ir).source
    assert "for _ in 0..16" in src
    assert 'asm!("nop"' in src
    # The word survives in the comment explaining why it is not used; what
    # must not survive is the call.
    assert "compiler_fence(" not in src


def test_delay_cycle_count_comes_from_the_erratum(ir: PeripheralIR) -> None:
    ir.errata.append(rule(ErrataConstraint.DELAY_CYCLES_AFTER_WRITE, cycles=7))
    assert "for _ in 0..7" in emit_rust(ir).source


# --- clock enable ---------------------------------------------------------


def test_clock_enable_becomes_an_extern_symbol(ir: PeripheralIR) -> None:
    """The enable bit is in RCC, which this IR does not describe and Z3
    never verified. Writing an unverified address is the defect this tool
    prevents, so the workaround becomes a link-time requirement."""
    ir.errata.append(rule(ErrataConstraint.CLOCK_ENABLE_BEFORE_ACCESS))
    src = emit_rust(ir).source
    assert 'extern "C" {' in src
    assert "pub fn usart1_enable_clock() -> i32;" in src
    assert "if unsafe { usart1_enable_clock() } != 0" in src
    assert "Error::ClockEnableFailed" in src


def test_clock_enable_runs_before_any_register_write(ir: PeripheralIR) -> None:
    ir.errata.append(rule(ErrataConstraint.CLOCK_ENABLE_BEFORE_ACCESS))
    src = emit_rust(ir).source
    assert src.index("usart1_enable_clock() }") < src.index("wr(CR1_OFFSET")


def test_no_register_is_skipped_because_of_the_clock_hook(ir: PeripheralIR) -> None:
    """The hook writes RCC, not CR1, so CR1 must still get its reset
    value. Suppressing that write was a bug in the C emitter's first fix."""
    ir.errata.append(rule(ErrataConstraint.CLOCK_ENABLE_BEFORE_ACCESS))
    src = emit_rust(ir).source
    for reg in ir.verified_registers:
        assert f"wr({reg.name}_OFFSET, {reg.name}_RESET)" in src


# --- avoid_value ----------------------------------------------------------


def test_forbidden_value_setter_returns_result(ir: PeripheralIR) -> None:
    """Result is #[must_use], so discarding the refusal is a compiler
    warning -- stronger than C's ignorable int."""
    field = ir.registers[0].fields[0].name
    ir.errata.append(
        rule(ErrataConstraint.AVOID_VALUE, value=0x3F, field=field)
    )
    src = emit_rust(ir).source
    assert f"pub fn set_cr1_{field.lower()}(value: u32) -> Result<(), Error>" in src
    assert "if value == 0x3F" in src
    assert 'Error::ForbiddenValue { errata: "2.0.0" }' in src


def test_field_scoped_setter_masks_only_that_field(ir: PeripheralIR) -> None:
    field = ir.registers[0].fields[0].name
    ir.errata.append(rule(ErrataConstraint.AVOID_VALUE, value=1, field=field))
    src = emit_rust(ir).source
    assert f"cur & !CR1_{field}_MASK" in src
    assert f"value << CR1_{field}_SHIFT" in src


def test_unverified_field_gets_no_setter(ir: PeripheralIR) -> None:
    ir.errata.append(
        rule(ErrataConstraint.AVOID_VALUE, value=1, field="NOT_A_FIELD")
    )
    src = emit_rust(ir).source
    assert "set_cr1_not_a_field" not in src
    assert "No setter" in src


# --- ordering -------------------------------------------------------------


def test_write_order_erratum_reorders_the_writes(ir: PeripheralIR) -> None:
    """The emitted comment claims generation-time ordering, so it must
    hold."""
    first, second = ir.registers[0].name, ir.registers[1].name
    ir.errata.append(
        rule(ErrataConstraint.WRITE_ORDER_DEPENDENCY, register=first,
             other_register=second)
    )
    src = emit_rust(ir).source
    assert src.index(f"wr({second}_OFFSET") < src.index(f"wr({first}_OFFSET")


def test_a_dependency_cycle_is_refused(ir: PeripheralIR) -> None:
    a, b = ir.registers[0].name, ir.registers[1].name
    ir.errata += [
        rule(ErrataConstraint.WRITE_ORDER_DEPENDENCY, register=a, other_register=b),
        rule(ErrataConstraint.WRITE_ORDER_DEPENDENCY, register=b, other_register=a),
    ]
    with pytest.raises(RustEmitError) as e:
        emit_rust(ir)
    assert "cycle" in str(e.value)


# --- shape ----------------------------------------------------------------


def test_masks_are_computed_in_python(ir: PeripheralIR) -> None:
    src = emit_rust(ir).source
    for f in ir.registers[0].fields:
        if f.reserved:
            continue
        assert f"CR1_{f.name}_MASK: u32 = 0x{f.mask:08X}" in src


def test_every_mmio_access_carries_a_safety_comment(ir: PeripheralIR) -> None:
    """An `unsafe` block without a stated safety argument is the thing
    reviewers wave through."""
    src = emit_rust(ir).source
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if "unsafe {" in line and "fn " not in line:
            window = "\n".join(lines[max(0, i - 4) : i + 1])
            assert "SAFETY" in window, f"unsafe without SAFETY note at line {i}: {line}"


def test_dummy_read_uses_the_volatile_accessor(ir: PeripheralIR) -> None:
    ir.errata.append(rule(ErrataConstraint.DUMMY_READ_REQUIRED))
    src = emit_rust(ir).source
    assert "let _ = unsafe { rd(CR1_OFFSET) };" in src


def test_errata_ids_are_reported(ir: PeripheralIR) -> None:
    ir.errata.append(rule(ErrataConstraint.DUMMY_READ_REQUIRED))
    out = emit_rust(ir)
    assert out.errata_applied == ["2.0.0"]
    assert out.errata_count == 1


def test_no_errata_means_no_errata_code(ir: PeripheralIR) -> None:
    out = emit_rust(ir)
    assert out.errata_applied == []
    assert "ERRATUM" not in out.source
