"""T-012 — smoke every Meta model the pipeline depends on.

The highest-value 25 minutes in Phase 0. If sam-3.1 box prompts do not behave as
documented, Stage 1 needs rethinking, and we want to know that on Day 3 rather
than on Day 7.

Reads .env directly. NEVER prints the key, not even a prefix.

Run:  python scripts/smoke_api.py
      python scripts/smoke_api.py --only models,spark
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
OUT_DIR = ROOT / "docs" / "api-smoke"

TIMEOUT = httpx.Timeout(90.0, connect=20.0)


def load_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        sys.exit(f"missing {ENV_PATH}. Copy .env.example to .env and fill in MODEL_API_KEY.")
    env: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    if not env.get("MODEL_API_KEY"):
        sys.exit("MODEL_API_KEY is empty in .env")
    return env


def save(name: str, payload: object) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(
        json.dumps(payload, indent=2)[:200_000], encoding="utf-8"
    )


def report(name: str, ok: bool, detail: str) -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<28} {detail}")
    return ok


# ---------------------------------------------------------------------------


def check_models(client: httpx.Client, env: dict[str, str]) -> bool:
    try:
        r = client.get("/models")
    except Exception as e:
        return report("GET /models", False, f"{type(e).__name__}: {e}")
    if r.status_code != 200:
        return report("GET /models", False, f"HTTP {r.status_code}: {r.text[:200]}")

    body = r.json()
    save("models", body)
    items = body.get("data", body if isinstance(body, list) else [])
    ids = sorted(
        m.get("id", "") if isinstance(m, dict) else str(m) for m in items
    )
    wanted = [
        env.get("SPARK_MODEL", ""),
        env.get("SPARK_MODEL_FULL", ""),
        env.get("SAM_MODEL", ""),
        env.get("WONDER_MODEL", ""),
    ]
    missing = [w for w in wanted if w and w not in ids]
    ok = report("GET /models", True, f"{len(ids)} models")
    for i in ids[:40]:
        print(f"           - {i}")
    if missing:
        print(f"    !! pinned model IDs not listed: {missing}")
        print("       Update the *_MODEL vars in .env to real IDs before building.")
    return ok


def check_spark(client: httpx.Client, env: dict[str, str]) -> bool:
    model = env.get("SPARK_MODEL") or "muse-spark-1.3"
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Reply with exactly: OK"},
        ],
        "max_tokens": 16,
    }
    try:
        r = client.post("/chat/completions", json=payload)
    except Exception as e:
        return report(f"chat {model}", False, f"{type(e).__name__}: {e}")
    if r.status_code != 200:
        return report(f"chat {model}", False, f"HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    save("spark_chat", body)
    text = (
        body.get("choices", [{}])[0].get("message", {}).get("content", "")
        if body.get("choices")
        else ""
    )
    usage = body.get("usage", {})
    return report(f"chat {model}", True, f"reply={text.strip()[:30]!r} usage={usage}")


def check_structured(client: httpx.Client, env: dict[str, str]) -> bool:
    """The capability the whole IR extractor rests on: schema-locked JSON output."""
    model = env.get("SPARK_MODEL") or "muse-spark-1.3"
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "lsb": {"type": "integer"},
            "msb": {"type": "integer"},
        },
        "required": ["name", "lsb", "msb"],
        "additionalProperties": False,
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "A register table row reads: UE, bit 0. Return it as JSON.",
            }
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "bitfield", "schema": schema, "strict": True},
        },
        "max_tokens": 128,
    }
    try:
        r = client.post("/chat/completions", json=payload)
    except Exception as e:
        return report("structured output", False, f"{type(e).__name__}: {e}")
    if r.status_code != 200:
        return report(
            "structured output", False, f"HTTP {r.status_code}: {r.text[:300]}"
        )
    body = r.json()
    save("spark_structured", body)
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    try:
        parsed = json.loads(content)
    except Exception:
        return report("structured output", False, f"not JSON: {content[:120]!r}")
    return report("structured output", True, f"parsed={parsed}")


def check_sam(client: httpx.Client, env: dict[str, str]) -> bool:
    """THE CRITICAL ONE. If text-to-mask does not work as documented,
    Stage 1's design changes."""
    model = env.get("SAM_MODEL") or "sam-3.1"
    # 1x1 transparent PNG — we are probing the request shape and error surface,
    # not expecting a real detection.
    tiny_png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": tiny_png},
                    {"type": "input_text", "text": "table"},
                ],
            }
        ],
    }
    try:
        r = client.post("/responses", json=payload)
    except Exception as e:
        return report(f"{model} /responses", False, f"{type(e).__name__}: {e}")
    save("sam_responses", {"status": r.status_code, "body": r.text[:20_000]})
    if r.status_code != 200:
        return report(
            f"{model} /responses", False, f"HTTP {r.status_code}: {r.text[:300]}"
        )
    return report(f"{model} /responses", True, f"{len(r.text)} bytes returned")


def check_wonder(client: httpx.Client, env: dict[str, str]) -> bool:
    model = env.get("WONDER_MODEL") or "muse-wonder-1.0"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 16,
    }
    try:
        r = client.post("/chat/completions", json=payload)
    except Exception as e:
        return report(f"chat {model}", False, f"{type(e).__name__}: {e}")
    if r.status_code != 200:
        return report(f"chat {model}", False, f"HTTP {r.status_code}: {r.text[:300]}")
    save("wonder_chat", r.json())
    return report(f"chat {model}", True, "responded")


CHECKS = {
    "models": check_models,
    "spark": check_spark,
    "structured": check_structured,
    "sam": check_sam,
    "wonder": check_wonder,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated: " + ",".join(CHECKS))
    args = ap.parse_args()

    env = load_env()
    base = env.get("META_API_BASE", "https://api.meta.ai/v1")
    names = args.only.split(",") if args.only else list(CHECKS)

    print(f"base: {base}")
    print(f"key:  loaded from .env ({len(env['MODEL_API_KEY'])} chars, not shown)")
    print()

    results: dict[str, bool] = {}
    with httpx.Client(
        base_url=base,
        timeout=TIMEOUT,
        headers={
            "Authorization": f"Bearer {env['MODEL_API_KEY']}",
            "Content-Type": "application/json",
        },
        follow_redirects=True,
    ) as client:
        for n in names:
            fn = CHECKS.get(n.strip())
            if not fn:
                print(f"  SKIP  unknown check {n!r}")
                continue
            results[n] = fn(client, env)

    print()
    passed = sum(results.values())
    print(f"{passed}/{len(results)} checks passed. Raw responses in docs/api-smoke/")
    if not results.get("models", True):
        print("\n!! /models failed — check the key and META_API_BASE before anything else.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
