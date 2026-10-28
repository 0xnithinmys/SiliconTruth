"""Recover the bit-to-name mapping from the PDF's own text coordinates.

This closes the gap that name corroboration leaves open. Checking that a
name was PRINTED catches an invented field like `M1`. It does not catch
two real names swapped between two bit positions, because both appear on
the page.

The grid itself answers that. A register bitmap prints the bit number and
the field name in the same column, so the x-overlap between the digit row
and the name row *is* the mapping -- and it can be read from the text
layer with no model at all.

WHY THIS IS A CHECK AND NOT THE EXTRACTOR
=========================================
If the mapping can be recovered deterministically, the obvious question is
why a model is used at all. Because this only works on a vector-text PDF
laid out as a two-row grid. A scanned manual has no text layer, a
single-column register description has no grid, and vendors differ. The
model generalises; this does not. So this runs as corroboration where it
applies and reports UNAVAILABLE where it does not.

CONSERVATISM IS THE WHOLE DESIGN
================================
A layout heuristic that guesses wrong produces a FALSE FAILURE, which
blocks a correct read -- worse than the false negative this was written to
help with. So the reconstruction must be complete before it is trusted:
every bit of the register accounted for, exactly once. Anything less is
UNAVAILABLE, not FAIL.

That bar is not theoretical. On the committed fixture, `RXNEIE` and
`IDLEIE` are drawn a point smaller than their neighbours, which shifts
their glyph centres into a different row bucket. A naive implementation
silently loses them and then "discovers" that two fields are mislabelled.
Hence the y-tolerance band below, and the completeness requirement after
it.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field as dc_field
from enum import Enum

from silicontruth.ingest.pdf_render import TextSpan
from silicontruth.ir.schema import Register


class GridStatus(str, Enum):
    CORROBORATED = "corroborated"
    VIOLATIONS = "violations"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GridViolation:
    register: str
    bit: int
    detail: str

    def __str__(self) -> str:
        return f"[grid_corroboration] {self.register} bit {self.bit}: {self.detail}"


@dataclass
class GridResult:
    status: GridStatus
    violations: list[GridViolation] = dc_field(default_factory=list)
    mapping: dict[int, str] = dc_field(default_factory=dict)
    reason: str = ""

    @property
    def passed(self) -> bool:
        """UNAVAILABLE is not a pass, for the usual reason: a check that
        could not run has not been satisfied."""
        return self.status is GridStatus.CORROBORATED

    def summary(self) -> str:
        if self.status is GridStatus.UNAVAILABLE:
            return f"UNAVAILABLE: {self.reason}"
        if self.status is GridStatus.CORROBORATED:
            return f"PASS: {len(self.mapping)} bit(s) matched to the printed grid"
        return f"FAIL: {len(self.violations)} bit(s) disagree with the printed grid"


@dataclass(frozen=True)
class Cell:
    text: str
    x0: float
    x1: float

    @property
    def centre(self) -> float:
        return (self.x0 + self.x1) / 2.0


def _rows(spans: list[TextSpan], tolerance: float | None = None) -> list[list[TextSpan]]:
    """Bucket spans into visual rows with a tolerance band.

    Exact y-centre bucketing is what loses RXNEIE and IDLEIE: a one-point
    font difference moves the glyph centre enough to land in its own
    bucket. The band is derived from glyph height so it scales with the
    document rather than being a magic number.
    """
    if not spans:
        return []
    heights = [s.bbox[3] - s.bbox[1] for s in spans]
    band = tolerance if tolerance is not None else max(statistics.median(heights) * 0.6, 1.0)

    ordered = sorted(spans, key=lambda s: (s.bbox[1] + s.bbox[3]) / 2.0)
    out: list[list[TextSpan]] = []
    current: list[TextSpan] = [ordered[0]]
    ref = (ordered[0].bbox[1] + ordered[0].bbox[3]) / 2.0
    for s in ordered[1:]:
        c = (s.bbox[1] + s.bbox[3]) / 2.0
        if abs(c - ref) <= band:
            current.append(s)
        else:
            out.append(current)
            current = [s]
            ref = c
    out.append(current)
    return out


def _cells(row: list[TextSpan], gap_factor: float = 0.6) -> list[Cell]:
    """Split a row of characters into cells on horizontal gaps.

    PyMuPDF returns one span per character, so "DEATDEATDEAT" is twelve
    spans; the inter-cell gap is what separates one DEAT from the next.
    """
    if not row:
        return []
    items = sorted(row, key=lambda s: s.bbox[0])
    widths = [i.bbox[2] - i.bbox[0] for i in items]
    med = statistics.median(widths) if widths else 1.0

    groups: list[list[TextSpan]] = [[items[0]]]
    for prev, nxt in zip(items, items[1:]):
        if nxt.bbox[0] - prev.bbox[2] > med * gap_factor:
            groups.append([nxt])
        else:
            groups[-1].append(nxt)
    return [
        Cell("".join(c.text for c in g), g[0].bbox[0], g[-1].bbox[2])
        for g in groups
    ]


def _is_bit_row(cells: list[Cell], width: int) -> list[int] | None:
    """A row of consecutive descending bit numbers, or None.

    Requires at least 8 cells and strict descent by one, which no prose row
    satisfies by accident.
    """
    if len(cells) < 8:
        return None
    nums: list[int] = []
    for c in cells:
        t = c.text.strip()
        if not re.fullmatch(r"\d{1,2}", t):
            return None
        n = int(t)
        if n >= width:
            return None
        nums.append(n)
    if any(b - a != -1 for a, b in zip(nums, nums[1:])):
        return None
    return nums


def _name_for(cells: list[Cell], x0: float, x1: float) -> str | None:
    """The name cell whose horizontal span best overlaps this bit column."""
    best, best_overlap = None, 0.0
    for c in cells:
        overlap = min(x1, c.x1) - max(x0, c.x0)
        if overlap > best_overlap:
            best, best_overlap = c, overlap
    if best is None or best_overlap <= 0:
        return None
    return best.text.strip()


def build_grid_mapping(
    spans: list[TextSpan], width: int = 32
) -> tuple[dict[int, str], str]:
    """Read bit -> printed name out of the page's coordinates.

    Returns (mapping, reason). An empty mapping always carries a reason, so
    a caller can say *why* the check did not run rather than merely that it
    did not.
    """
    if not spans:
        return {}, "no text layer on this page (scanned raster?)"

    rows = _rows(spans)
    celled = [_cells(r) for r in rows]

    mapping: dict[int, str] = {}
    for i, cells in enumerate(celled):
        bits = _is_bit_row(cells, width)
        if not bits:
            continue
        # The name row is the next row down that is not itself a bit row.
        for cand in celled[i + 1 : i + 3]:
            if _is_bit_row(cand, width):
                continue
            if not cand:
                continue
            if len(cand) < len(cells):
                # MERGED CELLS. Long names in narrow columns can sit so close
                # that the gap between two cells falls below the split
                # threshold, and the tokenizer returns them as one run --
                # observed on the ADC fixture, where DEEPPWD and ADVREGEN came
                # back as "DEEPPWDADVREGEN" and the check then reported two
                # false disagreements on a read that was entirely correct.
                #
                # The honest response is to abstain for this row rather than
                # guess which half belongs to which column. An incomplete
                # mapping makes the whole check UNAVAILABLE below, which is
                # advisory -- and that is the right outcome, because a false
                # FAILURE blocks working output while a missed catch only
                # leaves the other two gates to do their job.
                return {}, (
                    f"name cells ({len(cand)}) do not align with bit cells "
                    f"({len(cells)}); adjacent labels merged, so the column "
                    "mapping for this row cannot be trusted"
                )
            for bit, cell in zip(bits, cells):
                name = _name_for(cand, cell.x0, cell.x1)
                if name:
                    mapping[bit] = name
            break

    if not mapping:
        return {}, "no bit-number grid found on this page"
    missing = [b for b in range(width) if b not in mapping]
    if missing:
        # Incomplete means untrustworthy. Reporting a disagreement from a
        # partial reconstruction is how a layout heuristic blocks a correct
        # read, which is worse than the false negative it was meant to help.
        return {}, (
            f"grid reconstruction incomplete: {len(missing)} of {width} bits "
            f"not located (first missing: {missing[0]})"
        )
    return mapping, ""


def _normalise(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def corroborate_grid(
    register: Register, spans: list[TextSpan], *, width: int | None = None
) -> GridResult:
    """Check the register's bit->name assignment against the printed grid."""
    w = width or register.width
    mapping, reason = build_grid_mapping(spans, w)
    if not mapping:
        return GridResult(status=GridStatus.UNAVAILABLE, reason=reason)

    violations: list[GridViolation] = []
    for f in register.fields:
        if f.reserved:
            continue
        want = _normalise(f.name)
        for bit in range(f.lsb, f.msb + 1):
            printed = _normalise(mapping.get(bit, ""))
            if not printed:
                continue
            # Reserved cells print as "Res."; a non-reserved field claiming
            # such a bit is a genuine disagreement worth reporting.
            if printed != want:
                violations.append(
                    GridViolation(
                        register=register.name,
                        bit=bit,
                        detail=(
                            f"the page prints {mapping[bit]!r} in this column, "
                            f"but the field claiming it is {f.name!r}"
                        ),
                    )
                )
                break  # one report per field, not one per bit

    status = GridStatus.VIOLATIONS if violations else GridStatus.CORROBORATED
    return GridResult(status=status, violations=violations, mapping=mapping)
