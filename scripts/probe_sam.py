#!/usr/bin/env python3
"""Learn what sam-3.1 actually returns for a real datasheet page.

The 1x1 transparent PNG probe in smoke_api.py proved the endpoint accepts
an image (images_processed: 1) but returned an empty output with empty
annotations -- correct for a blank pixel, and useless for learning the
mask format. This sends a real page and dumps the entire response, so the
segmentation stage is built against observed structure rather than a guess
about it.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from silicontruth.ingest.pdf_render import render_page
from silicontruth.models.provider import load_env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="benchmarks/suite/uart32/datasheet.pdf")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--prompt", default="table")
    ap.add_argument("--out", default="docs/api-smoke/sam_real.json")
    args = ap.parse_args()

    env = load_env()
    key = env.get("MODEL_API_KEY", "")
    base = env.get("META_API_BASE", "https://api.meta.ai/v1")
    model = env.get("SAM_MODEL", "sam-3.1")
    if not key:
        print("no MODEL_API_KEY")
        return 2

    page = render_page(args.pdf, args.page, dpi=args.dpi)
    uri = "data:image/png;base64," + base64.b64encode(page.png).decode()
    print(f"page {page.width}x{page.height} @ {args.dpi} dpi, "
          f"{len(page.png) / 1024:.0f} KiB; prompt={args.prompt!r}")

    client = httpx.Client(
        base_url=base,
        timeout=httpx.Timeout(180.0, connect=20.0),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        follow_redirects=True,
    )
    payload = {
        "model": model,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": uri},
                {"type": "input_text", "text": args.prompt},
            ],
        }],
    }
    r = client.post("/responses", json=payload)
    print(f"HTTP {r.status_code}  {len(r.text)} bytes")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(r.text, encoding="utf-8")

    if r.status_code != 200:
        print(r.text[:800])
        return 1

    body = r.json()
    print("top-level keys:", sorted(body))
    print("usage:", body.get("usage"))
    for item in body.get("output", []):
        print(f"\noutput item: type={item.get('type')} status={item.get('status')}")
        for c in item.get("content", []):
            print("  content type:", c.get("type"))
            txt = c.get("text")
            if txt:
                print("  text:", txt[:300])
            ann = c.get("annotations")
            print(f"  annotations: {len(ann) if ann is not None else 'None'}")
            if ann:
                print("  first annotation keys:", sorted(ann[0]))
                print("  first annotation:", json.dumps(ann[0])[:600])
    print(f"\nfull response saved to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
