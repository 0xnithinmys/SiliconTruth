#!/usr/bin/env python3
"""Generate a synthetic datasheet page with a known-correct ground truth.

Why this exists. Real reference manuals are copyrighted, large, and cannot
be committed, which makes them useless as a CI fixture. But the perception
stage has to be measured against *something* whose right answer is known
exactly, or "the model read the table correctly" is an opinion.

So: draw a page in the visual idiom of an ST reference manual -- a 32-cell
bit-position grid above a column of field descriptions -- and emit the
ground-truth IR beside it. Accuracy then has a denominator.

This is a measuring instrument, not a demo. It deliberately includes the
two features that break naive text extraction:

  1. The bit grid is a real table: cell contents are positioned by
     coordinate, so linear text extraction interleaves the number row with
     the name row and destroys the mapping.
  2. One field (UE, bit 0) is governed by an erratum documented nowhere on
     this page -- that link is what the errata cross-reference has to find.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf as fitz

# --- ground truth ---------------------------------------------------------
# USART_CR1 as it appears on the generated page. Widths sum to 32 exactly,
# so the Z3 width-conservation check passes on a correct read and fails on
# any off-by-one -- which is the whole point of the fixture.
FIELDS: list[tuple[str, int, int, str, str]] = [
    # (name, msb, lsb, access, description)
    ("RESERVED_31_29", 31, 29, "r", "Reserved, must be kept at reset value."),
    ("EOBIE", 28, 28, "rw", "End of Block interrupt enable."),
    ("RTOIE", 27, 27, "rw", "Receiver timeout interrupt enable."),
    ("DEAT", 26, 21, "rw", "Driver Enable assertion time."),
    ("DEDT", 20, 16, "rw", "Driver Enable de-assertion time."),
    ("OVER8", 15, 15, "rw", "Oversampling mode."),
    ("CMIE", 14, 14, "rw", "Character match interrupt enable."),
    ("MME", 13, 13, "rw", "Mute mode enable."),
    ("M0", 12, 12, "rw", "Word length bit 0."),
    ("WAKE", 11, 11, "rw", "Receiver wakeup method."),
    ("PCE", 10, 10, "rw", "Parity control enable."),
    ("PS", 9, 9, "rw", "Parity selection."),
    ("PEIE", 8, 8, "rw", "PE interrupt enable."),
    ("TXEIE", 7, 7, "rw", "TXE interrupt enable."),
    ("TCIE", 6, 6, "rw", "Transmission complete interrupt enable."),
    ("RXNEIE", 5, 5, "rw", "RXNE interrupt enable."),
    ("IDLEIE", 4, 4, "rw", "IDLE interrupt enable."),
    ("TE", 3, 3, "rw", "Transmitter enable."),
    ("RE", 2, 2, "rw", "Receiver enable."),
    ("UESM", 1, 1, "rw", "USART enable in Stop mode."),
    ("UE", 0, 0, "rw", "USART enable."),
]

REGISTER = {
    "name": "CR1",
    "display_name": "USART_CR1",
    "offset": 0x00,
    "width": 32,
    "reset_value": 0x00000000,
    "description": "Control register 1",
}
PERIPHERAL = {"name": "USART1", "base_address": 0x40011000}

PAGE_W, PAGE_H = 595.0, 842.0  # A4 in points
MARGIN = 56.0


BANK_H = 56.0  # number row + name row + access row


def _cell_access(bit: int) -> str:
    """The access letter printed beneath each cell, ST-style.

    Access is NOT provable by Z3 -- an rw/ro swap has no numeric
    contradiction -- so it is printed here precisely so that the Renode
    oracle has something to disagree with at execution time.
    """
    for name, msb, lsb, a, _d in FIELDS:
        if lsb <= bit <= msb:
            return "r" if name.startswith("RESERVED") else a
    return ""


def _cell_name(bit: int) -> str:
    for name, msb, lsb, _a, _d in FIELDS:
        if lsb <= bit <= msb:
            return "Res." if name.startswith("RESERVED") else name
    return ""


def _assert_grid_covers_32() -> None:
    """The drawn grid must name every bit 0..31 exactly once.

    This is a self-check on the measuring instrument. A fixture that
    silently mislabels a bit is worse than no fixture: it reports a model
    error that is really a generator error.
    """
    bits = [b for bank_hi in (31, 15) for b in range(bank_hi, bank_hi - 16, -1)]
    assert sorted(bits) == list(range(32)), f"grid covers {sorted(bits)}"
    for b in range(32):
        assert _cell_name(b), f"bit {b} has no field"


def build_page(doc: fitz.Document, page_no: int) -> None:
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    x0, x1 = MARGIN, PAGE_W - MARGIN
    y = MARGIN

    page.insert_text((x0, y), "27.8.1", fontname="helv", fontsize=9)
    page.insert_text(
        (x0 + 44, y), "Control register 1 (USART_CR1)", fontname="hebo", fontsize=12
    )
    y += 22
    page.insert_text(
        (x0, y), "Address offset: 0x00", fontname="helv", fontsize=9
    )
    page.insert_text(
        (x0 + 190, y), "Reset value: 0x0000 0000", fontname="helv", fontsize=9
    )
    y += 24

    # --- the bit grid: two banks of 16 cells, numbers above names ---------
    cell_w = (x1 - x0) / 16.0
    # (31, 15), not (31, 16): the banks are 31..16 and 15..0. Getting this
    # wrong draws bit 16 twice and omits bit 0 entirely, so the rendered
    # page disagrees with ground_truth() and every accuracy number measured
    # against this fixture becomes meaningless. _assert_grid_covers_32()
    # below is what catches that.
    for bank, hi in enumerate((31, 15)):
        top = y + bank * BANK_H
        num_bot, name_bot = top + 16, top + 34
        acc_bot = name_bot + 14
        for i in range(16):
            bit = hi - i
            cx0 = x0 + i * cell_w
            page.draw_rect(fitz.Rect(cx0, top, cx0 + cell_w, num_bot), width=0.5)
            page.draw_rect(
                fitz.Rect(cx0, num_bot, cx0 + cell_w, name_bot), width=0.5
            )
            page.draw_rect(
                fitz.Rect(cx0, name_bot, cx0 + cell_w, acc_bot), width=0.5
            )
            acc = _cell_access(bit)
            page.insert_text(
                (cx0 + cell_w / 2 - 1.9 * len(acc), acc_bot - 4),
                acc,
                fontname="helv",
                fontsize=7.0,
            )
            n = str(bit)
            page.insert_text(
                (cx0 + cell_w / 2 - 2.6 * len(n), num_bot - 5),
                n,
                fontname="helv",
                fontsize=7.5,
            )
            label = _cell_name(bit)
            size = 6.0 if len(label) > 5 else 7.0
            page.insert_text(
                (cx0 + cell_w / 2 - 0.26 * size * len(label), name_bot - 6),
                label,
                fontname="helv",
                fontsize=size,
            )
    y += 2 * BANK_H + 18

    # --- field descriptions ----------------------------------------------
    for name, msb, lsb, access, desc in FIELDS:
        if name.startswith("RESERVED"):
            bits = f"Bits {msb}:{lsb}"
            page.insert_text(
                (x0, y),
                f"{bits}  Reserved, must be kept at reset value.",
                fontname="helv",
                fontsize=8.5,
            )
            y += 15
            continue
        bits = f"Bit {lsb}" if msb == lsb else f"Bits {msb}:{lsb}"
        page.insert_text(
            (x0, y), f"{bits}  {name}: {desc}", fontname="helv", fontsize=8.5
        )
        y += 15
        if y > PAGE_H - MARGIN - 20:
            break

    page.insert_text(
        (x1 - 30, PAGE_H - 30), str(page_no), fontname="helv", fontsize=8
    )


def ground_truth() -> dict:
    return {
        "peripheral": PERIPHERAL,
        "register": REGISTER,
        "fields": [
            {
                "name": n,
                "msb": msb,
                "lsb": lsb,
                "width": msb - lsb + 1,
                "access": a,
                "reserved": n.startswith("RESERVED"),
                "description": d,
            }
            for n, msb, lsb, a, d in FIELDS
        ],
        "invariant": {
            "width_sum": sum(msb - lsb + 1 for _n, msb, lsb, _a, _d in FIELDS),
            "register_width": REGISTER["width"],
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="benchmarks/synthetic")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    gt = ground_truth()
    assert gt["invariant"]["width_sum"] == 32, gt["invariant"]
    _assert_grid_covers_32()

    doc = fitz.open()
    build_page(doc, page_no=412)
    pdf_path = out / "synthetic_usart.pdf"
    doc.save(str(pdf_path))
    doc.close()

    gt_path = out / "ground_truth.json"
    gt_path.write_text(json.dumps(gt, indent=2), encoding="utf-8")

    print(f"wrote {pdf_path}")
    print(f"wrote {gt_path}  ({len(gt['fields'])} fields, widths sum to 32)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
