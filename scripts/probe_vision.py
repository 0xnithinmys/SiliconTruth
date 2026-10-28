#!/usr/bin/env python3
"""Measure what the model actually reads off a rendered datasheet page.

Answers the question Stage 3 rests on: can muse-spark read a 32-bit
bitfield grid out of a page image accurately enough to be worth
verifying? Scored against benchmarks/synthetic/ground_truth.json, so the
answer is a number, not an impression.

Reports three things separately, because they fail for different reasons
and have different fixes:
  * accepted   -- did the endpoint take an image at all
  * exact      -- fields whose name, msb and lsb all match ground truth
  * z3_ready   -- do the returned widths sum to the register width
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silicontruth.ingest.pdf_render import render_page
from silicontruth.models.provider import ProviderError, Truncated, get_provider

SCHEMA = {
    "type": "object",
    "properties": {
        "register_name": {"type": "string"},
        "offset_hex": {"type": "string"},
        "reset_value_hex": {"type": "string"},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "msb": {"type": "integer"},
                    "lsb": {"type": "integer"},
                    "reserved": {"type": "boolean"},
                },
                "required": ["name", "msb", "lsb", "reserved"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["register_name", "offset_hex", "reset_value_hex", "fields"],
    "additionalProperties": False,
}

PROMPT = """This image is one page of a microcontroller reference manual.

Read the register description. Report every bitfield of the register.

Rules you must follow exactly:
- Use the bit-position grid at the top of the page as the authoritative
  source for which bits belong to which field. The grid has two banks:
  bits 31..16 and bits 15..0.
- A field spanning several cells (the same name repeated across adjacent
  cells) is ONE field. Report its highest bit as msb and its lowest as lsb.
- A single-bit field has msb == lsb.
- Cells marked "Res." are reserved. Group adjacent reserved cells into one
  field and set reserved=true.
- Report offset_hex and reset_value_hex exactly as printed on the page.
- Do NOT compute addresses or masks. Report only what is printed.
- Every bit from 0 to 31 must be covered exactly once.
"""


def score(got: dict, truth: dict) -> dict:
    tf = {
        (f["name"], f["msb"], f["lsb"])
        for f in truth["fields"]
        if not f["reserved"]
    }
    gf = {
        (f["name"], f["msb"], f["lsb"])
        for f in got.get("fields", [])
        if not f.get("reserved")
    }
    width_sum = sum(
        f["msb"] - f["lsb"] + 1 for f in got.get("fields", []) if "msb" in f
    )
    reg_w = truth["register"]["width"]
    return {
        "truth_fields": len(tf),
        "returned_fields": len(got.get("fields", [])),
        "exact": len(tf & gf),
        "missed": sorted(tf - gf),
        "spurious": sorted(gf - tf),
        "width_sum": width_sum,
        "z3_ready": width_sum == reg_w,
        "offset_ok": got.get("offset_hex", "").replace(" ", "").lower()
        in ("0x00", "0x0", "0x0000"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="benchmarks/synthetic/synthetic_usart.pdf")
    ap.add_argument("--truth", default="benchmarks/synthetic/ground_truth.json")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--provider", default=None)
    args = ap.parse_args()

    truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))
    page = render_page(args.pdf, 1, dpi=args.dpi)
    uri = "data:image/png;base64," + base64.b64encode(page.png).decode()
    print(f"page: {page.width}x{page.height} @ {args.dpi} DPI, "
          f"{len(page.png)/1024:.0f} KiB PNG")

    provider = get_provider(args.provider)
    caps = provider.capabilities
    print(f"provider: {caps.name}  vision_model={caps.vision_model}")

    try:
        got = provider.extract(
            PROMPT, schema=SCHEMA, images=[uri], max_tokens=args.max_tokens
        )
    except Truncated as e:
        print(f"\nTRUNCATED: {e}\n  -> raise --max-tokens")
        return 2
    except ProviderError as e:
        print(f"\nREJECTED: {e}")
        return 3

    Path("docs/api-smoke").mkdir(parents=True, exist_ok=True)
    Path("docs/api-smoke/vision_probe.json").write_text(
        json.dumps(got, indent=2), encoding="utf-8"
    )

    s = score(got, truth)
    print(f"\n  register_name = {got.get('register_name')!r}")
    print(f"  offset_hex    = {got.get('offset_hex')!r}  ok={s['offset_ok']}")
    print(f"  reset_value   = {got.get('reset_value_hex')!r}")
    print(f"\n  exact fields  : {s['exact']}/{s['truth_fields']}")
    print(f"  returned      : {s['returned_fields']}")
    print(f"  width sum     : {s['width_sum']} (need "
          f"{truth['register']['width']})  z3_ready={s['z3_ready']}")
    if s["missed"]:
        print(f"  MISSED        : {s['missed']}")
    if s["spurious"]:
        print(f"  SPURIOUS      : {s['spurious']}")
    return 0 if s["exact"] == s["truth_fields"] and s["z3_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
