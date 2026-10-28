"""T-081/T-083 — C HAL emission and errata injection.

The errata tests are the important ones. Errata injection is the project's
differentiator, and the thing a naive single-pass driver provably omits.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from silicontruth.ir.schema import (
    ErrataConstraint,
    ErrataRule,
    PeripheralIR,
    Provenance,
    Source,
)
from silicontruth.synth.hal_c_emitter import HalEmitError, emit_hal, emit_header, emit_source
from silicontruth.verify.z3_register_audit import audit

FIXTURE = Path(__file__).parent / "fixtures" / "usart1_valid.json"


def errata_prov(page: int = 19) -> Provenance:
    return Provenance(
        page=page,
        bbox=(100.0, 200.0, 900.0, 240.0),
        source=Source.ERRATA,
        errata_id="2.14.1",
    )


@pytest.fixture
def ir() -> PeripheralIR:
    x = PeripheralIR.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    assert audit(x).passed
    return x


@pytest.fixture
def ir_with_errata(ir: PeripheralIR) -> PeripheralIR:
    ir.errata.append(
        ErrataRule(
            errata_id="2.14.1",
            title="USART clock enable requires a 3-cycle delay before first access",
            affected_register="CR1",
            constraint=ErrataConstraint.DELAY_CYCLES_AFTER_WRITE,
            params={"cycles": 3},
            provenance=errata_prov(19),
        )
    )
    return ir


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_unaudited_ir_cannot_emit() -> None:
    raw = PeripheralIR.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    with pytest.raises(HalEmitError, match="no verified registers"):
        emit_header(raw)


def test_unverified_register_is_excluded_and_announced(ir: PeripheralIR) -> None:
    """INVARIANT #1 at the C boundary: the register is absent, and the header
    says so loudly rather than silently dropping it."""
    brr = ir.register_by_name("BRR")
    assert brr is not None
    brr.offset = 0x03
    audit(ir)

    hdr = emit_header(ir)
    assert "USART1_BRR  " not in hdr, "unverified register got an accessor"
    assert "WARNING" in hdr and "BRR" in hdr, "exclusion was silent"
    assert "aligned" in hdr, "the reason was not carried through"


# ---------------------------------------------------------------------------
# Header structure
# ---------------------------------------------------------------------------


def test_header_has_include_guard(ir: PeripheralIR) -> None:
    hdr = emit_header(ir)
    assert "#ifndef SILICONTRUTH_STM32H743_USART1_H" in hdr
    assert "#define SILICONTRUTH_STM32H743_USART1_H" in hdr
    assert hdr.rstrip().endswith("*/")


def test_base_address_matches_ir(ir: PeripheralIR) -> None:
    assert "#define USART1_BASE  (0x40011000UL)" in emit_header(ir)


def test_accessors_are_volatile(ir: PeripheralIR) -> None:
    """Non-volatile MMIO accessors get optimised away. This is not a style point."""
    hdr = emit_header(ir)
    for reg in ("CR1", "CR2", "BRR"):
        m = re.search(rf"#define USART1_{reg}\s+\(\*\(volatile (\w+) \*\)", hdr)
        assert m, f"{reg} accessor missing or not volatile"
        assert m.group(1) == "uint32_t"


def test_bitfield_masks_match_computed_values(ir: PeripheralIR) -> None:
    """The mask is computed in Python from lsb/msb, never supplied by a model."""
    hdr = emit_header(ir)
    # DEDT is [20:16] -> 0x001F0000, shift 16
    assert "#define USART1_CR1_DEDT_SHIFT  (16U)" in hdr
    assert "#define USART1_CR1_DEDT_MASK   (0x001F0000UL)" in hdr
    # UE is bit 0 -> 0x00000001
    assert "#define USART1_CR1_UE_SHIFT  (0U)" in hdr
    assert "#define USART1_CR1_UE_MASK   (0x00000001UL)" in hdr


def test_reserved_fields_get_no_macros(ir: PeripheralIR) -> None:
    assert "RESERVED_" not in emit_header(ir)


def test_offsets_are_emitted_for_every_verified_register(ir: PeripheralIR) -> None:
    hdr = emit_header(ir)
    assert "#define USART1_CR1_OFFSET  (0x00UL)" in hdr
    assert "#define USART1_CR2_OFFSET  (0x04UL)" in hdr
    assert "#define USART1_BRR_OFFSET  (0x0CUL)" in hdr


# ---------------------------------------------------------------------------
# Errata injection -- the differentiator
# ---------------------------------------------------------------------------


def test_errata_delay_is_injected_as_real_code(ir_with_errata: PeripheralIR) -> None:
    src, applied = emit_source(ir_with_errata)
    assert "2.14.1" in applied
    assert "nop" in src, "the delay workaround produced no instructions"
    assert re.search(r"for \(volatile int _d = 0; _d < 3; \+\+_d\)", src)


def test_errata_code_cites_its_source_page(ir_with_errata: PeripheralIR) -> None:
    """The first thing an embedded engineer asks is 'says who?'. The answer has
    to be a page number, in the code, next to the workaround."""
    src, _ = emit_source(ir_with_errata)
    assert "ERRATUM 2.14.1" in src
    assert "errata p.19" in src
    assert "Workaround is mandatory" in src


def test_dummy_read_errata(ir: PeripheralIR) -> None:
    ir.errata.append(
        ErrataRule(
            errata_id="2.3.4",
            title="Dummy read required after BRR write",
            affected_register="BRR",
            constraint=ErrataConstraint.DUMMY_READ_REQUIRED,
            provenance=errata_prov(22),
        )
    )
    src, applied = emit_source(ir)
    assert "2.3.4" in applied
    assert "(void)USART1_BRR;" in src


def test_clock_enable_errata_runs_before_other_writes(ir: PeripheralIR) -> None:
    """Ordering is load-bearing: a clock-enable workaround that runs after the
    first register write has not worked."""
    ir.errata.append(
        ErrataRule(
            errata_id="2.1.1",
            title="Peripheral clock must be enabled before any register access",
            affected_register="CR1",
            constraint=ErrataConstraint.CLOCK_ENABLE_BEFORE_ACCESS,
            params={"enable_bit": "UE"},
            provenance=errata_prov(11),
        )
    )
    src, applied = emit_source(ir)
    assert "2.1.1" in applied
    clock_pos = src.index("ERRATUM 2.1.1")
    # CR1 itself is no longer reset-written (that would clear UE), so compare
    # against the first write to any other register.
    first_write = min(src.index(f"USART1_{r} = ") for r in ("CR2", "BRR"))
    assert clock_pos < first_write, "clock-enable workaround emitted after the first write"


def test_avoid_value_errata_guards_the_write_not_the_read(ir: PeripheralIR) -> None:
    """An avoid_value erratum forbids WRITING a value. The only place that
    can be enforced is the write.

    The earlier emission was `if (BRR == 0) return -1;` inside init() -- a
    read-side equality check on a register nothing had written yet, which
    prevents nothing at all while looking like a safeguard.
    """
    ir.errata.append(
        ErrataRule(
            errata_id="2.9.9",
            title="BRR value 0 is forbidden",
            affected_register="BRR",
            constraint=ErrataConstraint.AVOID_VALUE,
            params={"value": 0},
            provenance=errata_prov(30),
        )
    )
    src, _ = emit_source(ir)
    hdr = emit_header(ir)

    assert "int usart1_brr_set(uint32_t value)" in src
    assert "int usart1_brr_set(uint32_t value);" in hdr
    assert "if (value == 0x0UL)" in src
    assert "erratum 2.9.9 forbids this value" in src
    # The useless read-side check must be gone.
    assert "if (USART1_BRR == 0)" not in src


def test_avoid_value_scoped_to_a_field_masks_only_that_field(
    ir: PeripheralIR,
) -> None:
    """A forbidden 6-bit field value is not a forbidden 32-bit register
    value. Comparing the whole register against it is a different wrong
    answer, so the setter must be field-scoped."""
    field = ir.registers[0].fields[0].name
    ir.errata.append(
        ErrataRule(
            errata_id="2.9.4",
            title="Reserved field value corrupts timing",
            affected_register="CR1",
            constraint=ErrataConstraint.AVOID_VALUE,
            params={"value": 0x3F, "field": field},
            provenance=errata_prov(30),
        )
    )
    src, _ = emit_source(ir)
    setter = f"int usart1_cr1_{field.lower()}_set(uint32_t value)"
    assert setter in src
    assert f"USART1_CR1_{field}_MASK" in src
    assert f"USART1_CR1_{field}_SHIFT" in src
    assert "if (value == 0x3FUL)" in src


def test_avoid_value_on_an_unverified_field_emits_no_setter(
    ir: PeripheralIR,
) -> None:
    """Writing bits no Z3 run verified is the defect this tool prevents,
    so a setter is refused rather than generated against a guess."""
    ir.errata.append(
        ErrataRule(
            errata_id="2.9.5",
            title="Unknown field value forbidden",
            affected_register="CR1",
            constraint=ErrataConstraint.AVOID_VALUE,
            params={"value": 1, "field": "NOT_A_REAL_FIELD"},
            provenance=errata_prov(30),
        )
    )
    src, _ = emit_source(ir)
    assert "not_a_real_field_set(uint32_t" not in src
    assert "No setter is generated" in src


def test_write_order_errata_actually_reorders_the_writes(
    ir: PeripheralIR,
) -> None:
    """The emitted comment claims the sequence enforces the ordering, so
    the sequence must enforce it.

    Registers default to offset order. CR1 is at the lowest offset, so an
    erratum requiring CR1 to be written after BRR makes offset order wrong
    -- and a comment promising something the code does not do is worse than
    no comment at all.
    """
    ir.errata.append(
        ErrataRule(
            errata_id="2.5.0",
            title="CR1 must be written after BRR",
            affected_register="CR1",
            constraint=ErrataConstraint.WRITE_ORDER_DEPENDENCY,
            params={"other_register": "BRR"},
            provenance=errata_prov(14),
        )
    )
    src, _ = emit_source(ir)
    assert src.index("USART1_BRR = ") < src.index("USART1_CR1 = "), (
        "BRR must be written before CR1"
    )
    assert "is written only after BRR" in src


def test_a_write_order_cycle_is_a_hard_error(ir: PeripheralIR) -> None:
    """No write order satisfies a cycle. Picking one would be a guess."""
    ir.errata += [
        ErrataRule(
            errata_id="2.5.1",
            title="CR1 after BRR",
            affected_register="CR1",
            constraint=ErrataConstraint.WRITE_ORDER_DEPENDENCY,
            params={"other_register": "BRR"},
            provenance=errata_prov(14),
        ),
        ErrataRule(
            errata_id="2.5.2",
            title="BRR after CR1",
            affected_register="BRR",
            constraint=ErrataConstraint.WRITE_ORDER_DEPENDENCY,
            params={"other_register": "CR1"},
            provenance=errata_prov(14),
        ),
    ]
    with pytest.raises(HalEmitError) as e:
        emit_source(ir)
    assert "cycle" in str(e.value)


def test_no_errata_means_no_errata_code(ir: PeripheralIR) -> None:
    src, applied = emit_source(ir)
    assert applied == []
    assert "ERRATUM" not in src


def test_all_errata_constraints_have_a_translation(ir: PeripheralIR) -> None:
    """The enum is closed; every member must emit something. A silently skipped
    mandatory workaround is the exact bug this project exists to stop."""
    for c in ErrataConstraint:
        fresh = PeripheralIR.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
        audit(fresh)
        fresh.errata.append(
            ErrataRule(
                errata_id=f"X.{c.value}",
                title=f"test {c.value}",
                affected_register="CR1",
                constraint=c,
                params={"cycles": 2, "enable_bit": "UE", "value": 0, "must_follow": "CR2"},
                provenance=errata_prov(),
            )
        )
        src, applied = emit_source(fresh)
        assert applied, f"{c.value} produced no applied record"
        assert f"ERRATUM X.{c.value}" in src, f"{c.value} emitted no code"


# ---------------------------------------------------------------------------
# Whole-file shape
# ---------------------------------------------------------------------------


def test_emit_hal_bundles_both_files(ir_with_errata: PeripheralIR) -> None:
    hal = emit_hal(ir_with_errata)
    assert hal.header.startswith("/*")
    assert '#include "usart1_hal.h"' in hal.source
    assert "int usart1_init(void)" in hal.header
    assert "int usart1_init(void)" in hal.source
    assert hal.errata_count == 1


def test_source_balances_braces(ir_with_errata: PeripheralIR) -> None:
    """Cheap structural proxy for 'this will compile' while arm-none-eabi-gcc
    is unavailable locally; the real -Werror gate runs in the Modal container."""
    src = emit_hal(ir_with_errata).source
    assert src.count("{") == src.count("}")
    assert src.count("(") == src.count(")")


def test_banner_reports_counts(ir_with_errata: PeripheralIR) -> None:
    hdr = emit_header(ir_with_errata)
    assert "Registers: 3 verified" in hdr
    assert "Errata applied: 1" in hdr


def test_clock_enable_delegates_to_a_hook_instead_of_inventing_a_write(
    ir: PeripheralIR,
) -> None:
    """REGRESSION, and the root-cause fix for an earlier one.

    The clock-enable bit lives in another peripheral (RCC on STM32) that
    this IR does not describe and Z3 never verified. The old emission fell
    back to `CR1 |= CR1` -- nonsense that compiles, which is worse than
    nothing -- and an earlier fix then had to suppress CR1's reset write to
    stop that self-OR being undone.

    Delegating to a declared-but-undefined hook removes both problems: no
    unverified address is written, an unimplemented hook fails at link
    time, and CR1 gets its reset value like any other register.
    """
    ir.errata.append(
        ErrataRule(
            errata_id="2.1.1",
            title="Peripheral clock must be enabled before any register access",
            affected_register="CR1",
            constraint=ErrataConstraint.CLOCK_ENABLE_BEFORE_ACCESS,
            params={},
            provenance=errata_prov(11),
        )
    )
    src, _ = emit_source(ir)
    hdr = emit_header(ir)

    assert "if (usart1_enable_clock() != 0) { return -1; }" in src
    assert "int usart1_enable_clock(void);" in hdr
    # The fabricated self-OR must never reappear.
    assert "USART1_CR1 |= USART1_CR1" not in src

    # The gate runs before any register write.
    assert src.index("usart1_enable_clock()") < src.index("USART1_CR1 = ")

    # Every register still gets initialised, CR1 included.
    assert "USART1_CR1 = 0x0UL;" in src
    assert "USART1_CR2 = 0x0UL;" in src
    assert "USART1_BRR = 0x0UL;" in src
