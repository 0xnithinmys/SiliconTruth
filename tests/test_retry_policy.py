"""T-071/T-072/T-073 — the Z3 retry loop.

Uses a stub re-extractor rather than a model: what is under test is whether a
violation maps to the right pixels and whether the loop gives up honestly, not
whether a VLM can read a table.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from silicontruth.ir.schema import PeripheralIR, Register
from silicontruth.verify.retry_policy import (
    MAX_RETRIES,
    RETRY_DPI,
    locate_failure,
    run_retry_loop,
    scale_bbox,
)
from silicontruth.verify.z3_register_audit import Violation, audit

FIXTURE = Path(__file__).parent / "fixtures" / "usart1_valid.json"


@pytest.fixture
def ir() -> PeripheralIR:
    return PeripheralIR.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _break_bit_31(ir: PeripheralIR) -> Register:
    """The canonical defect: reserved [31:29] misread as [30:29]."""
    cr1 = ir.register_by_name("CR1")
    assert cr1 is not None
    next(f for f in cr1.fields if f.name == "RESERVED_31_29").msb = 30
    return cr1


# ---------------------------------------------------------------------------
# Mapping a violation back to pixels
# ---------------------------------------------------------------------------


def test_bit_level_violation_locates_the_covering_field(ir: PeripheralIR) -> None:
    cr1 = ir.register_by_name("CR1")
    assert cr1 is not None
    dedt = next(f for f in cr1.fields if f.name == "DEDT")  # [20:16]
    v = Violation(register="CR1", constraint="overlap", detail="x", bit=18)
    page, bbox = locate_failure(cr1, v)
    assert page == dedt.provenance.page
    # Padded, so strictly wider than the raw field box.
    assert bbox[0] < dedt.provenance.bbox[0]
    assert bbox[2] > dedt.provenance.bbox[2]


def test_named_fields_take_priority(ir: PeripheralIR) -> None:
    cr1 = ir.register_by_name("CR1")
    assert cr1 is not None
    ue = next(f for f in cr1.fields if f.name == "UE")
    v = Violation(
        register="CR1", constraint="overlap", detail="x", bit=0, fields=("UE", "GHOST")
    )
    page, _ = locate_failure(cr1, v)
    assert page == ue.provenance.page


def test_unaccounted_bit_falls_back_to_bracketing_neighbours(ir: PeripheralIR) -> None:
    """Bit 31 is unaccounted for precisely because no field claims it, so there
    is no covering field to re-read. The loop must widen to the neighbours."""
    cr1 = _break_bit_31(ir)
    v = Violation(
        register="CR1", constraint="width_conservation", detail="31 of 32", bit=31
    )
    page, bbox = locate_failure(cr1, v)
    assert page > 0
    assert bbox[2] > bbox[0] and bbox[3] > bbox[1]


def test_register_level_violation_uses_register_provenance(ir: PeripheralIR) -> None:
    brr = ir.register_by_name("BRR")
    assert brr is not None
    v = Violation(register="BRR", constraint="alignment", detail="not aligned")
    page, _ = locate_failure(brr, v)
    assert page == brr.provenance.page


# ---------------------------------------------------------------------------
# Resolution scaling -- the same trap as in PDF ingestion
# ---------------------------------------------------------------------------


def test_bbox_doubles_from_300_to_600_dpi() -> None:
    assert scale_bbox((10.0, 20.0, 30.0, 40.0), from_dpi=300, to_dpi=600) == (
        20.0,
        40.0,
        60.0,
        80.0,
    )


def test_bbox_scaling_is_identity_at_equal_dpi() -> None:
    b = (1.5, 2.5, 3.5, 4.5)
    assert scale_bbox(b, from_dpi=300, to_dpi=300) == b


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def test_clean_ir_triggers_no_retries(ir: PeripheralIR) -> None:
    calls: list[str] = []

    def never(reg, **kw):
        calls.append(reg.name)
        return None

    result, report = run_retry_loop(ir, never)
    assert result.passed
    assert calls == []
    assert report.first_pass_rate == 1.0
    assert report.final_pass_rate == 1.0


def test_successful_repair_restores_the_register(ir: PeripheralIR) -> None:
    """A re-read at 600 DPI that gets the bit right must repair the IR."""
    pristine = copy.deepcopy(ir.register_by_name("CR1"))
    _break_bit_31(ir)

    seen: list[int] = []

    def fix(reg: Register, *, page: int, bbox, dpi: int) -> Register:
        seen.append(dpi)
        return copy.deepcopy(pristine)

    result, report = run_retry_loop(ir, fix)

    assert seen == [RETRY_DPI], "the retry must re-render at 600 DPI"
    assert result.passed, f"still failing: {result.violations}"
    assert report.repaired == ["CR1"]
    assert report.abandoned == []
    assert report.first_pass_rate < report.final_pass_rate == 1.0


def test_unrepairable_register_is_abandoned_not_silently_passed(ir: PeripheralIR) -> None:
    """The honest outcome. A visible gap beats a silent wrong offset."""
    _break_bit_31(ir)

    def useless(reg, **kw):
        return None  # the model cannot do better

    result, report = run_retry_loop(ir, useless)

    assert not result.passed
    assert report.abandoned == ["CR1"]
    assert report.repaired == []

    cr1 = ir.register_by_name("CR1")
    assert cr1 is not None and not cr1.verified
    assert "abandoned after 3" in (cr1.unverified_reason or "")


def test_retries_are_capped(ir: PeripheralIR) -> None:
    _break_bit_31(ir)
    attempts: list[int] = []

    def counting(reg, **kw):
        attempts.append(1)
        return None

    _, report = run_retry_loop(ir, counting)
    assert len(attempts) == MAX_RETRIES
    assert len(report.attempts) == MAX_RETRIES


def test_a_worse_re_extraction_is_discarded(ir: PeripheralIR) -> None:
    """If the model comes back with something that still fails, the loop must
    not keep drifting; the previous version is restored."""
    _break_bit_31(ir)

    def worse(reg: Register, **kw) -> Register:
        bad = copy.deepcopy(reg)
        bad.offset = 0x03  # introduces a NEW defect
        return bad

    run_retry_loop(ir, worse)
    cr1 = ir.register_by_name("CR1")
    assert cr1 is not None
    assert cr1.offset == 0x00, "a worse re-extraction was allowed to persist"


def test_abandoned_register_is_excluded_from_codegen(ir: PeripheralIR) -> None:
    _break_bit_31(ir)
    run_retry_loop(ir, lambda reg, **kw: None)

    assert "CR1" not in [r.name for r in ir.verified_registers]
    assert "CR1" in [r.name for r in ir.unverified_registers]

    from silicontruth.synth.svd_emitter import emit_svd

    assert "<name>CR1</name>" not in emit_svd(ir)


def test_report_tracks_the_pass_rate_delta(ir: PeripheralIR) -> None:
    """T-074: showing the retry loop earning its keep is itself a selling point."""
    pristine = copy.deepcopy(ir.register_by_name("CR1"))
    _break_bit_31(ir)
    _, report = run_retry_loop(ir, lambda reg, **kw: copy.deepcopy(pristine))

    assert report.first_pass_rate == pytest.approx(2 / 3)
    assert report.final_pass_rate == 1.0
    assert "67% -> after retry 100%" in report.summary()
    assert "1 repaired, 0 abandoned" in report.summary()


def test_on_event_receives_each_attempt(ir: PeripheralIR) -> None:
    """The UI streams these so a judge watches the loop work."""
    _break_bit_31(ir)
    events = []
    run_retry_loop(ir, lambda reg, **kw: None, on_event=events.append)

    assert len(events) == MAX_RETRIES
    assert events[0].register == "CR1"
    assert events[0].dpi == RETRY_DPI
    assert events[0].violations_before
    assert "bit 31" in events[0].violations_before[0]


def test_re_extractor_receives_the_scaled_bbox(ir: PeripheralIR) -> None:
    _break_bit_31(ir)
    got: dict = {}

    def capture(reg, *, page, bbox, dpi):
        got.update(page=page, bbox=bbox, dpi=dpi)
        return None

    run_retry_loop(ir, capture, base_dpi=300, retry_dpi=600)
    assert got["dpi"] == 600
    # A 300 DPI bbox scaled to 600 must exceed the original page-space values.
    assert got["bbox"][2] > 2000
