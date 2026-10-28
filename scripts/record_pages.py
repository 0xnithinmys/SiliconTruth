#!/usr/bin/env python3
"""Record page images and region boxes into a replay fixture.

The UI needs to show the page a value was read from, with the region
highlighted. That needs the page itself, and a real reference manual
cannot be committed or deployed -- it is copyrighted. The synthetic suite
is drawn by this project, so its pages CAN ship, which is what makes a
working evidence pane possible at all in a keyless demo.

Deliberately writes PNGs rather than shipping the PDF for pdf.js to
render. The plan called for a pdf.js canvas; a pre-rendered PNG is a
fraction of the client bundle, renders identically, needs no worker
plumbing, and -- the point for this project -- is the EXACT raster the
model was shown. A pdf.js canvas would re-rasterise at some other
resolution, so a box that lines up in the UI would not prove the box lined
up for the model. The deviation is recorded in the README.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silicontruth.ingest.pdf_render import render_page
from silicontruth.ir.schema import PeripheralIR


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--chip", required=True)
    ap.add_argument("--ir", type=Path, default=None,
                    help="IR whose provenance supplies the region boxes")
    ap.add_argument("--pages", type=int, nargs="+", default=[1])
    ap.add_argument("--dpi", type=int, default=150,
                    help="must match the dpi the boxes were measured at")
    ap.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    args = ap.parse_args()

    out = args.fixtures / args.chip / "pages"
    out.mkdir(parents=True, exist_ok=True)

    # Region boxes come from the IR's provenance, which is filled in Python
    # from crop metadata -- never from the model. The UI is therefore
    # highlighting where we actually looked, not where something claimed to
    # have looked.
    regions: dict[int, list[dict]] = {}
    if args.ir and args.ir.exists():
        ir = PeripheralIR.model_validate_json(args.ir.read_text(encoding="utf-8"))
        for reg in ir.registers:
            p = reg.provenance
            regions.setdefault(p.page, []).append({
                "register": reg.name,
                "bbox": list(p.bbox),
                "mask_id": p.mask_id,
                "verified": reg.verified,
                "fields": len(reg.fields),
            })

    index = {"schema": 1, "chip": args.chip, "dpi": args.dpi, "pages": []}
    for page_no in args.pages:
        page = render_page(args.pdf, page_no, dpi=args.dpi)
        name = f"p{page_no}.png"
        (out / name).write_bytes(page.png)

        # A whole-page read has a provenance box covering the whole page,
        # which is true and useless as a highlight: a rectangle around
        # everything points at nothing. Flag it so the UI can say "read from
        # the whole page" instead of drawing a border and implying it
        # localised something it did not.
        page_area = page.width * page.height
        marked = []
        for r in regions.get(page_no, []):
            x0, y0, x1, y1 = r["bbox"]
            coverage = ((x1 - x0) * (y1 - y0)) / page_area if page_area else 0.0
            marked.append({**r, "whole_page": coverage > 0.9,
                           "coverage": round(coverage, 3)})

        index["pages"].append({
            "page": page_no,
            "image": f"pages/{name}",
            "width": page.width,
            "height": page.height,
            "regions": marked,
        })
        localised = sum(1 for r in marked if not r["whole_page"])
        whole = len(marked) - localised
        note = f"{localised} region(s)"
        if whole:
            note += f", {whole} whole-page read(s)"
        print(f"  p.{page_no}  {page.width}x{page.height}  "
              f"{len(page.png) / 1024:.0f} KiB  {note}")

    (args.fixtures / args.chip / "pages.json").write_text(
        json.dumps(index, indent=2), encoding="utf-8"
    )
    print(f"  -> {args.fixtures / args.chip / 'pages.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
