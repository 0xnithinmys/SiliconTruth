"""Tests for the name-corroboration check.

This check exists because of a measured false negative, and the first test
below reconstructs it exactly. At 42 DPI the model invented a field `M1`
at bit 28 and slid EOBIE, RTOIE and DEAT down to make room. The result
still tiled bits 0..31 once each with no gap and no overlap, so all four
Z3 constraints were genuinely satisfied and the gate passed a wrong read
three times running.

No solver can catch that: there is no arithmetic contradiction. The error
is in the names, not the numbers -- so the check is whether the name was
printed on the page at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from silicontruth.ingest.pdf_render import extract_spans
from silicontruth.ir.extractor import build_register
from silicontruth.verify.text_corroboration import (
    Corroboration,
    corroborate,
    corroborate_register,
)
from silicontruth.verify.z3_register_audit import audit

PDF = Path("benchmarks/synthetic/synthetic_usart.pdf")
BBOX = (0.0, 0.0, 595.0, 842.0)


def field(name: str, msb: int, lsb: int, reserved: bool = False) -> dict:
    return {
        "name": name, "msb": msb, "lsb": lsb, "access": "rw",
        "reserved": reserved, "description": "",
    }


def register(fields: list[dict]):
    return build_register(
        {
            "register_name": "USART_CR1",
            "offset_hex": "0x00",
            "reset_value_hex": "0x0000 0000",
            "fields": fields,
        },
        page=1,
        bbox=BBOX,
    ).register


CORRECT = [
    field("RESERVED", 31, 29, True), field("EOBIE", 28, 28),
    field("RTOIE", 27, 27), field("DEAT", 26, 21),
    field("DEDT", 20, 16), field("OVER8", 15, 0),
]

# The exact 42 DPI misread: M1 invented, the rest slid down one.
MISREAD = [
    field("RESERVED", 31, 29, True), field("M1", 28, 28),
    field("EOBIE", 27, 27), field("RTOIE", 26, 26),
    field("DEAT", 25, 21), field("DEDT", 20, 16), field("OVER8", 15, 0),
]


@pytest.fixture(scope="module")
def spans():
    if not PDF.exists():
        pytest.skip("synthetic fixture not generated; "
                    "run scripts/make_synthetic_datasheet.py")
    return extract_spans(str(PDF), 1)


# --- the false negative this module was written for -----------------------


def test_the_measured_misread_satisfies_every_z3_constraint(spans):
    """Establishes the premise. If Z3 caught this, the module would be
    unnecessary -- so the test asserts that it does NOT."""
    from silicontruth.ir.extractor import to_ir, ExtractionReport

    ir = to_ir(
        [ExtractionReport(register=register(MISREAD), raw={})],
        chip="synthetic", peripheral="USART1", base_address=0x40011000,
    )
    result = audit(ir)
    assert result.passed, (
        "premise broken: Z3 now catches this, so this test needs rewriting"
    )
    assert sum(f.msb - f.lsb + 1 for f in ir.registers[0].fields) == 32


def test_corroboration_catches_the_invented_field(spans):
    """The catch Z3 cannot make."""
    r = corroborate_register(register(MISREAD), spans)
    assert r.status is Corroboration.VIOLATIONS
    assert not r.passed
    assert [v.field for v in r.violations] == ["M1"]
    assert "invented" in r.violations[0].detail


def test_a_correct_read_is_corroborated(spans):
    """And it must not fire on a good read -- a check that rejects
    everything is as useless as one that passes everything. The first
    version did exactly that, because PyMuPDF hands back spans at
    CHARACTER granularity, so EOBIE was never a token."""
    r = corroborate_register(register(CORRECT), spans)
    assert r.status is Corroboration.CORROBORATED
    assert r.passed
    assert r.checked == 5


@pytest.mark.parametrize("name", ["EOBIE", "RTOIE", "DEAT", "DEDT", "OVER8",
                                  "CMIE", "MME", "WAKE", "PCE", "PEIE",
                                  "TXEIE", "TCIE", "RXNEIE", "IDLEIE",
                                  "UESM", "UE"])
def test_every_real_field_name_is_found(spans, name):
    """Guards against the character-granularity regression returning."""
    r = corroborate_register(register([field(name, 31, 0)]), spans)
    assert r.passed, f"{name} is printed on the page but was not found"


@pytest.mark.parametrize("name", ["M1", "SPURIOUS", "FAKEFIELD", "ZZTOP"])
def test_invented_names_are_rejected(spans, name):
    r = corroborate_register(register([field(name, 31, 0)]), spans)
    assert not r.passed


# --- scope, stated so the check is not misread ---------------------------


def test_no_text_layer_reports_unavailable_not_pass():
    """A scanned raster manual has no text layer. Reporting a pass from an
    empty span list would be exactly the vacuous pass this module exists
    to eliminate."""
    r = corroborate_register(register(CORRECT), [])
    assert r.status is Corroboration.UNAVAILABLE
    assert r.passed is False
    assert "no text layer" in r.reason


def test_unavailable_is_not_passed():
    """Explicit, because `not failed` is the tempting shorthand and it is
    wrong: a check that could not run has not been satisfied."""
    r = corroborate_register(register(CORRECT), [])
    assert r.passed is False
    assert r.violations == []


def test_reserved_fields_are_not_checked(spans):
    """The extractor renames reserved runs RESERVED_<msb>_<lsb>, so those
    names are ours, not the page's. Checking them would be checking our own
    naming convention."""
    r = corroborate_register(
        register([field("RESERVED", 31, 0, True)]), spans
    )
    assert r.checked == 0
    assert r.passed


def test_whole_ir_is_unavailable_if_any_page_lacks_text(spans):
    """A per-register mixture is too easy to misread as a pass."""
    from silicontruth.ir.extractor import ExtractionReport, to_ir

    ir = to_ir(
        [ExtractionReport(register=register(CORRECT), raw={})],
        chip="c", peripheral="USART1", base_address=0x40011000,
    )
    assert corroborate(ir, {}).status is Corroboration.UNAVAILABLE
    assert corroborate(ir, {1: spans}).status is Corroboration.CORROBORATED


def test_case_and_punctuation_do_not_matter(spans):
    r = corroborate_register(register([field("eobie", 31, 0)]), spans)
    assert r.passed
