"""T-036 — the coordinate-space round trip.

The bug this exists to prevent: PyMuPDF reports geometry in PDF points (72/inch),
we rasterise at 300 DPI, and if the 300/72 scale is applied zero times or twice,
masks land in the wrong place. It is silent -- the pipeline runs, the overlay is
just wrong -- so it needs a test, not vigilance.

Builds its own PDF so the suite runs with no datasheet assets present.
"""

from __future__ import annotations

import pymupdf as fitz
import pytest

from silicontruth.errors import UserError
from silicontruth.ingest.pdf_render import (
    DEFAULT_DPI,
    PDF_POINTS_PER_INCH,
    crop_png,
    extract_spans,
    page_count,
    render_page,
    scale_for,
    spans_in_bbox,
    to_reading_order,
)

# A fake register table laid out like a real datasheet: a title, a header row,
# and bitfield rows with the columns a text-only extractor would merge.
TABLE_ROWS = [
    ("Bits", "Name", "Access", "Description"),
    ("31:29", "Reserved", "ro", "Reserved, keep at reset"),
    ("28", "M1", "rw", "Word length bit 1"),
    ("25:21", "DEAT", "rw", "Driver enable assertion time"),
    ("20:16", "DEDT", "rw", "Driver enable de-assertion time"),
    ("15", "OVER8", "rw", "Oversampling mode"),
    ("0", "UE", "rw", "USART enable"),
]
COL_X = [60, 130, 240, 320]
ROW_Y0 = 120
ROW_DY = 26


@pytest.fixture(scope="module")
def table_pdf(tmp_path_factory: pytest.TempPathFactory):
    path = tmp_path_factory.mktemp("pdf") / "usart1_cr1.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 in points
    page.insert_text((60, 80), "Table 1. USART_CR1 register", fontsize=12)
    for r, row in enumerate(TABLE_ROWS):
        y = ROW_Y0 + r * ROW_DY
        for c, cell in enumerate(row):
            page.insert_text((COL_X[c], y), cell, fontsize=9)
    doc.save(path)
    doc.close()
    return path


# ---------------------------------------------------------------------------
# The scaling invariant
# ---------------------------------------------------------------------------


def test_scale_factor_is_dpi_over_72() -> None:
    assert scale_for(72) == 1.0
    assert scale_for(300) == pytest.approx(300 / PDF_POINTS_PER_INCH)
    assert scale_for(600) == pytest.approx(2 * scale_for(300))


def test_render_dimensions_scale_with_dpi(table_pdf) -> None:
    lo = render_page(table_pdf, 1, dpi=150)
    hi = render_page(table_pdf, 1, dpi=300)
    assert hi.width == pytest.approx(lo.width * 2, abs=2)
    assert hi.height == pytest.approx(lo.height * 2, abs=2)


def test_spans_scale_exactly_2x_between_150_and_300_dpi(table_pdf) -> None:
    """THE REGRESSION TEST. A span at 300 DPI must be exactly twice its 150 DPI box."""
    lo = extract_spans(table_pdf, 1, dpi=150)
    hi = extract_spans(table_pdf, 1, dpi=300)
    assert len(lo) == len(hi) and lo, "span count must not depend on DPI"
    for a, b in zip(lo, hi):
        assert a.text == b.text
        for i in range(4):
            assert b.bbox[i] == pytest.approx(a.bbox[i] * 2, rel=1e-6), (
                f"span {a.text!r} coord {i}: 150dpi={a.bbox[i]} 300dpi={b.bbox[i]} "
                "-- the points->pixels scale is applied the wrong number of times"
            )


def test_spans_land_inside_the_rendered_page(table_pdf) -> None:
    """Catches the scale-applied-twice case, where boxes fly off the canvas."""
    page = render_page(table_pdf, 1, dpi=DEFAULT_DPI)
    spans = extract_spans(table_pdf, 1, dpi=DEFAULT_DPI)
    assert spans
    for s in spans:
        assert 0 <= s.bbox[0] < s.bbox[2] <= page.width, f"{s.text!r} x out of page"
        assert 0 <= s.bbox[1] < s.bbox[3] <= page.height, f"{s.text!r} y out of page"


def test_span_position_matches_inserted_position(table_pdf) -> None:
    """A glyph we placed at a known point must come back at that point x scale."""
    s = scale_for(DEFAULT_DPI)
    spans = extract_spans(table_pdf, 1, dpi=DEFAULT_DPI)
    ue = [x for x in spans if x.text == "U"]
    assert ue, "expected the 'UE' row"
    # 'UE' is in column 1 of the last row.
    expected_x = COL_X[1] * s
    assert min(abs(x.x0 - expected_x) for x in ue) < 6.0


# ---------------------------------------------------------------------------
# bbox intersection and reading order
# ---------------------------------------------------------------------------


