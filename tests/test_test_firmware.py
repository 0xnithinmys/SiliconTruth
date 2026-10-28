"""The test firmware and the local Docker oracle.

These cover the gap that kept invariant #2 from ever running: emit_resc has
always written `sysbus LoadELF @test_firmware.elf`, and nothing produced that
ELF. The emulation gate could not have executed even with Renode installed.

Everything here is pure. No Docker, no toolchain, no network, so it runs in
the normal suite on a machine that has none of them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from silicontruth.ir.schema import (
    ErrataConstraint,
    ErrataRule,
    PeripheralIR,
    Provenance,
    Source,
)
from silicontruth.oracle import docker_oracle as do
from silicontruth.synth.hal_c_emitter import emit_hal
from silicontruth.synth.renode_peripheral import emit_peripheral, emit_repl, emit_resc
from silicontruth.synth.test_firmware import (
    FLASH_ORIGIN,
    SRAM_ORIGIN,
    emit_firmware,
    emit_linker_script,
)
from silicontruth.verify.z3_register_audit import audit

FIXTURE = Path(__file__).parent / "fixtures" / "usart1_valid.json"


@pytest.fixture
def ir() -> PeripheralIR:
    x = PeripheralIR.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    assert audit(x).passed
    return x


@pytest.fixture
def ir_clock(ir: PeripheralIR) -> PeripheralIR:
    # A deep copy, NOT the same object. Appending to `ir` in place made the two
    # fixtures one object, so the "only when the erratum demands it" assertion
    # was comparing the clock-erratum IR against itself and could never fail.
    ir = ir.model_copy(deep=True)
    ir.errata.append(
        ErrataRule(
            errata_id="2.3.2",
            title="register access before clock enable",
            affected_register=ir.registers[0].name,
            constraint=ErrataConstraint.CLOCK_ENABLE_BEFORE_ACCESS,
            params={},
            provenance=Provenance(
                page=19, bbox=(1.0, 2.0, 3.0, 4.0), source=Source.ERRATA,
                errata_id="2.3.2",
            ),
        )
    )
    return ir


# -- the firmware ---------------------------------------------------------


def test_firmware_boots_and_drives_the_driver(ir: PeripheralIR) -> None:
    src = emit_firmware(ir)
    p = ir.peripheral.lower()
    assert f"{p}_init()" in src
    assert f'#include "{p}_hal.h"' in src
    # A Cortex-M loads SP and the reset vector from the start of the image. No
    # vector table means the core faults before main and the oracle reports a
    # driver failure that is really a missing startup.
    assert ".vectors" in src
    assert "Reset_Handler" in src
    assert "_stack_top" in src


def test_clock_hook_is_defined_only_when_the_erratum_demands_it(
    ir: PeripheralIR, ir_clock: PeripheralIR
) -> None:
    p = ir.peripheral.lower()
    # The HAL declares the hook without defining it, so an unimplemented
    # workaround is a link error. The firmware is the board, so the firmware
    # supplies it -- but only when there is an erratum that needs one.
    assert f"int {p}_enable_clock(void)\n{{" in emit_firmware(ir_clock)
    assert f"int {p}_enable_clock(void)\n{{" not in emit_firmware(ir)


def test_clock_hook_writes_no_peripheral_register(ir_clock: PeripheralIR) -> None:
    """The hook satisfies the linker and touches no MMIO.

    It used to write the lowest-offset register and call that enabling the
    clock. That was wrong twice over: the clock lives in a controller absent
    from this IR, so the write invented hardware hal_c_emitter explicitly
    refuses to invent, and the register it picked is one the erratum protects,
    so it also tripped the delay rule on that same register. Nothing may be
    written here; whether the clock was on is judged by abstention instead."""
    src = emit_firmware(ir_clock)
    body = src[src.index("_enable_clock(void)") :].split("}")[0]
    assert "return 0;" in body
    # No assignment to any generated register macro.
    assert f"{ir_clock.peripheral.upper()}_" not in body


def test_firmware_refuses_an_ir_with_nothing_verified(ir: PeripheralIR) -> None:
    for r in ir.registers:
        r.verified = False
    with pytest.raises(ValueError):
        emit_firmware(ir)


# -- the linker script ----------------------------------------------------


def test_linker_regions_match_the_generated_platform(ir: PeripheralIR) -> None:
    """A linker script that disagrees with platform.repl by one digit produces
    a firmware that loads and immediately hard-faults. Pin them together."""
    ld = emit_linker_script()
    repl = emit_repl(ir)

    for origin in (FLASH_ORIGIN, SRAM_ORIGIN):
        assert f"0x{origin:08X}" in ld
        assert f"0x{origin:08X}" in repl

    assert "ENTRY(Reset_Handler)" in ld
    assert "_stack_top = ORIGIN(SRAM) + LENGTH(SRAM);" in ld


def test_vectors_section_is_placed_first_in_flash() -> None:
    ld = emit_linker_script()
    sections = ld[ld.index("SECTIONS") :]
    assert sections.index(".vectors") < sections.index(".text")


# -- command construction -------------------------------------------------


def test_compile_links_an_elf_rather_than_object_files() -> None:
    cmd = do.compile_cmd("USART1")
    assert "-o" in cmd and "test_firmware.elf" in cmd
    assert "-T" in cmd and "link.ld" in cmd
    # The previous container only ever passed -c, which is exactly why
    # LoadELF had nothing to load.
    assert "-c" not in cmd
    assert "-Werror" in cmd
    assert "usart1_hal.c" in cmd and "main.c" in cmd


def test_renode_runs_headless() -> None:
    # Without --disable-xwt Renode looks for a display, fails to find one, and
    # hangs instead of failing. That is indistinguishable from a slow run.
    assert "--disable-xwt" in do.renode_cmd()


def test_docker_mounts_the_workdir(tmp_path: Path) -> None:
    cmd = do.docker_cmd(tmp_path, ["echo", "hi"], image="img:1")
    assert "--rm" in cmd
    joined = " ".join(cmd)
    assert ":/work" in joined
    assert joined.endswith("img:1 echo hi")


def test_write_inputs_lays_out_everything_the_container_needs(
    ir_clock: PeripheralIR, tmp_path: Path
) -> None:
    hal = emit_hal(ir_clock)
    names = do.write_inputs(ir_clock, hal.source, hal.header, tmp_path)
    p = ir_clock.peripheral.lower()
    assert set(names) == {
        "link.ld",
        "main.c",
        "peripheral_mock.py",
        "platform.repl",
        "run_test.resc",
        f"{p}_hal.c",
        f"{p}_hal.h",
    }
    for n in names:
        assert (tmp_path / n).read_text(encoding="utf-8").strip()

    # The script names the ELF the compile step is told to produce. These two
    # drifting apart is the original bug, so assert they agree.
    resc = (tmp_path / "run_test.resc").read_text(encoding="utf-8")
    elf = re.search(r"LoadELF @(\S+)", resc)
    assert elf and elf.group(1) in do.compile_cmd(ir_clock.peripheral)


# -- the four bugs the first live run of the emulation gate exposed ---------
#
# Every one of these survived review because the gate had never executed. They
# are pinned individually: each was independently capable of making the whole
# second invariant vacuous while reporting success.


@pytest.fixture
def ir_delay(ir: PeripheralIR) -> PeripheralIR:
    ir = ir.model_copy(deep=True)
    ir.errata.append(
        ErrataRule(
            errata_id="2.14.1",
            title="delay required after write",
            affected_register=ir.registers[0].name,
            constraint=ErrataConstraint.DELAY_CYCLES_AFTER_WRITE,
            params={"cycles": 16},
            provenance=Provenance(
                page=19, bbox=(1.0, 2.0, 3.0, 4.0), source=Source.ERRATA,
                errata_id="2.14.1",
            ),
        )
    )
    return ir


def test_mock_state_survives_re_execution(ir_delay: PeripheralIR) -> None:
    """Renode re-runs the whole script on EVERY bus access.

    An unconditional `state = {...}` therefore reset the state before each
    check could read it, which silently killed the clock, delay, dummy-read
    and write-order traps together. The mock enforced only "is this offset
    known" while looking like it enforced the datasheet's state machine."""
    src = emit_peripheral(ir_delay)
    assert "if 'state' not in globals():" in src
    # And nothing may reassign it unconditionally at top level again.
    assert "\nstate = {" not in src


