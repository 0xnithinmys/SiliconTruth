"""T-130 — record every run as JSONL so Keyless Replay is nearly free.

Recording starts on day one, not at the end. Two reasons:
  * the replay feature then costs almost nothing to build
  * every run leaves a debugging artifact while the pipeline is still changing

A judge opening the deployed URL gets these fixtures from a CDN edge cache:
no API key, no signup, no backend, no cold start. Live infra failing during
judging is a medium-likelihood, critical-impact risk; this removes the
dependency rather than mitigating it.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1


class EventKind(str, Enum):
    RUN_START = "run_start"
    PAGE_RENDER = "page_render"
    SAM_MASK = "sam_mask"
    IR_EXTRACTED = "ir_extracted"
    Z3_AUDIT = "z3_audit"
    Z3_RETRY = "z3_retry"
    # The two gates added after the DPI sweep found a false negative. Z3
    # proves arithmetic; these check the names against the page. They are
    # recorded separately because they fail for different reasons and a UI
    # that collapses them into one "verified" badge hides which one spoke.
    NAME_AUDIT = "name_audit"
    GRID_AUDIT = "grid_audit"
    ERRATA_LINKED = "errata_linked"
    SVD_EMITTED = "svd_emitted"
    HAL_EMITTED = "hal_emitted"
    ARTIFACT = "artifact"
    WORKTREE = "worktree"
    RENODE_TRACE = "renode_trace"
    VERDICT = "verdict"
    RUN_END = "run_end"
    ERROR = "error"


def _jsonable(obj: Any) -> Any:
    """Best-effort conversion. Recording must never crash a real run."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if is_dataclass(obj) and not isinstance(obj, type):
        return _jsonable(asdict(obj))
    if hasattr(obj, "model_dump"):  # pydantic
        return _jsonable(obj.model_dump(mode="json"))
    if isinstance(obj, bytes):
        return f"<{len(obj)} bytes>"
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


@dataclass
class Event:
    kind: EventKind
    t_ms: float
    payload: dict[str, Any] = field(default_factory=dict)

    def to_line(self) -> str:
        return json.dumps(
            {"kind": self.kind.value, "t_ms": round(self.t_ms, 2), **_jsonable(self.payload)}
        )


class Recorder:
    """Append-only JSONL writer for one pipeline run.

    Usage:
        with Recorder("fixtures", chip="stm32h7", peripheral="USART1") as rec:
            rec.record(EventKind.Z3_AUDIT, passed=True, elapsed_ms=17.5)
    """

    def __init__(
        self,
        root: Path | str,
        *,
        chip: str,
        peripheral: str,
        base_address: int = 0,
        enabled: bool = True,
        append: bool = False,
    ) -> None:
        self.chip = chip
        self.peripheral = peripheral
        self.base_address = base_address
        # `extract` and `build` are separate invocations of ONE logical run:
        # the first reads the PDF, the second generates from the IR. Opening
        # in "w" both times meant the second silently erased the perception
        # half, leaving the replay UI able to show only codegen -- the half
        # that was never in question.
        self.append = append
        self.enabled = enabled
        self.dir = Path(root) / chip
        self.path = self.dir / "run.jsonl"
        self.events: list[Event] = []
        # Events written by an earlier command of the same run; see _resume.
        self._prior_events = 0
        self._t0 = time.perf_counter()
        self._fh = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> Recorder:
        continuing = False
        if self.enabled:
            self.dir.mkdir(parents=True, exist_ok=True)
            continuing = self.append and self.path.exists()
            if continuing:
                self._resume()
            else:
                self._fh = self.path.open("w", encoding="utf-8")
        # A continued run must not emit a second run_start: the UI reads the
        # first one for the chip's identity and base address, and two of them
        # is two runs as far as any reader is concerned.
        if not continuing:
            self.record(
                EventKind.RUN_START,
                schema=SCHEMA_VERSION,
                chip=self.chip,
                peripheral=self.peripheral,
                base_address=self.base_address,
            )
        return self

    def _resume(self) -> None:
        """Continue the trace the previous command left behind.

        Two things have to be repaired, or the file stops describing one run:
        the earlier command closed with a `run_end`, which would otherwise sit
        in the middle of the timeline, and its `t_ms` clock started at its own
        process launch, so a fresh clock would jump backwards. The trailing
        `run_end` is dropped and this recorder's origin is pushed back to where
        that clock stopped, leaving exactly one run_start, one run_end, and a
        monotonic timeline across both invocations.
        """
        kept = [
            line
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        while kept and f'"kind": "{EventKind.RUN_END.value}"' in kept[-1]:
            kept.pop()
        elapsed_ms = 0.0
        for line in reversed(kept):
            try:
                elapsed_ms = float(json.loads(line).get("t_ms", 0.0))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            break
        self._prior_events = len(kept)
        self._t0 = time.perf_counter() - elapsed_ms / 1000.0
        self._fh = self.path.open("w", encoding="utf-8")
        for line in kept:
            self._fh.write(line + "\n")
        self._fh.flush()

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.record(EventKind.ERROR, type=exc_type.__name__, message=str(exc))
        self.record(EventKind.RUN_END, events=self._prior_events + len(self.events))
        if self._fh:
            self._fh.close()
            self._fh = None

    # -- recording ---------------------------------------------------------

    def record(self, kind: EventKind, **payload: Any) -> Event:
        ev = Event(
            kind=kind, t_ms=(time.perf_counter() - self._t0) * 1000.0, payload=payload
        )
        self.events.append(ev)
        if self._fh:
            self._fh.write(ev.to_line() + "\n")
            self._fh.flush()  # a crashed run still leaves a usable trace
        return ev

    def write_artifact(self, name: str, content: str | bytes) -> Path:
        """Persist a generated file beside the trace (chip.svd, driver.c, ...)."""
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
        self.record(EventKind.ARTIFACT, artifact=name, bytes=len(content))
        return p

    def of_kind(self, kind: EventKind) -> list[Event]:
        return [e for e in self.events if e.kind is kind]


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------


def read_run(path: Path | str) -> list[dict[str, Any]]:
    """Load a recorded run. Malformed lines are skipped, not fatal: a partial
    trace from a crashed run is still worth showing."""
    out: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def iter_runs(root: Path | str) -> Iterator[tuple[str, Path]]:
    """Every recorded chip under root, for the replay chip switcher."""
    for d in sorted(Path(root).iterdir()):
        run = d / "run.jsonl"
        if d.is_dir() and run.exists():
            yield d.name, run


def build_index(root: Path | str) -> dict[str, Any]:
    """Manifest the replay UI reads to populate its chip list."""
    chips = []
    for name, run in iter_runs(root):
        events = read_run(run)
        start = next((e for e in events if e["kind"] == "run_start"), {})
        verdict = next(
            (e for e in reversed(events) if e["kind"] == "verdict"), {}
        )
        chips.append(
            {
                "chip": name,
                "peripheral": start.get("peripheral", "?"),
                "events": len(events),
                "duration_ms": events[-1]["t_ms"] if events else 0,
                "status": verdict.get("status", "UNKNOWN"),
                "artifacts": sorted(
                    p.name for p in run.parent.iterdir() if p.name != "run.jsonl"
                ),
            }
        )
    return {"schema": SCHEMA_VERSION, "chips": chips}


def write_index(root: Path | str) -> Path:
    root = Path(root)
    p = root / "index.json"
    p.write_text(json.dumps(build_index(root), indent=2), encoding="utf-8")
    return p
