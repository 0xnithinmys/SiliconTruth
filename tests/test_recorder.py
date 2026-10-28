"""Tests for the run recorder, specifically its resume path.

`extract` and `build` are two invocations of one logical run, and the replay
UI reads the single run.jsonl they share. Opening it in "w" both times meant
the second command silently erased the perception half -- the UI could only
ever show codegen, which was the half nobody doubted. These tests pin the
properties any reader of that file assumes: one run_start, one run_end, a
timeline that only moves forwards, and nothing dropped.
"""

from __future__ import annotations

from pathlib import Path

from silicontruth.replay.recorder import (
    EventKind,
    Recorder,
    build_index,
    read_run,
)


def _kinds(path: Path) -> list[str]:
    return [e["kind"] for e in read_run(path)]


def test_single_run_is_bracketed_once(tmp_path: Path) -> None:
    with Recorder(tmp_path, chip="uart32", peripheral="USART1",
                  base_address=0x4001_1000) as rec:
        rec.record(EventKind.Z3_AUDIT, passed=True)

    run = tmp_path / "uart32" / "run.jsonl"
    assert _kinds(run) == ["run_start", "z3_audit", "run_end"]
    assert read_run(run)[0]["base_address"] == 0x4001_1000


def test_resume_keeps_the_perception_half(tmp_path: Path) -> None:
    with Recorder(tmp_path, chip="uart32", peripheral="USART1") as rec:
        rec.record(EventKind.IR_EXTRACTED, register="CR1")
        rec.record(EventKind.NAME_AUDIT, passed=True)

    with Recorder(tmp_path, chip="uart32", peripheral="USART1",
                  append=True) as rec:
        rec.record(EventKind.HAL_EMITTED, errata=[])

    run = tmp_path / "uart32" / "run.jsonl"
    # The second command's events follow the first command's; neither the
    # extraction nor the codegen is lost, and the file still reads as one run.
    assert _kinds(run) == [
        "run_start", "ir_extracted", "name_audit", "hal_emitted", "run_end",
    ]


def test_resumed_timeline_only_moves_forwards(tmp_path: Path) -> None:
    with Recorder(tmp_path, chip="uart32", peripheral="USART1") as rec:
        rec.record(EventKind.IR_EXTRACTED, register="CR1")
    with Recorder(tmp_path, chip="uart32", peripheral="USART1",
                  append=True) as rec:
        rec.record(EventKind.HAL_EMITTED, errata=[])

    events = read_run(tmp_path / "uart32" / "run.jsonl")
    stamps = [e["t_ms"] for e in events]
    # A fresh perf_counter in the second process would restart near zero and
    # make the trace appear to run backwards halfway through.
    assert stamps == sorted(stamps), stamps
    # run_end counts the whole run, not just the segment that wrote it.
    assert events[-1]["events"] == len(events) - 1


def test_resume_without_append_truncates(tmp_path: Path) -> None:
    with Recorder(tmp_path, chip="uart32", peripheral="USART1") as rec:
        rec.record(EventKind.IR_EXTRACTED, register="CR1")
    with Recorder(tmp_path, chip="uart32", peripheral="USART1") as rec:
        rec.record(EventKind.HAL_EMITTED, errata=[])

    # Default stays destructive on purpose: a plain re-run is a NEW run and
    # must not accrete events from the last one.
    assert _kinds(tmp_path / "uart32" / "run.jsonl") == [
        "run_start", "hal_emitted", "run_end",
    ]


def test_disabled_recorder_writes_nothing(tmp_path: Path) -> None:
    with Recorder(tmp_path, chip="uart32", peripheral="USART1",
                  enabled=False) as rec:
        rec.record(EventKind.Z3_AUDIT, passed=True)
    assert not (tmp_path / "uart32" / "run.jsonl").exists()


def test_index_reports_the_resumed_duration(tmp_path: Path) -> None:
    with Recorder(tmp_path, chip="uart32", peripheral="USART1") as rec:
        rec.record(EventKind.IR_EXTRACTED, register="CR1")
    with Recorder(tmp_path, chip="uart32", peripheral="USART1",
                  append=True) as rec:
        rec.write_artifact("usart1_hal.c", "int main(void) { return 0; }")

    index = build_index(tmp_path)
    (chip,) = index["chips"]
    assert chip["chip"] == "uart32"
    assert chip["peripheral"] == "USART1"
    assert "usart1_hal.c" in chip["artifacts"]
    assert chip["events"] == 4  # run_start, ir_extracted, artifact, run_end
