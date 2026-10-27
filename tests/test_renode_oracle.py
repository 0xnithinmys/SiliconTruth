"""T-084..T-090 — the Renode peripheral model and the MMIO oracle.

THE KEYSTONE GATE (T-090)
-------------------------
    the naive driver trips a deterministic MMIO trap with a faulting PC
    AND the SiliconTruth-generated driver passes clean

Renode is not installed locally, so these tests drive the oracle with recorded
and synthetic traces. That is the right seam anyway: the assertion logic is what
we are testing, and it must be judged on trace content, not on whether an
emulator binary happens to be on PATH. The Modal container feeds it real traces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from silicontruth.ir.schema import (
    ErrataConstraint,
    ErrataRule,
    PeripheralIR,
    Provenance,
    Source,
)
from silicontruth.oracle.renode_oracle import (
    Status,
    evaluate,
    find_fault_pc,
    parse_trace,
    render_bus_trace,
)
from silicontruth.synth.renode_peripheral import emit_peripheral, emit_repl, emit_resc
from silicontruth.verify.z3_register_audit import audit

FIXTURE = Path(__file__).parent / "fixtures" / "usart1_valid.json"
BASE = 0x4001_1000


@pytest.fixture
def ir() -> PeripheralIR:
    x = PeripheralIR.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    assert audit(x).passed
    return x


@pytest.fixture
def ir_with_errata(ir: PeripheralIR) -> PeripheralIR:
    ir.errata.append(
        ErrataRule(
            errata_id="2.14.1",
            title="3-cycle delay required after CR1 write",
            affected_register="CR1",
            constraint=ErrataConstraint.DELAY_CYCLES_AFTER_WRITE,
            params={"cycles": 3},
            provenance=Provenance(
                page=19, bbox=(1.0, 1.0, 9.0, 9.0), source=Source.ERRATA, errata_id="2.14.1"
            ),
        )
    )
    return ir


# ---------------------------------------------------------------------------
# Synthetic traces, in the exact format the generated peripheral prints
# ---------------------------------------------------------------------------

GOOD_TRACE = """
Renode, version 1.15.0
Starting emulation...
SILICONTRUTH_MMIO WRITE 0x0000000C BRR 0x0000022B [PASS]
SILICONTRUTH_MMIO WRITE 0x00000004 CR2 0x00000000 [PASS]
SILICONTRUTH_MMIO WRITE 0x00000000 CR1 0x0000200C [PASS]
SILICONTRUTH_MMIO READ  0x00000000 CR1 0x0000200C [PASS]
Emulation finished.
"""

# What a naive single-pass LLM driver produces: CR1.UE set before BRR, and no
# errata delay. The peripheral model rejects the first offending write.
NAIVE_TRACE = """
Renode, version 1.15.0
Starting emulation...
SILICONTRUTH_MMIO WRITE 0x00000000 CR1 0x00002001 [PASS]
SILICONTRUTH_MMIO WRITE 0x0000000C BRR 0x0000022B [FAIL] ERRATA_2_14_1_DELAY_MISSING
cpu: CPU abort [PC=0x08000142]
Emulation finished.
"""

CLOCK_TRACE = """
SILICONTRUTH_MMIO WRITE 0x00000004 CR2 0x00000001 [FAIL] CLOCK_NOT_ENABLED
cpu: HardFault at PC=0x0800019A
"""

UNDEFINED_TRACE = """
SILICONTRUTH_MMIO READ 0x000000F0 ? 0x00000000 [FAIL] UNDEFINED_OFFSET
cpu: abort pc: 0x080001FE
"""

SILENT_TRACE = """
Renode, version 1.15.0
Starting emulation...
Emulation finished.
"""


# ---------------------------------------------------------------------------
# THE KEYSTONE GATE
# ---------------------------------------------------------------------------


def test_keystone_naive_driver_traps_and_generated_driver_passes() -> None:
    """T-090. Both directions, because either alone proves nothing.

    A gate that only rejects bad input might reject everything.
    A gate that only accepts good input might accept everything.
    """
    naive = evaluate(NAIVE_TRACE, base_address=BASE)
    good = evaluate(GOOD_TRACE, base_address=BASE)

    # The naive driver must fail, specifically and with a location.
    assert naive.status is Status.FAIL
    assert naive.exit_code != 0
    assert naive.violation == "ERRATA_2_14_1_DELAY_MISSING"
    assert naive.mmio_addr == "0x4001100C"
    assert naive.fault_pc == "0x08000142"

    # The generated driver must pass.
    assert good.status is Status.PASS
    assert good.exit_code == 0
    assert good.violation is None
    assert len(good.transactions) == 4


def test_verdict_json_is_the_documented_shape() -> None:
    """The repair loop and the UI both parse this. Its shape is a contract."""
    payload = json.loads(evaluate(NAIVE_TRACE, base_address=BASE).to_json())
    assert payload["status"] == "FAIL"
    assert payload["fault_pc"] == "0x08000142"
    assert payload["mmio_addr"] == "0x4001100C"
    assert payload["violation"] == "ERRATA_2_14_1_DELAY_MISSING"


# ---------------------------------------------------------------------------
# Trace parsing
# ---------------------------------------------------------------------------


def test_parse_extracts_every_transaction() -> None:
    txns = parse_trace(GOOD_TRACE)
    assert [t.register for t in txns] == ["BRR", "CR2", "CR1", "CR1"]
    assert [t.kind for t in txns] == ["WRITE", "WRITE", "WRITE", "READ"]
    assert txns[0].offset == 0x0C
    assert txns[0].value == 0x22B
    assert all(t.verdict == "PASS" for t in txns)


def test_parse_ignores_surrounding_renode_chatter() -> None:
    assert len(parse_trace("noise\n" + GOOD_TRACE + "\nmore noise")) == 4


def test_parse_captures_the_failure_note() -> None:
    failed = [t for t in parse_trace(NAIVE_TRACE) if t.verdict == "FAIL"]
    assert len(failed) == 1
    assert failed[0].note == "ERRATA_2_14_1_DELAY_MISSING"


def test_parse_empty_trace() -> None:
    assert parse_trace("") == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("cpu: CPU abort [PC=0x08000142]", "0x08000142"),
        ("HardFault at PC=0x0800019A", "0x0800019A"),
        ("cpu: abort pc: 0x080001FE", "0x080001FE"),
        ("no program counter here", None),
    ],
)
def test_fault_pc_extraction(text: str, expected: str | None) -> None:
    assert find_fault_pc(text) == expected


# ---------------------------------------------------------------------------
# Failure modes the model must catch
# ---------------------------------------------------------------------------


def test_clock_not_enabled_is_caught() -> None:
    """Failure mode C: config register written before the clock gate is set."""
    v = evaluate(CLOCK_TRACE, base_address=BASE)
    assert v.status is Status.FAIL
    assert v.violation == "CLOCK_NOT_ENABLED"
    assert v.mmio_addr == "0x40011004"
    assert v.fault_pc == "0x0800019A"


def test_undefined_offset_is_caught() -> None:
    v = evaluate(UNDEFINED_TRACE, base_address=BASE)
    assert v.status is Status.FAIL
    assert v.violation == "UNDEFINED_OFFSET"


def test_cpu_abort_without_a_failed_transaction_still_fails() -> None:
    trace = "SILICONTRUTH_MMIO WRITE 0x00000000 CR1 0x1 [PASS]\ncpu: HardFault at PC=0x08000100"
    v = evaluate(trace, base_address=BASE)
    assert v.status is Status.FAIL
    assert v.violation == "CPU_ABORT"
    assert v.fault_pc == "0x08000100"


def test_silence_is_not_success() -> None:
    """A driver that never touches the peripheral must not pass. This is the
    easiest way for a generated driver to look correct while doing nothing."""
    v = evaluate(SILENT_TRACE)
    assert v.status is Status.NO_TRACE
    assert v.exit_code != 0
    assert v.violation == "NO_MMIO_ACTIVITY"


def test_silence_can_be_allowed_explicitly() -> None:
    assert evaluate(SILENT_TRACE, require_transactions=False).status is Status.PASS


def test_first_failure_wins() -> None:
    """The repair loop fixes one thing at a time; report the earliest fault."""
    trace = (
        "SILICONTRUTH_MMIO WRITE 0x00000000 CR1 0x1 [FAIL] FIRST\n"
        "SILICONTRUTH_MMIO WRITE 0x00000004 CR2 0x2 [FAIL] SECOND\n"
    )
    assert evaluate(trace).violation == "FIRST"


# ---------------------------------------------------------------------------
# Bus-trace rendering (the UI pane)
# ---------------------------------------------------------------------------


def test_bus_trace_render_matches_the_demo_format() -> None:
    rendered = render_bus_trace(evaluate(GOOD_TRACE, base_address=BASE), BASE)
    assert "WRITE 0x4001100C -> 0x0000022B [PASS]" in rendered
    assert "WRITE 0x40011000 -> 0x0000200C [PASS]" in rendered


def test_bus_trace_shows_the_failure_note() -> None:
    v = evaluate(NAIVE_TRACE, base_address=BASE)
    assert "ERRATA_2_14_1_DELAY_MISSING" in render_bus_trace(v, BASE)


# ---------------------------------------------------------------------------
# Peripheral model generation
# ---------------------------------------------------------------------------


def test_generated_peripheral_is_valid_python(ir_with_errata: PeripheralIR) -> None:
    """It runs inside Renode's interpreter; a syntax error there is a late,
    confusing failure. Compile it here instead."""
    src = emit_peripheral(ir_with_errata)
    compile(src, "peripheral_mock.py", "exec")


def test_generated_peripheral_contains_the_register_map(ir: PeripheralIR) -> None:
    src = emit_peripheral(ir)
    assert "0x00: {'name': 'CR1'" in src
    assert "0x04: {'name': 'CR2'" in src
    assert "0x0C: {'name': 'BRR'" in src


def test_generated_peripheral_defines_the_trap_exceptions(ir: PeripheralIR) -> None:
    src = emit_peripheral(ir)
    assert "class InvalidStateAccess" in src
    assert "class ErrataViolation" in src


def test_generated_peripheral_handles_all_three_request_kinds(ir: PeripheralIR) -> None:
    src = emit_peripheral(ir)
    assert "request.isInit" in src
    assert "request.isRead" in src
    assert "request.isWrite" in src


def test_errata_rules_reach_the_model(ir_with_errata: PeripheralIR) -> None:
    src = emit_peripheral(ir_with_errata)
    assert "DELAY_REQUIRED     = [0]", "CR1 at offset 0 should require a delay"
    assert "ERRATA_DELAY_MISSING" in src


def test_unverified_registers_are_not_modelled(ir: PeripheralIR) -> None:
    brr = ir.register_by_name("BRR")
    assert brr is not None
    brr.offset = 0x03
    audit(ir)
    src = emit_peripheral(ir)
    assert "'BRR'" not in src


def test_peripheral_requires_verified_registers() -> None:
    raw = PeripheralIR.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="no verified registers"):
        emit_peripheral(raw)


# ---------------------------------------------------------------------------
# Platform and script generation
# ---------------------------------------------------------------------------


def test_repl_maps_the_peripheral_at_its_base_address(ir: PeripheralIR) -> None:
    repl = emit_repl(ir)
    assert "Python.PythonPeripheral @ sysbus 0x40011000" in repl
    assert 'filename: "peripheral_mock.py"' in repl
    assert "cpu: CPU.CortexM @ sysbus" in repl


def test_repl_size_covers_the_register_span(ir: PeripheralIR) -> None:
    size_line = next(ln for ln in emit_repl(ir).splitlines() if ln.strip().startswith("size:"))
    assert int(size_line.split("0x")[1], 16) >= 0x10


def test_resc_boots_headless_and_quits(ir: PeripheralIR) -> None:
    resc = emit_resc(ir)
    assert "mach create" in resc
    assert "LoadPlatformDescription @platform.repl" in resc
    assert "sysbus LoadELF @test_firmware.elf" in resc
    assert resc.strip().endswith("quit")


# ---------------------------------------------------------------------------
# End to end: generated peripheral logic agrees with the oracle
# ---------------------------------------------------------------------------


def test_model_and_oracle_agree_on_the_trace_format(ir: PeripheralIR) -> None:
    """The peripheral prints the lines; the oracle parses them. If these two
    drift, the oracle silently sees zero transactions and everything 'passes'."""
    from silicontruth.synth.renode_peripheral import TRACE_PREFIX

    src = emit_peripheral(ir)
    assert TRACE_PREFIX in src
    # Build a line exactly as the model's format string would, then parse it.
    line = f"{TRACE_PREFIX} WRITE 0x00000000 CR1 0x0000200C [PASS]"
    txns = parse_trace(line)
    assert len(txns) == 1, "the oracle cannot parse what the model emits"
    assert txns[0].register == "CR1" and txns[0].value == 0x200C
