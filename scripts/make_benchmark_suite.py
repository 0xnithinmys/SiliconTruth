#!/usr/bin/env python3
"""Generate the synthetic benchmark suite into benchmarks/."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silicontruth.bench.suite import SUITE
from silicontruth.bench.synthetic import emit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="benchmarks/suite")
    args = ap.parse_args()
    out = Path(args.out)

    for spec in SUITE:
        paths = emit(spec, out)
        nf = sum(len(r.fields) for r in spec.registers)
        ml = sum(1 for e in spec.errata if e.must_link)
        print(f"  {spec.slug:9s} {len(spec.registers)} reg, {nf:3d} fields, "
              f"{ml}/{len(spec.errata)} errata -> {paths['datasheet'].parent}")
    print(f"\n{len(SUITE)} chips written to {out}")
    print("SYNTHETIC. Drawn by this project; not evidence about real silicon.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
