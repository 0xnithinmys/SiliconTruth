"""Draw synthetic datasheet pages with committed ground truth.

Real reference manuals are copyrighted and cannot be committed, which
makes them useless as a CI fixture and leaves accuracy claims with no
denominator. This module draws pages in the visual idiom of a vendor
reference manual and emits the exact ground-truth IR beside each one.

What it is NOT: evidence about real silicon. A synthetic page is drawn by
the same project that reads it, and nothing here substitutes for running
the pipeline on an actual manual. It is a regression instrument, and every
number derived from it is labelled synthetic wherever it is reported.

The suite deliberately varies the things that break perception:

  * register width (8, 16 and 32 bits), because the width-conservation
    check is parameterised by it and a 32-only suite never tests that
  * multi-column fields, whose repeated name across adjacent cells is the
    single most common misread
  * single-bit fields packed densely, where a one-column slip is invisible
    to arithmetic
  * reserved runs in the middle of a register, not only at the top
  * several registers per page, so page segmentation matters
  * errata that must NOT be linked, to catch an over-eager linker
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path

import pymupdf as fitz

PAGE_W, PAGE_H = 595.0, 842.0  # A4 in points
MARGIN = 56.0


@dataclass(frozen=True)
class FieldSpec:
    name: str
    msb: int
    lsb: int
    access: str = "rw"
    description: str = ""

    @property
    def reserved(self) -> bool:
        return self.name.upper().startswith("RESERVED")

    @property
    def width(self) -> int:
        return self.msb - self.lsb + 1


@dataclass(frozen=True)
class RegisterSpec:
    name: str          # e.g. "CR1"
    display: str       # e.g. "USART_CR1", as printed
    offset: int
    width: int         # 8, 16 or 32
    reset_value: int
    description: str
    fields: list[FieldSpec]

    def validate(self) -> None:
        """A fixture that disagrees with its own ground truth is worse than
        no fixture: it reports a model error that is really a drawing error."""
        assert self.width in (8, 16, 32), f"{self.name}: bad width {self.width}"
        covered: list[int] = []
        for f in self.fields:
            assert 0 <= f.lsb <= f.msb < self.width, f"{self.name}.{f.name}: range"
            covered.extend(range(f.lsb, f.msb + 1))
        assert sorted(covered) == list(range(self.width)), (
            f"{self.name}: fields cover {sorted(covered)}, "
            f"expected 0..{self.width - 1} exactly once"
        )
        assert self.reset_value < (1 << self.width), f"{self.name}: reset too wide"
        reserved_mask = 0
        for f in self.fields:
            if f.reserved:
                reserved_mask |= ((1 << f.width) - 1) << f.lsb
        assert not (self.reset_value & reserved_mask), (
            f"{self.name}: reset value sets reserved bits"
        )


@dataclass(frozen=True)
class ErratumSpec:
    errata_id: str
    title: str
    affected_register: str   # as printed, e.g. "USART_CR1"; "" if none
    constraint: str          # a member of ErrataConstraint, or "none"
    description: str
    workaround: str
    must_link: bool
    params: dict = dc_field(default_factory=dict)


@dataclass(frozen=True)
class ChipSpec:
    slug: str
    chip: str
    peripheral: str
    base_address: int
    registers: list[RegisterSpec]
    errata: list[ErratumSpec]
    section: str = "27.8"
    first_page: int = 412
    errata_page: int = 19

    def validate(self) -> None:
        assert self.registers, f"{self.slug}: no registers"
        offsets = [r.offset for r in self.registers]
        assert len(set(offsets)) == len(offsets), f"{self.slug}: duplicate offsets"
        for r in self.registers:
            r.validate()
        known = {r.display for r in self.registers}
        for e in self.errata:
            if e.must_link:
                assert e.affected_register in known, (
                    f"{self.slug}/{e.errata_id}: must_link but names "
                    f"{e.affected_register!r}, which is not a register here"
                )
                assert e.constraint != "none", (
                    f"{self.slug}/{e.errata_id}: must_link with constraint 'none'"
                )


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

def _cell_label(reg: RegisterSpec, bit: int) -> tuple[str, str]:
    for f in reg.fields:
        if f.lsb <= bit <= f.msb:
            return ("Res." if f.reserved else f.name), ("r" if f.reserved else f.access)
    return "", ""


def _bank_rows(width: int, per_row: int = 16) -> list[int]:
    """Top bit of each printed bank, high to low."""
    return list(range(width - 1, -1, -per_row))


def draw_register(page, reg: RegisterSpec, y: float, x0: float, x1: float) -> float:
    """Draw one register description. Returns the new y cursor."""
    page.insert_text((x0, y), f"{reg.display}", fontname="hebo", fontsize=11)
    y += 18
    page.insert_text(
        (x0, y),
        f"Address offset: 0x{reg.offset:02X}",
        fontname="helv",
        fontsize=8.5,
    )
    digits = reg.width // 4
    page.insert_text(
        (x0 + 170, y),
        f"Reset value: 0x{reg.reset_value:0{digits}X}",
        fontname="helv",
        fontsize=8.5,
    )
    y += 18

    per_row = 16 if reg.width >= 16 else 8
    cols = min(per_row, reg.width)
    cell_w = (x1 - x0) / cols
    for top_bit in _bank_rows(reg.width, per_row):
        num_bot = y + 14
        name_bot = num_bot + 15
        acc_bot = name_bot + 12
        for i in range(cols):
            bit = top_bit - i
            if bit < 0:
                break
            cx0 = x0 + i * cell_w
            for a, b in ((y, num_bot), (num_bot, name_bot), (name_bot, acc_bot)):
                page.draw_rect(fitz.Rect(cx0, a, cx0 + cell_w, b), width=0.5)
            n = str(bit)
            page.insert_text(
                (cx0 + cell_w / 2 - 2.4 * len(n), num_bot - 4),
                n, fontname="helv", fontsize=7.0,
            )
            label, acc = _cell_label(reg, bit)
            size = 5.6 if len(label) > 5 else 6.6
            page.insert_text(
                (cx0 + cell_w / 2 - 0.26 * size * len(label), name_bot - 5),
                label, fontname="helv", fontsize=size,
            )
            page.insert_text(
                (cx0 + cell_w / 2 - 1.8 * len(acc), acc_bot - 3),
                acc, fontname="helv", fontsize=6.6,
            )
        y = acc_bot + 6

    y += 6
    for f in reg.fields:
        bits = f"Bit {f.lsb}" if f.msb == f.lsb else f"Bits {f.msb}:{f.lsb}"
        text = (
            f"{bits}  Reserved, must be kept at reset value."
            if f.reserved
            else f"{bits}  {f.name}: {f.description}"
        )
        page.insert_text((x0, y), text, fontname="helv", fontsize=8.0)
        y += 12
    return y + 10


def _wrap(paragraphs: list[str], width: int) -> list[str]:
    lines: list[str] = []
    for para in paragraphs:
        cur = ""
        for word in para.split():
            if len(cur) + len(word) + 1 > width:
                lines.append(cur)
                cur = word
            else:
                cur = f"{cur} {word}".strip()
        lines.append(cur)
    return lines


def build_datasheet(spec: ChipSpec) -> fitz.Document:
    """One register per page, as dense manuals effectively are once a
    register's bit grid and field list are laid out."""
    doc = fitz.open()
    for i, reg in enumerate(spec.registers):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        x0, x1 = MARGIN, PAGE_W - MARGIN
        y = MARGIN
        page.insert_text(
            (x0, y), f"{spec.section}.{i + 1}", fontname="helv", fontsize=9
        )
        page.insert_text(
            (x0 + 46, y), reg.description, fontname="hebo", fontsize=12
        )
        y += 26
        draw_register(page, reg, y, x0, x1)
        page.insert_text(
            (x1 - 30, PAGE_H - 30), str(spec.first_page + i),
            fontname="helv", fontsize=8,
        )
    return doc


