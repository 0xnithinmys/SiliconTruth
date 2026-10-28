"""Tests for bit-to-name recovery from the printed grid.

This check closes the gap name corroboration leaves: two real names
swapped between two bit positions both appear on the page, so the name
check passes them, and Z3 sees no arithmetic contradiction either.

The heaviest tests here are the CONSERVATISM ones. A layout heuristic that
guesses wrong produces a false FAILURE, which blocks a correct read -- and
that is worse than the false negative this was built to help with. So an
incomplete reconstruction must report UNAVAILABLE, never FAIL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from silicontruth.ingest.pdf_render import TextSpan, extract_spans
from silicontruth.ir.extractor import build_register
from silicontruth.verify.grid_corroboration import (
    GridStatus,
    build_grid_mapping,
    corroborate_grid,
)

PDF = Path("benchmarks/synthetic/synthetic_usart.pdf")
BBOX = (0.0, 0.0, 595.0, 842.0)


@pytest.fixture(scope="module")
def spans():
    if not PDF.exists():
        pytest.skip("run scripts/make_synthetic_datasheet.py first")
    return extract_spans(str(PDF), 1)


def field(name: str, msb: int, lsb: int, reserved: bool = False) -> dict:
    return {"name": name, "msb": msb, "lsb": lsb, "access": "rw",
            "reserved": reserved, "description": ""}


def register(fields: list[dict]):
    return build_register(
        {"register_name": "USART_CR1", "offset_hex": "0x00",
         "reset_value_hex": "0x0000 0000", "fields": fields},
        page=1, bbox=BBOX,
    ).register


TRUE_FIELDS = [
    field("RESERVED", 31, 29, True), field("EOBIE", 28, 28),
    field("RTOIE", 27, 27), field("DEAT", 26, 21), field("DEDT", 20, 16),
    field("OVER8", 15, 15), field("CMIE", 14, 14), field("MME", 13, 13),
    field("M0", 12, 12), field("WAKE", 11, 11), field("PCE", 10, 10),
    field("PS", 9, 9), field("PEIE", 8, 8), field("TXEIE", 7, 7),
    field("TCIE", 6, 6), field("RXNEIE", 5, 5), field("IDLEIE", 4, 4),
    field("TE", 3, 3), field("RE", 2, 2), field("UESM", 1, 1),
    field("UE", 0, 0),
]


# --- reconstruction -------------------------------------------------------


def test_every_bit_is_located(spans):
    mapping, reason = build_grid_mapping(spans, 32)
    assert reason == ""
    assert sorted(mapping) == list(range(32))


def test_small_font_cells_are_not_lost(spans):
    """REGRESSION. RXNEIE and IDLEIE are drawn a point smaller than their
    neighbours, which moves their glyph centres into a different row bucket.
    Exact y bucketing silently dropped them, and the check then "found" two
    mislabelled fields on a correct page."""
    mapping, _ = build_grid_mapping(spans, 32)
    assert mapping[5] == "RXNEIE"
    assert mapping[4] == "IDLEIE"


def test_multi_column_fields_map_to_every_bit_they_span(spans):
    mapping, _ = build_grid_mapping(spans, 32)
    assert all(mapping[b] == "DEAT" for b in range(21, 27))
    assert all(mapping[b] == "DEDT" for b in range(16, 21))


def test_reserved_cells_are_recovered_too(spans):
    mapping, _ = build_grid_mapping(spans, 32)
    assert all(mapping[b] == "Res." for b in (29, 30, 31))


# --- the catch ------------------------------------------------------------


def test_a_correct_read_is_corroborated(spans):
    r = corroborate_grid(register(TRUE_FIELDS), spans)
    assert r.status is GridStatus.CORROBORATED, [str(v) for v in r.violations]
    assert r.passed


def test_two_swapped_names_are_caught(spans):
    """The case name corroboration cannot see: both names are printed on
    the page, so "was it printed?" passes. Only the column says otherwise."""
    swapped = [f.copy() for f in TRUE_FIELDS]
    i = next(k for k, f in enumerate(swapped) if f["name"] == "TE")
    j = next(k for k, f in enumerate(swapped) if f["name"] == "RE")
    swapped[i] = field("RE", 3, 3)
    swapped[j] = field("TE", 2, 2)

    r = corroborate_grid(register(swapped), spans)
    assert r.status is GridStatus.VIOLATIONS
    assert {v.bit for v in r.violations} == {2, 3}


def test_a_whole_slid_block_is_caught(spans):
    """The measured 42 DPI failure: one field invented, the rest slid down
    so the bit partition stays complete."""
    slid = [
        field("RESERVED", 31, 29, True), field("M1", 28, 28),
        field("EOBIE", 27, 27), field("RTOIE", 26, 26),
        field("DEAT", 25, 21), field("DEDT", 20, 16), field("OVER8", 15, 0),
    ]
    r = corroborate_grid(register(slid), spans)
    assert r.status is GridStatus.VIOLATIONS
    assert r.violations


def test_the_violation_names_both_sides(spans):
    """An engineer has to be able to act on it without opening the PDF."""
    swapped = [f.copy() for f in TRUE_FIELDS]
    swapped[-1] = field("UESM", 0, 0)
    swapped[-2] = field("UE", 1, 1)
    r = corroborate_grid(register(swapped), spans)
    detail = str(r.violations[0])
    assert "the page prints" in detail
    assert "but the field claiming it is" in detail


# --- conservatism: a false FAILURE is the worse error ---------------------


def test_no_text_layer_is_unavailable_not_failure():
    r = corroborate_grid(register(TRUE_FIELDS), [])
    assert r.status is GridStatus.UNAVAILABLE
    assert r.passed is False
    assert r.violations == []
    assert "no text layer" in r.reason


def test_a_page_with_no_grid_is_unavailable():
    """Prose must not be mistaken for a bit grid."""
    prose = [
        TextSpan(text=ch, bbox=(10.0 + i * 6, 100.0, 15.0 + i * 6, 110.0), size=9.0)
        for i, ch in enumerate("The USART supports a configurable baud rate.")
    ]
    r = corroborate_grid(register(TRUE_FIELDS), prose)
    assert r.status is GridStatus.UNAVAILABLE
    assert "no bit-number grid" in r.reason


def test_an_incomplete_grid_is_unavailable_not_failure(spans):
    """Half a grid must not become a disagreement report. This is the rule
    that keeps a layout heuristic from blocking a correct read."""
    # Keep only the upper half of the page: one bank, so 16 bits at most.
    half = [s for s in spans if s.bbox[3] < 600.0]
    mapping, reason = build_grid_mapping(half, 32)
    assert mapping == {}
    assert "incomplete" in reason

    r = corroborate_grid(register(TRUE_FIELDS), half)
    assert r.status is GridStatus.UNAVAILABLE
    assert r.violations == []


def test_unavailable_never_counts_as_passed():
    for spans_in in ([], None or []):
        assert corroborate_grid(register(TRUE_FIELDS), spans_in).passed is False


def test_reserved_fields_are_not_compared(spans):
    """The extractor renames reserved runs, so comparing them would compare
    our naming convention against the page's."""
    r = corroborate_grid(register([field("RESERVED_31_29", 31, 29, True)]), spans)
    # No non-reserved field to check, and the grid is complete, so it passes
    # vacuously rather than reporting a disagreement about "Res.".
    assert r.status is GridStatus.CORROBORATED


