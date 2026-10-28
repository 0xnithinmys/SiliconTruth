"""Tests for the page -> IR translation layer.

build_register is pure, so everything the model's output has to survive --
hex grouping, access letters, missing keys, transposed bit pairs -- is
testable with no network and no credentials.

The central assertion running through these: the extractor must NOT
repair anything. A bad read has to reach the auditor intact. A gap that
Z3 names is a caught bug; a gap the extractor quietly patched is a
shipped one.
"""

from __future__ import annotations

import pytest

from silicontruth.ir.extractor import (
    ExtractionError,
    build_register,
    normalise_access,
    parse_hex,
    to_ir,
)
from silicontruth.verify.z3_register_audit import audit

BBOX = (0.0, 0.0, 595.0, 842.0)


def raw(**over) -> dict:
    """A correct USART_CR1 read, as the model actually returns one."""
    body = {
        "register_name": "USART_CR1",
        "offset_hex": "0x00",
        "reset_value_hex": "0x0000 0000",
        "fields": [
            {
                "name": "RESERVED_31_29",
                "msb": 31,
                "lsb": 29,
                "access": "r",
                "reserved": True,
                "description": "Reserved.",
            },
            {
                "name": "DEAT",
                "msb": 28,
                "lsb": 1,
                "access": "rw",
                "reserved": False,
                "description": "Driver Enable assertion time.",
            },
            {
                "name": "UE",
                "msb": 0,
                "lsb": 0,
                "access": "rw",
                "reserved": False,
                "description": "USART enable.",
            },
        ],
    }
    body.update(over)
    return body


# --- hex, as datasheets actually print it ---------------------------------


@pytest.mark.parametrize(
    "text,want",
    [
        ("0x00", 0),
        ("0x0000 0000", 0),
        ("0x4001_1000", 0x40011000),
        ("  0X40011000  ", 0x40011000),
        ("0xDEADBEEF", 0xDEADBEEF),
    ],
)
def test_parse_hex_accepts_datasheet_grouping(text, want):
    assert parse_hex(text, what="t") == want


@pytest.mark.parametrize("text", ["", "0x", "40011000", "0xGGGG", "zero", "0o17"])
def test_parse_hex_rejects_anything_else(text):
    """A reset value that silently parses to the wrong number is exactly
    the defect class this project exists to stop, so parsing is strict."""
    with pytest.raises(ExtractionError):
        parse_hex(text, what="t")


def test_parse_hex_rejects_non_strings():
    with pytest.raises(ExtractionError):
        parse_hex(None, what="t")  # type: ignore[arg-type]


def test_parse_hex_does_not_accept_decimal_lookalikes():
    """"1000" is 0x1000 only if someone guessed. It must not parse."""
    with pytest.raises(ExtractionError):
        parse_hex("1000", what="offset_hex")


# --- access ---------------------------------------------------------------


def test_bare_r_on_a_reserved_cell_is_read_only():
    assert normalise_access("r", reserved=True) == ("ro", None)


def test_unknown_access_warns_rather_than_raising():
    """Raising here would stop the pipeline before the Renode oracle --
    the only component that can actually catch an access error -- runs."""
    access, warning = normalise_access("??", reserved=False)
    assert access == "rw"
    assert warning and "Renode" in warning


def test_all_svd_access_modes_pass_through():
    for a in ("rw", "ro", "wo", "rc_w0", "rc_w1", "w1c"):
        assert normalise_access(a, reserved=False) == (a, None)


# --- building the register ------------------------------------------------


def test_builds_a_register_from_a_clean_read():
    rep = build_register(raw(), page=412, bbox=BBOX)
    r = rep.register
    assert r.name == "CR1"  # USART_CR1 -> CR1
    assert r.offset == 0
    assert r.reset_value == 0
    assert [f.name for f in r.fields] == ["RESERVED_31_29", "DEAT", "UE"]
    assert rep.warnings == []


def test_a_fresh_register_is_never_born_verified():
    """Only the Z3 auditor may set verified. If extraction could set it,
    the gate would be bypassable by a confident model."""
    assert build_register(raw(), page=1, bbox=BBOX).register.verified is False


def test_offset_is_parsed_not_computed():
    rep = build_register(raw(offset_hex="0x0C"), page=1, bbox=BBOX)
    assert rep.register.offset == 0x0C


def test_absolute_address_is_computed_in_python():
    """The model is never asked for base + offset. This is the check that
    the arithmetic stayed on our side of the line."""
    rep = build_register(raw(offset_hex="0x0C"), page=1, bbox=BBOX)
    assert rep.register.absolute_address(0x40011000) == 0x4001100C