def test_resc_addresses_the_cpu_by_full_path(ir: PeripheralIR) -> None:
    """A bare `cpu` fails with "No such command or device: cpu", which aborts
    the rest of the script, so RunFor never fired and the run reported NO_TRACE
    as though the driver had made no bus accesses at all."""
    resc = emit_resc(ir)
    assert "sysbus.cpu PerformanceInMips" in resc
    assert "\ncpu " not in resc


def test_delay_trap_uses_the_erratum_cycle_count(ir_delay: PeripheralIR) -> None:
    """The HAL emitted a 16-iteration loop and the mock hardcoded 3. Both now
    read `params['cycles']`, so the driver and its judge cannot disagree."""
    src = emit_peripheral(ir_delay)
    assert "DELAY_REQUIRED     = {0x00: 16}" in src
    # Measured in executed instructions. The workaround is a CPU nop loop, so
    # counting peripheral reads could never observe it and the trap rejected a
    # correct driver -- the failure mode this project calls worse than a miss.
    assert "_insn_since_write()" in src
    assert "ExecutedInstructions" in src
    assert "cycles_since_write" not in src


def test_clock_check_abstains_instead_of_enforcing(ir_clock: PeripheralIR) -> None:
    """The enabling write targets a clock controller outside this IR, so it is
    not observable from inside this address window.

    The old model mapped the erratum's affected_register -- the register the
    erratum PROTECTS -- to a "clock gate" offset and set clock_enabled on a
    write to it, so touching the guarded register was what lifted the guard."""
    src = emit_peripheral(ir_clock)
    assert "SILICONTRUTH_ABSTAIN CLOCK_ENABLE_BEFORE_ACCESS" in src
    assert "CLOCK_PROTECTED_OFFSETS" in src
    # The inverted unlock must not come back.
    assert "clock_enabled" not in src
    assert "CLOCK_NOT_ENABLED" not in src