def test_case_and_punctuation_are_ignored(spans):
    r = corroborate_grid(register([field("eobie", 28, 28)]), spans)
    assert r.passed


def test_one_report_per_field_not_per_bit(spans):
    """A six-bit field that is wrong should say so once."""
    wrong = [field("DEDT", 26, 21)]  # DEAT's columns, claimed by DEDT
    r = corroborate_grid(register(wrong), spans)
    assert len(r.violations) == 1


def test_merged_name_cells_abstain_rather_than_disagree():
    """MEASURED FALSE POSITIVE. Long names in narrow columns can sit so
    close that the inter-cell gap falls below the split threshold, and the
    tokenizer returns them as one run. On the ADC fixture, DEEPPWD and
    ADVREGEN came back as 'DEEPPWDADVREGEN' and the check reported two
    disagreements on a read that was entirely correct.

    Guessing which half belongs to which column is not available. Abstaining
    is, and an incomplete mapping is advisory rather than a failure."""
    adc = Path("benchmarks/suite/adc32/datasheet.pdf")
    if not adc.exists():
        pytest.skip("run scripts/make_benchmark_suite.py first")
    spans = extract_spans(str(adc), 1)

    mapping, reason = build_grid_mapping(spans, 32)
    if mapping:
        pytest.skip("this fixture no longer merges cells; nothing to assert")
    assert "merged" in reason

    r = corroborate_grid(
        register([field("DEEPPWD", 29, 29), field("ADVREGEN", 28, 28),
                  field("REST", 27, 0), field("TOP", 31, 30)]),
        spans,
    )
    assert r.status is GridStatus.UNAVAILABLE
    assert r.violations == []


def test_abstention_reason_explains_itself():
    """A bare UNAVAILABLE tells an operator nothing about what to fix."""
    adc = Path("benchmarks/suite/adc32/datasheet.pdf")
    if not adc.exists():
        pytest.skip("run scripts/make_benchmark_suite.py first")
    _, reason = build_grid_mapping(extract_spans(str(adc), 1), 32)
    if reason:
        assert "cannot be trusted" in reason or "incomplete" in reason
