#!/usr/bin/env python3
"""The control group: what you get by just asking the model for a driver.

Any claim that verification earns its cost needs a baseline that is
*honest*, which means it must not be a straw man. So this baseline gets
every advantage short of the thing under test:

  * the same model, at the same DPI, on the same page image
  * the errata document too, in the same request
  * a prompt that explicitly asks for correct masks and for errata
    workarounds to be applied

The only thing withheld is SiliconTruth itself: no Z3 gate, no
width-conservation check, no closed constraint set, no Renode execution.
Whatever difference appears is attributable to verification rather than to
a weaker prompt or a worse model.

The output is a scorecard, not a verdict. Every number traces to
ground_truth.json, and the run is repeated --trials times because a single
sample of a stochastic system is an anecdote.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silicontruth.ingest.pdf_render import render_page
from silicontruth.models.provider import ProviderError, Truncated, get_provider

PROMPT = """You are given pages from a microcontroller reference manual and
its silicon errata document.

Write a C header and an init function for the register described, exactly
as an embedded engineer would need it. Requirements:

- Define the peripheral base address, the register offset, and a SHIFT and
  MASK macro for every bitfield.
- The masks must be correct for the bit positions shown in the manual.
- Apply any errata workaround that software is required to perform.
- The peripheral base address is 0x40011000.