def test_provenance_comes_from_the_crop_not_the_model():
    rep = build_register(raw(), page=412, bbox=(10.0, 20.0, 30.0, 40.0))
    p = rep.register.provenance
    assert p.page == 412
    assert p.bbox == (10.0, 20.0, 30.0, 40.0)


def test_mask_id_is_carried_through_for_the_ui_overlay():
    rep = build_register(raw(), page=1, bbox=BBOX, mask_id="m7")
    assert rep.register.provenance.mask_id == "m7"


# --- refusing to repair ---------------------------------------------------


def test_transposed_bits_are_rejected_not_swapped():
    """The tempting "fix" is to exchange the two numbers so the field
    looks sane. That invents a field nobody read off the page, and the IR
    contract cannot represent msb < lsb anyway -- so the read is refused
    and the region is re-read instead."""
    bad = raw()
    bad["fields"][1]["msb"] = 1
    bad["fields"][1]["lsb"] = 28
    with pytest.raises(ExtractionError) as e:
        build_register(bad, page=1, bbox=BBOX)
    assert "msb 1 < lsb 28" in str(e.value)
    assert "swapping" in str(e.value)


def test_a_gap_in_the_bits_survives_to_the_auditor():
    """The end-to-end point of this module: a dropped bit must still be
    there when Z3 looks, so Z3 can name it."""
    holed = raw()
    holed["fields"][1]["lsb"] = 2  # bit 1 now belongs to nothing
    rep = build_register(holed, page=1, bbox=BBOX)
    ir = to_ir([rep], chip="synthetic", peripheral="USART1", base_address=0x40011000)

    result = audit(ir)
    assert not result.passed
    assert any(v.constraint == "width_conservation" for v in result.violations)


def test_a_correct_read_passes_the_auditor():
    rep = build_register(raw(), page=1, bbox=BBOX)
    ir = to_ir([rep], chip="synthetic", peripheral="USART1", base_address=0x40011000)
    result = audit(ir)
    assert result.passed, [str(v) for v in result.violations]


# --- unusable responses ---------------------------------------------------


def test_missing_register_name_is_fatal():
    with pytest.raises(ExtractionError):
        build_register(raw(register_name=""), page=1, bbox=BBOX)


def test_no_fields_is_fatal():
    with pytest.raises(ExtractionError):
        build_register(raw(fields=[]), page=1, bbox=BBOX)


def test_missing_bit_numbers_are_fatal():
    bad = raw()
    del bad["fields"][0]["msb"]
    with pytest.raises(ExtractionError):
        build_register(bad, page=1, bbox=BBOX)


def test_unnamed_field_is_kept_and_flagged():
    """Not fatal: a nameless field still occupies bits, and the auditor
    needs those bits to check width conservation."""
    anon = raw()
    anon["fields"][2]["name"] = ""
    rep = build_register(anon, page=1, bbox=BBOX)
    assert rep.register.fields[2].name == "FIELD_2"
    assert any("no name" in w for w in rep.warnings)


def test_to_ir_takes_the_base_address_from_the_caller():
    rep = build_register(raw(), page=1, bbox=BBOX)
    ir = to_ir([rep], chip="c", peripheral="P", base_address=0x50000000)
    assert ir.base_address == 0x50000000
    assert ir.registers[0].absolute_address(ir.base_address) == 0x50000000


def test_reserved_runs_get_unique_legal_names():
    """Datasheets print every reserved run as "Res.", so a register with
    three of them yields three identically-named fields -- and "Res." is
    not a C identifier. Renaming is naming only; the bits must survive."""
    r = raw()
    r["fields"][0]["name"] = "Res."
    rep = build_register(r, page=1, bbox=BBOX)
    f = rep.register.fields[0]
    assert f.name == "RESERVED_31_29"
    assert (f.msb, f.lsb) == (31, 29)  # bits untouched


def test_two_reserved_runs_do_not_collide():
    r = raw()
    r["fields"] = [
        {"name": "Res.", "msb": 31, "lsb": 29, "access": "r",
         "reserved": True, "description": ""},
        {"name": "DEAT", "msb": 28, "lsb": 2, "access": "rw",
         "reserved": False, "description": ""},
        {"name": "Res.", "msb": 1, "lsb": 0, "access": "r",
         "reserved": True, "description": ""},
    ]
    names = [f.name for f in build_register(r, page=1, bbox=BBOX).register.fields]
    assert names == ["RESERVED_31_29", "DEAT", "RESERVED_1_0"]
    assert len(set(names)) == 3
