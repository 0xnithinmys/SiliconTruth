"""Pluggable inference backend.

WHY THIS EXISTS
---------------
The Meta Model API is billing-blocked (HTTP 402) and Groq's free tier serves no
usable Llama. Rather than couple the pipeline to whichever vendor happens to work
this week, every model call goes through this interface.

Swapping providers is then a .env change, not a refactor. When the Meta credits
land, set PROVIDER=meta and nothing downstream moves.

WHAT A PROVIDER MUST OFFER
--------------------------
  complete()   text in, text out
  extract()    text+images in, schema-validated JSON out   <-- Stage 2 depends on this
  supports_vision / context_window   capability reporting, so the pipeline can
                                     refuse to run rather than silently degrade

A provider that cannot do vision is not a drop-in for Stage 1. We make that
explicit instead of discovering it mid-extraction.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent


def load_env(path: Path | None = None) -> dict[str, str]:
    """Read .env without a dependency. Never logs values."""
    p = path or (ROOT / ".env")
    env: dict[str, str] = dict(os.environ)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env.setdefault(k.strip(), v.strip())
    return env


class ProviderError(RuntimeError):
    """Raised with the vendor's own message, so failures stay diagnosable."""


class BillingBlocked(ProviderError):
    """HTTP 402. Distinct because it is actionable by a human, not by a retry."""


class VisionUnsupported(ProviderError):
    """The configured provider cannot accept images. Stage 1 cannot proceed."""


@dataclass(frozen=True)
class Capabilities:
    name: str
    text_model: str
    vision_model: str | None
    context_window: int

    @property
    def supports_vision(self) -> bool:
        return self.vision_model is not None


class Provider(ABC):
    """One inference backend."""

    @property
    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    def complete(self, prompt: str, *, max_tokens: int = 1024) -> str: ...

    @abstractmethod
    def extract(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        images: list[str] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Schema-locked JSON extraction. `images` are data: URLs or https URLs."""

    def require_vision(self) -> None:
        if not self.capabilities.supports_vision:
            raise VisionUnsupported(
                f"provider '{self.capabilities.name}' has no vision model configured. "
                "Stage 1 reads register tables from page images and cannot run "
                "without one."
            )


class OpenAICompatProvider(Provider):
    """Covers Meta Model API, Groq, OpenRouter, Together, Cerebras.

    They all speak the OpenAI chat-completions shape, so one implementation
    serves every candidate backend. Only base URL, key and model IDs differ.
    """

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        text_model: str,
        vision_model: str | None = None,
        context_window: int = 131_072,
        timeout: float = 180.0,
    ) -> None:
        if not api_key:
            raise ProviderError(f"{name}: no API key configured")
        self._caps = Capabilities(
            name=name,
            text_model=text_model,
            vision_model=vision_model,
            context_window=context_window,
        )
        self._client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout, connect=20.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            follow_redirects=True,
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._caps

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self._client.post("/chat/completions", json=payload)
        except Exception as e:  # network-level
            raise ProviderError(f"{self._caps.name}: {type(e).__name__}: {e}") from e
        if r.status_code == 402:
            raise BillingBlocked(f"{self._caps.name}: {r.text[:400]}")
        if r.status_code != 200:
            raise ProviderError(f"{self._caps.name}: HTTP {r.status_code}: {r.text[:400]}")
        return r.json()

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> str:
        body = self._post(
            {
                "model": self._caps.text_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
            }
        )
        return body["choices"][0]["message"]["content"]

    def extract(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        images: list[str] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        if images:
            self.require_vision()
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for img in images:
                content.append({"type": "image_url", "image_url": {"url": img}})
            message: dict[str, Any] = {"role": "user", "content": content}
            model = self._caps.vision_model or self._caps.text_model
        else:
            message = {"role": "user", "content": prompt}
            model = self._caps.text_model

        body = self._post(
            {
                "model": model,
                "messages": [message],
                "max_tokens": max_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "extraction",
                        "schema": schema,
                        "strict": True,
                    },
                },
            }
        )
        raw = body["choices"][0]["message"]["content"]
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"{self._caps.name}: response was not valid JSON: {raw[:300]!r}"
            ) from e


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Known backends. Each entry says where to find the key, the base URL, and
# sensible model defaults that .env can override.
_BACKENDS: dict[str, dict[str, Any]] = {
    "meta": {
        "key_var": "MODEL_API_KEY",
        "base_var": "META_API_BASE",
        "base_default": "https://api.meta.ai/v1",
        "text_var": "SPARK_MODEL",
        "text_default": "muse-spark-1.3-contributor",
        "vision_var": "SAM_MODEL",
        "vision_default": "muse-spark-1.3",
        "context_window": 1_048_576,
    },
    "openrouter": {
        "key_var": "OPENROUTER_API_KEY",
        "base_var": "OPENROUTER_API_BASE",
        "base_default": "https://openrouter.ai/api/v1",
        "text_var": "OPENROUTER_TEXT_MODEL",
        "text_default": "meta-llama/llama-4-scout",
        "vision_var": "OPENROUTER_VISION_MODEL",
        "vision_default": "meta-llama/llama-4-scout",
        "context_window": 1_310_720,
    },
    "groq": {
        "key_var": "GROQ_API_KEY",
        "base_var": "GROQ_API_BASE",
        "base_default": "https://api.groq.com/openai/v1",
        "text_var": "GROQ_TEXT_MODEL",
        "text_default": "",
        "vision_var": "GROQ_VISION_MODEL",
        "vision_default": "",
        "context_window": 131_072,
    },
    "together": {
        "key_var": "TOGETHER_API_KEY",
        "base_var": "TOGETHER_API_BASE",
        "base_default": "https://api.together.xyz/v1",
        "text_var": "TOGETHER_TEXT_MODEL",
        "text_default": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "vision_var": "TOGETHER_VISION_MODEL",
        "vision_default": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "context_window": 1_048_576,
    },
}


def available_backends(env: dict[str, str] | None = None) -> list[str]:
    """Backends that have a key present. Does not check that the key works."""
    e = env or load_env()
    return [n for n, c in _BACKENDS.items() if e.get(c["key_var"])]


def get_provider(name: str | None = None, env: dict[str, str] | None = None) -> Provider:
    """Build the configured provider.

    Order: explicit arg > PROVIDER in .env > first backend with a key present.
    """
    e = env or load_env()
    chosen = name or e.get("PROVIDER") or next(iter(available_backends(e)), None)
    if not chosen:
        raise ProviderError(
            "no inference backend configured. Set one of "
            + ", ".join(c["key_var"] for c in _BACKENDS.values())
            + " in .env"
        )
    if chosen not in _BACKENDS:
        raise ProviderError(f"unknown provider {chosen!r}; known: {list(_BACKENDS)}")

    cfg = _BACKENDS[chosen]
    vision = e.get(cfg["vision_var"]) or cfg["vision_default"]
    return OpenAICompatProvider(
        name=chosen,
        base_url=e.get(cfg["base_var"]) or cfg["base_default"],
        api_key=e.get(cfg["key_var"], ""),
        text_model=e.get(cfg["text_var"]) or cfg["text_default"],
        vision_model=vision or None,
        context_window=int(cfg["context_window"]),
    )