Return C source only.
"""


_TOKEN = re.compile(r"0[xX][0-9a-fA-F]+|\d+|[A-Za-z_]\w*|<<|>>|[()|&+~-]")


def extract_macros(c: str) -> dict[str, int]:
    """Evaluate the #define bodies, rather than grabbing the first number.

    This matters more than it looks. The first version of this scorer read
    `#define EOBIE_MASK (0x1U << EOBIE_SHIFT)` as the value 0x1 and scored
    it wrong against 0x10000000 -- reporting the baseline at 5% when it was
    in fact emitting correct masks in the perfectly ordinary
    mask-then-shift idiom.

    A baseline measured with a broken scorer is not a baseline, it is a
    straw man, so this resolves macro references and evaluates the shift
    and bitwise operators the idiom actually uses.
    """
    bodies: dict[str, str] = {}
    for m in re.finditer(r"#define\s+(\w+)\s+([^\n\\]*)", c):
        bodies[m.group(1)] = m.group(2).strip()

    cache: dict[str, int | None] = {}

    def evaluate(name: str, depth: int = 0) -> int | None:
        if name in cache:
            return cache[name]
        if depth > 8 or name not in bodies:
            return None
        cache[name] = None  # guards against a cyclic #define
        expr_parts: list[str] = []
        for tok in _TOKEN.findall(bodies[name]):
            if re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", tok):
                expr_parts.append(tok)
            elif re.fullmatch(r"[A-Za-z_]\w*", tok):
                if tok.upper() in ("U", "UL", "ULL", "L"):
                    continue  # integer suffix that the tokenizer split off
                sub = evaluate(tok, depth + 1)
                if sub is None:
                    return None
                expr_parts.append(str(sub))
            else:
                expr_parts.append(tok)
        expr = " ".join(expr_parts)
        if not expr or not re.fullmatch(r"[0-9xXa-fA-F()<>|&+~\s-]+", expr):
            return None
        try:
            # Arithmetic only: the token filter above admits no names, no
            # calls and no attribute access, so there is nothing to execute.
            val = eval(expr, {"__builtins__": {}}, {})  # noqa: S307
        except Exception:
            return None
        if not isinstance(val, int):
            return None
        cache[name] = val
        return val

    out: dict[str, int] = {}
    for name in bodies:
        v = evaluate(name)
        if v is not None:
            out[name] = v
    return out


def score(c_code: str, truth: dict) -> dict:
    macros = extract_macros(c_code)
    fields = [f for f in truth["fields"] if not f["reserved"]]

    correct, wrong, missing = [], [], []
    for f in fields:
        want = ((1 << (f["msb"] - f["lsb"] + 1)) - 1) << f["lsb"]
        # Accept any macro whose name ends in the field name + _MASK.
        got = None
        for name, val in macros.items():
            if name.upper().endswith(f"{f['name'].upper()}_MASK"):
                got = val
                break
        if got is None:
            missing.append(f["name"])
        elif got == want:
            correct.append(f["name"])
        else:
            wrong.append((f["name"], hex(got), hex(want)))

    errata_ids = [e["errata_id"] for e in truth["errata"] if e["must_link"]]
    cited = [e for e in errata_ids if e in c_code]

    # Does it even mention the delay the errata mandates?
    delay = bool(re.search(r"\b(nop|delay|__NOP|for\s*\(.*volatile)", c_code, re.I))

    return {
        "fields_total": len(fields),
        "mask_correct": len(correct),
        "mask_wrong": wrong,
        "mask_missing": missing,
        "errata_required": errata_ids,
        "errata_cited": cited,
        "has_delay_loop": delay,
        "chars": len(c_code),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="benchmarks/synthetic/synthetic_usart.pdf")
    ap.add_argument("--errata", default="benchmarks/synthetic/synthetic_errata.pdf")
    ap.add_argument("--truth", default="benchmarks/synthetic/ground_truth.json")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=16384)
    ap.add_argument("--out", default="benchmarks/synthetic/naive_baseline.json")
    args = ap.parse_args()

    truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))
    pages = []
    for path in (args.pdf, args.errata):
        rp = render_page(path, 1, dpi=args.dpi)
        pages.append("data:image/png;base64," + base64.b64encode(rp.png).decode())

    provider = get_provider()
    print(f"provider: {provider.capabilities.name}  trials: {args.trials}")
    print("(same model, same pages, errata included, no verification)\n")

    runs = []
    for i in range(args.trials):
        try:
            code = provider.complete_with_images(
                PROMPT, images=pages, max_tokens=args.max_tokens
            )
        except Truncated as e:
            print(f"  trial {i + 1}: TRUNCATED ({e})")
            runs.append({"trial": i + 1, "error": "truncated"})
            continue
        except ProviderError as e:
            print(f"  trial {i + 1}: ERROR {e}")
            runs.append({"trial": i + 1, "error": str(e)[:200]})
            continue

        s = score(code, truth)
        s["trial"] = i + 1
        s["code"] = code
        runs.append(s)
        print(
            f"  trial {i + 1}: masks {s['mask_correct']}/{s['fields_total']} correct, "
            f"{len(s['mask_wrong'])} wrong, {len(s['mask_missing'])} missing; "
            f"errata cited {len(s['errata_cited'])}/{len(s['errata_required'])}"
        )
        for name, got, want in s["mask_wrong"][:6]:
            print(f"        WRONG {name}: emitted {got}, correct {want}")
        if s["mask_missing"][:6]:
            print(f"        MISSING {s['mask_missing'][:6]}")

    ok = [r for r in runs if "error" not in r]
    if ok:
        tot = sum(r["fields_total"] for r in ok)
        cor = sum(r["mask_correct"] for r in ok)
        err = sum(len(r["errata_cited"]) for r in ok)
        req = sum(len(r["errata_required"]) for r in ok)
        print(f"\n  masks correct : {cor}/{tot} ({100 * cor / tot:.0f}%)")
        print(f"  errata cited  : {err}/{req} ({100 * err / req:.0f}%)")

        per_trial = {r["mask_correct"] for r in ok}
        errata_spread = {len(r["errata_cited"]) for r in ok}
        print()
        if cor == tot:
            print("  READ THIS BEFORE QUOTING THE NUMBER ABOVE.")
            print("  The baseline got every mask right on this page. That is the")
            print("  honest result, and it means this fixture does NOT demonstrate")
            print("  that verification improves accuracy on clean input. It should")
            print("  not be presented as if it did.")
            print()
        if len(errata_spread) > 1:
            print(f"  What it does show is variance: errata cited per trial "
                  f"{sorted(errata_spread)} on")
            print("  identical input. A run that silently omits a mandatory")
            print("  workaround is indistinguishable, from the output alone, from")
            print("  one that applied it -- and nothing in the naive path reports")
            print("  which kind of run you just had.")
        if len(per_trial) > 1:
            print(f"  Mask accuracy also varied across trials: {sorted(per_trial)}.")
        print()
        print("  The claim this project can defend is detectability, not raw")
        print("  accuracy: width conservation names a wrong bit before any code")
        print("  is generated, and the Renode oracle fails a driver that omits a")
        print("  workaround. Neither requires anyone to notice.")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps({"truth": args.truth, "runs": runs}, indent=2), encoding="utf-8"
    )
    print(f"\n  wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