def build_errata(spec: ChipSpec) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    x0 = MARGIN
    y = MARGIN
    page.insert_text(
        (x0, y), "2  Description of device limitations",
        fontname="hebo", fontsize=12,
    )
    y += 26
    for e in spec.errata:
        page.insert_text(
            (x0, y), f"{e.errata_id}  {e.title}", fontname="hebo", fontsize=9.5
        )
        y += 14
        for line in _wrap(
            [f"Description: {e.description}", f"Workaround: {e.workaround}"], 95
        ):
            page.insert_text((x0 + 10, y), line, fontname="helv", fontsize=8.0)
            y += 11
        y += 7
        if y > PAGE_H - MARGIN - 40:
            break
    page.insert_text((x0, PAGE_H - 30), str(spec.errata_page),
                     fontname="helv", fontsize=8)
    return doc


def ground_truth(spec: ChipSpec) -> dict:
    return {
        "synthetic": True,
        "note": "Drawn by silicontruth.bench.synthetic. NOT evidence about "
                "real silicon.",
        "peripheral": {"name": spec.peripheral, "base_address": spec.base_address},
        "registers": [
            {
                "name": r.name,
                "display_name": r.display,
                "offset": r.offset,
                "width": r.width,
                "reset_value": r.reset_value,
                "page": spec.first_page + i,
                "pdf_page": i + 1,
                "fields": [
                    {
                        "name": f.name, "msb": f.msb, "lsb": f.lsb,
                        "width": f.width, "access": f.access,
                        "reserved": f.reserved, "description": f.description,
                    }
                    for f in r.fields
                ],
            }
            for i, r in enumerate(spec.registers)
        ],
        "errata": [
            {
                "errata_id": e.errata_id, "title": e.title,
                "affected_register": e.affected_register,
                "constraint": e.constraint, "params": e.params,
                "must_link": e.must_link,
            }
            for e in spec.errata
        ],
        "invariant": {
            "registers": len(spec.registers),
            "fields": sum(len(r.fields) for r in spec.registers),
            "errata_requiring_action": sum(1 for e in spec.errata if e.must_link),
        },
    }


def emit(spec: ChipSpec, out_dir: Path) -> dict[str, Path]:
    """Write the datasheet, the errata sheet and the ground truth."""
    spec.validate()
    d = out_dir / spec.slug
    d.mkdir(parents=True, exist_ok=True)

    import json

    ds = build_datasheet(spec)
    ds_path = d / "datasheet.pdf"
    ds.save(str(ds_path))
    ds.close()

    er_path = None
    if spec.errata:
        er = build_errata(spec)
        er_path = d / "errata.pdf"
        er.save(str(er_path))
        er.close()

    gt_path = d / "ground_truth.json"
    gt_path.write_text(json.dumps(ground_truth(spec), indent=2), encoding="utf-8")

    out = {"datasheet": ds_path, "ground_truth": gt_path}
    if er_path:
        out["errata"] = er_path
    return out