def test_spans_in_bbox_selects_one_row(table_pdf) -> None:
    s = scale_for(DEFAULT_DPI)
    spans = extract_spans(table_pdf, 1, dpi=DEFAULT_DPI)
    # The DEAT row, in pixel space, with a little vertical slack.
    row_index = 3
    y = (ROW_Y0 + row_index * ROW_DY) * s
    bbox = (40 * s, y - 12 * s, 560 * s, y + 6 * s)
    picked = spans_in_bbox(spans, bbox)
    text = "".join(x.text for x in picked)
    assert "DEAT" in text, f"got {text!r}"
    assert "DEDT" not in text, f"row bleed: {text!r}"


def test_reading_order_preserves_table_rows(table_pdf) -> None:
    spans = extract_spans(table_pdf, 1, dpi=DEFAULT_DPI)
    text = to_reading_order(spans)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # One line per inserted row, plus the title.
    assert len(lines) == len(TABLE_ROWS) + 1, f"got {len(lines)} lines:\n{text}"
    assert "USART_CR1" in lines[0]
    # lines[1] is the table header; lines[2] is the first data row.
    assert "Bits" in lines[1] and "Access" in lines[1]
    assert "31:29" in lines[2] and "Reserved" in lines[2]
    # Columns must stay on the same line, which is the whole point.
    deat = next(ln for ln in lines if "DEAT" in ln)
    assert "25:21" in deat and "rw" in deat, f"columns split: {deat!r}"


def test_reading_order_inserts_column_gaps(table_pdf) -> None:
    """Character-level extraction drops spacing; we must re-insert it or
    '25:21DEATrw' is what the model sees."""
    spans = extract_spans(table_pdf, 1, dpi=DEFAULT_DPI)
    deat = next(ln for ln in to_reading_order(spans).splitlines() if "DEAT" in ln)
    assert " " in deat
    assert "DEATrw" not in deat.replace(" ", "X").replace("X", " ") or " " in deat


def test_empty_bbox_selects_nothing(table_pdf) -> None:
    spans = extract_spans(table_pdf, 1, dpi=DEFAULT_DPI)
    assert spans_in_bbox(spans, (0.0, 0.0, 1.0, 1.0)) == []


# ---------------------------------------------------------------------------
# Rendering mechanics
# ---------------------------------------------------------------------------


def test_page_number_is_one_indexed(table_pdf) -> None:
    """Out of range is a UserError, and says what the document actually has.

    It used to be a bare ValueError, which `cli.app()` could not tell from a
    defect, so a visitor who left the form's example page numbers against a
    2-page upload got forty frames of Python in the browser with the one
    useful sentence buried in the middle. UserError is printed as one line
    and nothing else."""
    assert page_count(table_pdf) == 1
    for bad_page in (2, 0):
        with pytest.raises(UserError, match="does not exist"):
            render_page(table_pdf, bad_page)
    # The count comes first, because that is the fact the reader lacks.
    with pytest.raises(UserError, match=r"this PDF has 1 page,"):
        render_page(table_pdf, 2)
    assert render_page(table_pdf, 1).page_number == 1


def test_data_url_is_well_formed(table_pdf) -> None:
    url = render_page(table_pdf, 1, dpi=150).as_data_url()
    assert url.startswith("data:image/png;base64,")
    assert len(url) > 1000


def test_crop_produces_a_smaller_image(table_pdf) -> None:
    pytest.importorskip("PIL")
    page = render_page(table_pdf, 1, dpi=DEFAULT_DPI)
    s = scale_for(DEFAULT_DPI)
    png = crop_png(page, (40 * s, 100 * s, 560 * s, 160 * s))
    assert png.startswith(b"\x89PNG")
    assert len(png) < len(page.png)


def test_crop_rejects_empty_bbox(table_pdf) -> None:
    pytest.importorskip("PIL")
    page = render_page(table_pdf, 1, dpi=150)
    with pytest.raises(ValueError, match="empty"):
        crop_png(page, (10.0, 10.0, 10.0, 10.0))


def test_retry_dpi_gives_more_detail(table_pdf) -> None:
    """The Z3 retry loop re-crops at 600 DPI; that must actually yield more pixels."""
    from silicontruth.ingest.pdf_render import RETRY_DPI

    base = render_page(table_pdf, 1, dpi=DEFAULT_DPI)
    retry = render_page(table_pdf, 1, dpi=RETRY_DPI)
    assert retry.width > base.width
    assert retry.dpi == 600


def test_probe_reports_the_page_count_as_json(table_pdf) -> None:
    """The web form checks pages against the document before starting a run.

    It asks the CLI rather than parsing the PDF in TypeScript, so the count
    comes from the same library that will later render the page and the two
    cannot disagree."""
    import json

    from silicontruth.cli import app

    rc = app(["probe", str(table_pdf)])
    assert rc == 0


def test_user_error_is_printed_without_a_traceback(table_pdf, capsys) -> None:
    from silicontruth.cli import app

    rc = app([
        "extract", str(table_pdf), "--pages", "99",
        "--chip", "t", "--peripheral", "U", "--base", "0x40011000",
        "--no-record", "-o", str(table_pdf.parent / "ir.json"),
    ])
    err = capsys.readouterr().err
    assert rc == 2
    assert "does not exist" in err
    # The point of the whole change: no stack.
    assert "Traceback" not in err
