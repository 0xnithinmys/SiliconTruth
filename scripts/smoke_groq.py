"""Smoke the Groq free tier and discover which Llama models are actually served.

The Meta Model API is billing-blocked (HTTP 402). Groq serves Llama -- a Meta
open-weight model, explicitly permitted by the hackathon -- on a free tier.

This script answers the three questions that decide whether the architecture
survives the substitution:
  1. Which Llama models does this key actually have access to?
  2. Is there one with VISION? (Stage 1 needs it to read register tables.)
  3. Is there one with LONG CONTEXT? (Errata cross-reference needs it.)

Reads .env directly. NEVER prints the key.

Run:  python scripts/smoke_groq.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
OUT_DIR = ROOT / "docs" / "api-smoke"

TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def load_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        sys.exit(f"missing {ENV_PATH}")
    env: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    if not env.get("GROQ_API_KEY"):
        sys.exit("GROQ_API_KEY is empty in .env")
    return env


def save(name: str, payload: object) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(
        json.dumps(payload, indent=2)[:200_000], encoding="utf-8"
    )


def main() -> int:
    env = load_env()
    base = env.get("GROQ_API_BASE", "https://api.groq.com/openai/v1")
    client = httpx.Client(
        base_url=base,
        timeout=httpx.Timeout(90.0, connect=20.0),
        headers={
            "Authorization": f"Bearer {env['GROQ_API_KEY']}",
            "Content-Type": "application/json",
        },
    )

    print(f"base: {base}")
    print(f"key:  loaded from .env ({len(env['GROQ_API_KEY'])} chars, not shown)\n")

    # ---- 1. what do we actually have? ------------------------------------
    r = client.get("/models")
    if r.status_code != 200:
        print(f"FAIL  GET /models -> HTTP {r.status_code}: {r.text[:300]}")
        return 1
    body = r.json()
    save("groq_models", body)
    models = [m.get("id", "") for m in body.get("data", [])]
    llama = sorted(m for m in models if "llama" in m.lower())

    print(f"PASS  GET /models -> {len(models)} models, {len(llama)} Llama\n")
    print("  Llama models available:")
    for m in llama:
        ctx = next(
            (x.get("context_window") for x in body["data"] if x.get("id") == m), "?"
        )
        print(f"    {str(ctx):>9}  ctx   {m}")
    # Safety classifiers are Meta-owned but useless for extraction: 512-token
    # context, classify-only. They do not count as a usable Llama.
    text_candidates = [
        m for m in llama if "guard" not in m.lower() and "prompt-guard" not in m.lower()
    ]
    if not text_candidates:
        print("\n" + "=" * 68)
        print("NO USABLE LLAMA ON THIS KEY.")
        print("  Meta-owned models present are prompt-guard safety classifiers")
        print("  (512-token context, classification only) -- not usable for")
        print("  register extraction.")
        non_meta = sorted(set(models) - set(llama))
        print(f"\n  The other {len(non_meta)} models are not Meta:")
        for m in non_meta:
            print(f"    {m}")
        print("\n  Using them would break the hackathon's 'built with Meta's")
        print("  models' requirement. Groq is not a viable substitution path.")
        return 1

    text_model = env.get("GROQ_TEXT_MODEL") or next(
        (m for m in text_candidates if "70b" in m or "versatile" in m),
        text_candidates[0],
    )
    print(f"\n  probing text: {text_model}")
    r = client.post(
        "/chat/completions",
        json={
            "model": text_model,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "max_tokens": 16,
        },
    )
    if r.status_code == 200:
        d = r.json()
        txt = d["choices"][0]["message"]["content"].strip()
        print(f"    PASS  reply={txt[:30]!r}  usage={d.get('usage', {})}")
    else:
        print(f"    FAIL  HTTP {r.status_code}: {r.text[:250]}")

    # ---- 3. structured output (the IR extractor depends on this) ---------
    print(f"\n  probing schema-locked JSON: {text_model}")
    r = client.post(
        "/chat/completions",
        json={
            "model": text_model,
            "messages": [
                {
                    "role": "user",
                    "content": "A register row reads: UE, bit 0. Return JSON with keys name, lsb, msb.",
                }
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 128,
        },
    )
    if r.status_code == 200:
        content = r.json()["choices"][0]["message"]["content"]
        try:
            print(f"    PASS  parsed={json.loads(content)}")
        except Exception:
            print(f"    FAIL  not JSON: {content[:150]!r}")
    else:
        print(f"    FAIL  HTTP {r.status_code}: {r.text[:250]}")

    # ---- 4. VISION -- the one that decides Stage 1 ------------------------
    vision_candidates = [
        m for m in llama if any(k in m.lower() for k in ("scout", "maverick", "vision", "4-"))
    ]
    print(f"\n  probing VISION candidates: {vision_candidates or '(none found by name)'}")
    vision_ok = None
    for m in vision_candidates or llama:
        r = client.post(
            "/chat/completions",
            json={
                "model": m,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "What colour is this image?"},
                            {"type": "image_url", "image_url": {"url": TINY_PNG}},
                        ],
                    }
                ],
                "max_tokens": 32,
            },
        )
        if r.status_code == 200:
            print(f"    PASS  {m} accepts image input")
            vision_ok = m
            break
        print(f"    no    {m} -> HTTP {r.status_code}: {r.text[:120]}")

    print("\n" + "=" * 68)
    if vision_ok:
        print(f"VISION MODEL: {vision_ok}")
        print("  -> Stage 1 (register table extraction) is viable on Groq.")
        print(f"  Set in .env:  GROQ_VISION_MODEL={vision_ok}")
    else:
        print("NO VISION MODEL REACHABLE on this key.")
        print("  -> Stage 1 needs a different source for table reading.")
    print(f"TEXT MODEL:   {text_model}")
    print(f"  Set in .env:  GROQ_TEXT_MODEL={text_model}")
    print("Raw responses in docs/api-smoke/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
