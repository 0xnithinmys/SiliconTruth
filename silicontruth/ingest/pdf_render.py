"""T-034/T-035 — PDF rasterisation and coordinate-anchored text extraction.

THE COORDINATE-SPACE TRAP
-------------------------
PyMuPDF reports text geometry in PDF *points* (72 per inch). We rasterise at
RENDER_DPI (300 by default). Those are different spaces, and mixing them is the
classic bug in this pipeline: masks land a quarter of the way up the page.

Every function here is explicit about which space it returns, and
`SCALE = dpi / 72` is applied exactly once, at the boundary. Provenance bboxes
are always stored in RENDER_DPI pixel space, matching what SAM sees and what the
browser overlay draws.

WHY WE SEND BOTH THE CROP AND THE TEXT SPANS
--------------------------------------------
The image preserves table structure that text extraction destroys. The text spans
preserve exact glyphs that OCR would corrupt. Either alone is lossy; together they
let the model read a register table without inventing digits.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz

from silicontruth.errors import UserError

PDF_POINTS_PER_INCH = 72.0
DEFAULT_DPI = 300
RETRY_DPI = 600

BBox = tuple[float, float, float, float]


def scale_for(dpi: int) -> float:
    """Points -> pixels at the given DPI. The single place this conversion lives."""
    return dpi / PDF_POINTS_PER_INCH


@dataclass(frozen=True)
class TextSpan:
    """One run of text with its geometry in RENDER_DPI pixel space."""

    text: str
    bbox: BBox  # pixel space, not points
    size: float  # font size in points (unscaled; relative comparisons only)

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


@dataclass(frozen=True)
class RenderedPage:
    page_number: int  # 1-indexed, matching how datasheets are cited
    dpi: int
    width: int
    height: int
    png: bytes

    def as_data_url(self) -> str:
        return "data:image/png;base64," + base64.b64encode(self.png).decode("ascii")

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.png)
        return path


def render_page(pdf: Path | str, page_number: int, dpi: int = DEFAULT_DPI) -> RenderedPage:
    """Rasterise one page. `page_number` is 1-indexed."""
    with fitz.open(pdf) as doc:
        if not 1 <= page_number <= doc.page_count:
            # UserError, not ValueError: asking for a page the document does
            # not have is a typo, and a traceback for it blames the tool. The
            # message leads with what the document actually is, because that
            # is the fact the reader does not have.
            raise UserError(
                f"this PDF has {doc.page_count} "
                f"page{'' if doc.page_count == 1 else 's'}, "
                f"so page {page_number} does not exist"
            )
        page = doc[page_number - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale_for(dpi), scale_for(dpi)))
        return RenderedPage(
            page_number=page_number,
            dpi=dpi,
            width=pix.width,
            height=pix.height,
            png=pix.tobytes("png"),
        )


def extract_spans(
    pdf: Path | str, page_number: int, dpi: int = DEFAULT_DPI
) -> list[TextSpan]:
    """Character-level text with geometry, scaled into RENDER_DPI pixel space.

    Uses rawdict so we get per-character boxes; dense register tables put several
    logical columns on one visual line, and span-level boxes merge them.
    """
    s = scale_for(dpi)
    spans: list[TextSpan] = []
    with fitz.open(pdf) as doc:
        page = doc[page_number - 1]
        raw = page.get_text("rawdict")
        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    for ch in span.get("chars", []):
                        x0, y0, x1, y1 = ch["bbox"]
                        if not ch["c"].strip():
                            continue
                        spans.append(
                            TextSpan(
                                text=ch["c"],
                                bbox=(x0 * s, y0 * s, x1 * s, y1 * s),
                                size=span.get("size", 0.0),
                            )
                        )
    return spans


def spans_in_bbox(spans: list[TextSpan], bbox: BBox) -> list[TextSpan]:
    """Spans whose centre falls inside bbox. Both must be in the same pixel space."""
    x0, y0, x1, y1 = bbox
    out = []
    for s in spans:
        cx = (s.bbox[0] + s.bbox[2]) / 2
        cy = (s.bbox[1] + s.bbox[3]) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            out.append(s)
    return out


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    n = len(ys)
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2


def to_reading_order(spans: list[TextSpan], *, row_tolerance: float | None = None) -> str:
    """Sort into rows then columns and join into readable text.

    Row bucketing tolerance defaults to half the median glyph height. Too tight
    and one table row shatters into three; too loose and two rows merge. Half the
    median height is the value that survives both 8pt footnotes and 14pt headers
    on the same page.
    """
    if not spans:
        return ""
    tol = row_tolerance if row_tolerance is not None else _median(
        [s.height for s in spans]
    ) * 0.5
    tol = max(tol, 1.0)

    rows: list[list[TextSpan]] = []
    for s in sorted(spans, key=lambda s: (s.y0, s.x0)):
        placed = False
        for row in rows:
            if abs(row[0].y0 - s.y0) <= tol:
                row.append(s)
                placed = True
                break
        if not placed:
            rows.append([s])

    lines = []
    for row in rows:
        row.sort(key=lambda s: s.x0)
        # Re-insert spacing the character-level extraction dropped: a gap wider
        # than half a glyph is a real separation, not kerning.
        buf: list[str] = []
        prev_x1: float | None = None
        for s in row:
            if prev_x1 is not None and s.x0 - prev_x1 > max(s.height * 0.4, 2.0):
                buf.append(" ")
            buf.append(s.text)
            prev_x1 = s.bbox[2]
        lines.append("".join(buf).rstrip())
    return "\n".join(lines)


def crop_png(page: RenderedPage, bbox: BBox) -> bytes:
    """Crop a rendered page to bbox (pixel space) and return PNG bytes."""
    from PIL import Image  # lazy: only needed when cropping

    img = Image.open(io.BytesIO(page.png))
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(page.width, x1), min(page.height, y1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"crop bbox {bbox} is empty against page {page.width}x{page.height}")
    out = io.BytesIO()
    img.crop((x0, y0, x1, y1)).save(out, format="PNG")
    return out.getvalue()


def page_count(pdf: Path | str) -> int:
    with fitz.open(pdf) as doc:
        return doc.page_count
