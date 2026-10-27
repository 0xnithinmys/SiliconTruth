"""T-075/T-076 — SVD emission and structural validation.

The load-bearing test here is test_unverified_registers_are_never_emitted:
it proves invariant #1 holds at the codegen boundary, not just in the audit.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from silicontruth.ir.schema import BitField, PeripheralIR, Provenance, Source
from silicontruth.synth.svd_emitter import (
    SvdEmitError,
    emit_svd,
    validate_svd,
)
from silicontruth.verify.z3_register_audit import audit

FIXTURE = Path(__file__).parent / "fixtures" / "usart1_valid.json"


@pytest.fixture
def ir() -> PeripheralIR:
    return PeripheralIR.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def verified_ir(ir: PeripheralIR) -> PeripheralIR:
    result = audit(ir)
    assert result.passed
    return ir


@pytest.fixture
def svd(verified_ir: PeripheralIR) -> str:
    return emit_svd(verified_ir, vendor="STMicroelectronics")


# ---------------------------------------------------------------------------
# The gate: nothing unproved gets out
# ---------------------------------------------------------------------------


def test_emitting_unaudited_ir_fails_loudly(ir: PeripheralIR) -> None:
    """No audit run means nothing is verified, so there is nothing to emit."""
    with pytest.raises(SvdEmitError, match="no verified registers"):
        emit_svd(ir)


def test_unverified_registers_are_never_emitted(ir: PeripheralIR) -> None:
    """INVARIANT #1 at the codegen boundary.

    Corrupt one register, audit, emit. The corrupt register must be absent from
    the SVD while its siblings are present.
    """
    brr = ir.register_by_name("BRR")
    assert brr is not None
    brr.offset = 0x03  # unaligned -> fails the gate

    result = audit(ir)
    assert not result.passed
    assert not brr.verified

    xml_text = emit_svd(ir)
    names = {e.text for e in ET.fromstring(xml_text).iter("name")}
    assert "BRR" not in names, "an unverified register reached the SVD"
    assert "CR1" in names and "CR2" in names, "verified siblings were dropped too"


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_emitted_svd_is_well_formed(svd: str) -> None:
    root = ET.fromstring(svd)
    assert root.tag == "device"
    assert svd.startswith('<?xml version="1.0" encoding="utf-8"?>')


def test_emitted_svd_passes_validation(svd: str) -> None:
    v = validate_svd(svd)
    assert v.ok, f"validation errors: {v.errors}"


def test_base_address_and_offsets_are_hex(svd: str) -> None:
    root = ET.fromstring(svd)
    base = root.find(".//peripheral/baseAddress")
    assert base is not None and base.text == "0x40011000"
    offsets = [e.text for e in root.iter("addressOffset")]
    assert all(o.startswith("0x") for o in offsets), offsets
    assert "0x0" in offsets and "0x4" in offsets and "0xC" in offsets


def test_registers_are_sorted_by_offset(svd: str) -> None:
    root = ET.fromstring(svd)
    offs = [int(r.find("addressOffset").text, 0) for r in root.iter("register")]
    assert offs == sorted(offs)


def test_bitrange_format(svd: str) -> None:
    root = ET.fromstring(svd)
    ranges = [e.text for e in root.iter("bitRange")]
    assert ranges
    for r in ranges:
        assert r.startswith("[") and ":" in r and r.endswith("]"), r
    # DEDT is [20:16] in the fixture.
    assert "[20:16]" in ranges


def test_reserved_fields_are_not_emitted(svd: str) -> None:
    """SVD treats undeclared bits as reserved, and svd2rust warns on explicit
    reserved fields. They still count in the Z3 width proof."""
    root = ET.fromstring(svd)
    names = [e.text for e in root.iter("name")]
    assert not any(n and n.startswith("RESERVED_") for n in names), names


def test_live_fields_survive(svd: str) -> None:
    root = ET.fromstring(svd)
    names = {e.text for e in root.iter("name")}
    for expected in ("UE", "TE", "RE", "OVER8", "DEDT", "DEAT", "M1"):
        assert expected in names, f"{expected} missing from SVD"


def test_access_is_translated_to_svd_vocabulary(svd: str) -> None:
    root = ET.fromstring(svd)
    accesses = {e.text for e in root.iter("access")}
    assert accesses <= {"read-write", "read-only", "write-only"}, accesses


def test_address_block_spans_the_registers(svd: str) -> None:
    root = ET.fromstring(svd)
    size = int(root.find(".//addressBlock/size").text, 0)
    # BRR at 0x0C is 4 bytes wide, so the block must reach at least 0x10.
    assert size >= 0x10


# ---------------------------------------------------------------------------
# Modified-write semantics
# ---------------------------------------------------------------------------


def test_clear_on_write_emits_modified_write_values(verified_ir: PeripheralIR) -> None:
    """rc_w0 has no numeric contradiction for Z3, but it does change generated
    code, so it must survive into the SVD."""
    cr1 = verified_ir.register_by_name("CR1")
    assert cr1 is not None
    ue = next(f for f in cr1.fields if f.name == "UE")
    object.__setattr__(ue, "access", "rc_w0")

    root = ET.fromstring(emit_svd(verified_ir))
    ue_el = next(
        f for f in root.iter("field") if f.find("name") is not None and f.find("name").text == "UE"
    )
    mw = ue_el.find("modifiedWriteValues")
    assert mw is not None and mw.text == "zeroToClear"


# ---------------------------------------------------------------------------
# Identifier safety
# ---------------------------------------------------------------------------


def test_invalid_c_identifier_is_rejected(verified_ir: PeripheralIR) -> None:
    """svd2rust turns these into symbols; a space or hyphen breaks the build."""
    cr1 = verified_ir.register_by_name("CR1")
    assert cr1 is not None
    cr1.fields.append(
        BitField(
            name="BAD NAME",
            lsb=0,
            msb=0,
            access="rw",
            provenance=Provenance(
                page=1, bbox=(0.0, 0.0, 1.0, 1.0), source=Source.DATASHEET
            ),
        )
    )
    with pytest.raises(SvdEmitError, match="valid C identifier"):
        emit_svd(verified_ir)


# ---------------------------------------------------------------------------
# The validator must actually reject bad input
# ---------------------------------------------------------------------------


def test_validator_rejects_malformed_xml() -> None:
    v = validate_svd("<device><unclosed>")
    assert not v.ok and "well-formed" in v.errors[0]


def test_validator_rejects_wrong_root() -> None:
    v = validate_svd("<peripherals/>")
    assert not v.ok
    assert any("expected <device>" in e for e in v.errors)


def test_validator_catches_overlapping_bitranges() -> None:
    xml_text = """<?xml version="1.0"?>
    <device><name>X</name><version>1.0</version><addressUnitBits>8</addressUnitBits>
    <width>32</width><peripherals><peripheral><name>P</name>
    <baseAddress>0x0</baseAddress><registers><register>
    <name>R</name><addressOffset>0x0</addressOffset><size>32</size>
    <fields>
      <field><name>A</name><bitRange>[7:0]</bitRange></field>
      <field><name>B</name><bitRange>[3:2]</bitRange></field>
    </fields></register></registers></peripheral></peripherals></device>"""
    v = validate_svd(xml_text)
    assert not v.ok
    assert any("overlaps" in e for e in v.errors), v.errors


def test_validator_catches_bit_beyond_register_width() -> None:
    xml_text = """<?xml version="1.0"?>
    <device><name>X</name><version>1.0</version><addressUnitBits>8</addressUnitBits>
    <width>32</width><peripherals><peripheral><name>P</name>
    <baseAddress>0x0</baseAddress><registers><register>
    <name>R</name><addressOffset>0x0</addressOffset><size>16</size>
    <fields><field><name>A</name><bitRange>[20:16]</bitRange></field></fields>
    </register></registers></peripheral></peripherals></device>"""
    v = validate_svd(xml_text)
    assert not v.ok
    assert any("exceeds" in e for e in v.errors), v.errors


def test_validator_catches_duplicate_offsets() -> None:
    xml_text = """<?xml version="1.0"?>
    <device><name>X</name><version>1.0</version><addressUnitBits>8</addressUnitBits>
    <width>32</width><peripherals><peripheral><name>P</name>
    <baseAddress>0x0</baseAddress><registers>
    <register><name>A</name><addressOffset>0x0</addressOffset><size>32</size></register>
    <register><name>B</name><addressOffset>0x0</addressOffset><size>32</size></register>
    </registers></peripheral></peripherals></device>"""
    v = validate_svd(xml_text)
    assert not v.ok
    assert any("duplicate" in e for e in v.errors), v.errors


def test_validator_catches_bad_bitrange_syntax() -> None:
    xml_text = """<?xml version="1.0"?>
    <device><name>X</name><version>1.0</version><addressUnitBits>8</addressUnitBits>
    <width>32</width><peripherals><peripheral><name>P</name>
    <baseAddress>0x0</baseAddress><registers><register>
    <name>R</name><addressOffset>0x0</addressOffset><size>32</size>
    <fields><field><name>A</name><bitRange>7-0</bitRange></field></fields>
    </register></registers></peripheral></peripherals></device>"""
    v = validate_svd(xml_text)
    assert not v.ok
    assert any("[msb:lsb]" in e for e in v.errors), v.errors
