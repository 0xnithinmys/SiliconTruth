"""Tests for the artifact orchestrator.

Its job is partial-failure behaviour: one generator failing must not cost
you the artifacts that generated fine, and a failed artifact must leave
NOTHING on disk rather than a truncated file -- a partial driver looks
exactly like a complete one at a glance, which is how a half-generated HAL
gets compiled and flashed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from silicontruth.ir.schema import PeripheralIR
from silicontruth.orchestrate import generate as orch
from silicontruth.orchestrate.generate import (
    NothingVerified,
    generate,
    write,
)
from silicontruth.verify.z3_register_audit import audit

FIXTURE = Path(__file__).parent / "fixtures" / "usart1_valid.json"


@pytest.fixture()
def ir() -> PeripheralIR:
    obj = PeripheralIR.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    result = audit(obj)
    assert result.passed, [str(v) for v in result.violations]
    for reg in obj.registers:
        reg.verified = True
    return obj


# --- the gate -------------------------------------------------------------


def test_nothing_verified_refuses_to_emit(ir: PeripheralIR) -> None:
    """An empty-but-valid SVD looks like a successful run, so an IR that
    failed its gates must produce no artifacts at all."""
    for reg in ir.registers:
        reg.verified = False
    with pytest.raises(NothingVerified):
        generate(ir)


def test_nothing_is_written_when_the_gate_refuses(ir: PeripheralIR, tmp_path) -> None:
    for reg in ir.registers:
        reg.verified = False
    with pytest.raises(NothingVerified):
        generate(ir)
    assert list(tmp_path.iterdir()) == []


# --- the full set ---------------------------------------------------------


def test_every_artifact_is_generated(ir: PeripheralIR) -> None:
    result = generate(ir)
    names = {a.name for a in result.artifacts}
    assert names == {
        "chip.svd",
        "usart1_hal.h",
        "usart1_hal.c",
        "usart1_hal.rs",
        "peripheral_mock.py",
        "platform.repl",
        "run_test.resc",
    }
    assert result.ok, [a.detail for a in result.failed]


def test_the_rust_hal_is_included(ir: PeripheralIR) -> None:
    """REGRESSION. `build` emitted the SVD, the C HAL and the Renode model
    but silently omitted the Rust HAL, which simply never reached disk."""
    rs = next(a for a in generate(ir).artifacts if a.name.endswith(".rs"))
    assert rs.ok
    assert "pub fn init()" in (rs.content or "")


def test_errata_ids_are_reported(ir: PeripheralIR) -> None:
    from silicontruth.ir.schema import (
        ErrataConstraint,
        ErrataRule,
        Provenance,
        Source,
    )

    ir.errata.append(
        ErrataRule(
            errata_id="2.1.1", title="t", affected_register="CR1",
            constraint=ErrataConstraint.DUMMY_READ_REQUIRED, params={},
            provenance=Provenance(
                page=19, bbox=(0.0, 0.0, 1.0, 1.0), source=Source.ERRATA,
            ),
        )
    )
    assert generate(ir).errata_applied == ["2.1.1"]


# --- partial failure ------------------------------------------------------


def test_one_generator_failing_does_not_lose_the_others(
    ir: PeripheralIR, monkeypatch
) -> None:
    def boom(_ir):
        raise RuntimeError("rust emitter exploded")

    monkeypatch.setattr(orch, "emit_rust", boom)
    result = generate(ir)

    assert not result.ok
    assert [a.name for a in result.failed] == ["usart1_hal.rs"]
    # The other six still generated.
    assert sum(1 for a in result.artifacts if a.ok) == 6
    assert "rust emitter exploded" in result.failed[0].detail


def test_a_failed_artifact_writes_nothing(ir: PeripheralIR, monkeypatch, tmp_path):
    """A truncated file on disk is indistinguishable from a complete one."""
    monkeypatch.setattr(
        orch, "emit_rust", lambda _ir: (_ for _ in ()).throw(RuntimeError("no"))
    )
    result = generate(ir)
    written = write(result, tmp_path)
    assert not any(p.name.endswith(".rs") for p in written)
    assert not (tmp_path / "usart1_hal.rs").exists()


def test_an_invalid_svd_is_a_failed_artifact_not_a_crash(
    ir: PeripheralIR, monkeypatch
) -> None:
    monkeypatch.setattr(
        orch, "validate_svd",
        lambda _xml: type("V", (), {"ok": False, "errors": ["bad bitRange"]})(),
    )
    result = generate(ir)
    svd = next(a for a in result.artifacts if a.name == "chip.svd")
    assert not svd.ok
    assert "bad bitRange" in svd.detail


def test_summary_counts_successes(ir: PeripheralIR, monkeypatch) -> None:
    monkeypatch.setattr(
        orch, "emit_rust", lambda _ir: (_ for _ in ()).throw(RuntimeError("no"))
    )
    assert generate(ir).summary() == "6/7 artifact(s) generated"


# --- writing --------------------------------------------------------------


def test_write_creates_the_directory_and_returns_paths(
    ir: PeripheralIR, tmp_path
) -> None:
    out = tmp_path / "nested" / "out"
    written = write(generate(ir), out)
    assert len(written) == 7
    assert all(p.exists() and p.stat().st_size > 0 for p in written)


def test_written_content_matches_the_artifact(ir: PeripheralIR, tmp_path) -> None:
    result = generate(ir)
    write(result, tmp_path)
    for a in result.artifacts:
        if a.ok and a.content is not None:
            assert (tmp_path / a.name).read_text(encoding="utf-8") == a.content
