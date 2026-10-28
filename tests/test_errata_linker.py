"""Guardrail tests for the errata cross-reference.

link_errata is pure, so every way an erratum can be refused is testable
with no network. That matters more than usual here, because the failure
mode of this component is not "no workaround" -- it is "a confident wrong
workaround", which compiles, runs, and damages hardware.

The two guardrails under test:
  1. ErrataConstraint is a closed set; anything outside it is rejected,
     never coerced to the nearest member.
  2. An erratum must name a register that exists in the IR.
"""

from __future__ import annotations

import pytest

from silicontruth.ir.errata_linker import link_errata
from silicontruth.ir.extractor import build_register, to_ir
from silicontruth.ir.schema import ErrataConstraint

BBOX = (0.0, 0.0, 595.0, 842.0)


def make_ir(*names: str):
    reports = []
    for i, n in enumerate(names or ("USART_CR1",)):
        reports.append(
            build_register(
                {
                    "register_name": n,
                    "offset_hex": f"0x{i * 4:02X}",
                    "reset_value_hex": "0x0000 0000",
                    "fields": [
                        {
                            "name": "ALL",
                            "msb": 31,
                            "lsb": 0,
                            "access": "rw",
                            "reserved": False,
                            "description": "",
                        }
                    ],
                },
                page=412,
                bbox=BBOX,
            )
        )
    return to_ir(reports, chip="c", peripheral="USART1", base_address=0x40011000)


def item(**over) -> dict:
    base = {
        "errata_id": "2.14.1",
        "title": "Write not taken into account immediately",
        "affected_register": "USART_CR1",
        "constraint": "delay_cycles_after_write",
        "cycles": "16",
        "ns": "",
        "us": "",
        "value": "",
        "other_register": "",
        "quote": "Software must wait 16 APB cycles.",
    }
    base.update(over)
    return base


def link(*items, ir=None):
    return link_errata({"errata": list(items)}, ir or make_ir(), page=19, bbox=BBOX)


# --- the happy path -------------------------------------------------------


def test_links_a_well_formed_erratum():
    r = link(item())
    assert len(r.rules) == 1
    rule = r.rules[0]
    assert rule.constraint is ErrataConstraint.DELAY_CYCLES_AFTER_WRITE
    assert rule.affected_register == "CR1"  # USART_CR1 -> CR1
    assert rule.params["cycles"] == 16  # parsed in Python, not by the model


def test_provenance_records_the_errata_document():
    from silicontruth.ir.schema import Source

    rule = link(item()).rules[0]
    assert rule.provenance.source is Source.ERRATA
    assert rule.provenance.page == 19
    assert rule.provenance.errata_id == "2.14.1"


def test_hex_values_are_parsed_in_python():
    r = link(item(constraint="avoid_value", cycles="", value="0x3F"))
    assert r.rules[0].params["value"] == 0x3F


def test_cycles_with_units_still_parse():
    assert link(item(cycles="16 APB cycles")).rules[0].params["cycles"] == 16


# --- GUARDRAIL 1: the closed set -----------------------------------------


def test_unknown_constraint_is_rejected_not_coerced():
    """The dangerous alternative is snapping to the nearest member.
    'We do not know what this erratum requires' must not silently become
    a specific code change."""
    r = link(item(constraint="recalibrate_the_pll"))
    assert r.rules == []
    assert "rejected rather than coerced" in r.rejected[0].reason


def test_every_supported_constraint_is_accepted():
    cases = {
        "delay_cycles_after_write": {"cycles": "4"},
        "dummy_read_required": {},
        "clock_enable_before_access": {},
        "avoid_value": {"value": "0x3F"},
        "write_order_dependency": {"other_register": "USART_CR2"},
    }
    ir = make_ir("USART_CR1", "USART_CR2")
    for name, extra in cases.items():
        kw = {"constraint": name, "cycles": "", "value": "", "other_register": ""}
        kw.update(extra)
        r = link(item(**kw), ir=ir)
        assert len(r.rules) == 1, (name, [str(x) for x in r.rejected])
        assert r.rules[0].constraint is ErrataConstraint(name)


def test_the_closed_set_is_exactly_what_the_schema_declares():
    """If someone adds a constraint to the enum without teaching the
    linker what params it needs, this fails rather than the linker
    quietly accepting an unimplementable workaround."""
    from silicontruth.ir.errata_linker import REQUIRED_PARAMS

    assert set(REQUIRED_PARAMS) == set(ErrataConstraint)


# --- GUARDRAIL 2: the register must exist --------------------------------


def test_erratum_for_an_unknown_register_is_rejected():
    """A workaround on a register nobody described writes to an address
    nobody verified."""
    r = link(item(affected_register="USART_TDR"))
    assert r.rules == []
    assert "not in the IR" in r.rejected[0].reason


def test_erratum_for_another_peripheral_is_not_applied_here():
    """The hole this closes: stripping the prefix blindly maps SPI2_CR1
    onto this peripheral's CR1, so an erratum for a different silicon
    block would inject a delay into a register it never mentioned. Same
    register name, different peripheral."""
    r = link(item(affected_register="SPI2_CR1"))
    assert r.rules == []
    assert "belongs to peripheral" in r.rejected[0].reason


def test_the_instance_number_does_not_break_a_legitimate_match():
    """USART_CR1 in the errata must still match peripheral USART1."""
    assert len(link(item(affected_register="USART_CR1")).rules) == 1
    assert len(link(item(affected_register="USART1_CR1")).rules) == 1


def test_a_bare_register_name_is_accepted():
    """An erratum that says only "CR1" makes no claim about which
    peripheral, so there is nothing to contradict."""
    assert len(link(item(affected_register="CR1")).rules) == 1


def test_erratum_naming_no_register_is_rejected():
    r = link(item(affected_register=""))
    assert r.rules == []
    assert "names no affected register" in r.rejected[0].reason


def test_write_order_dependency_checks_the_other_register_too():
    r = link(
        item(
            constraint="write_order_dependency",
            cycles="",
            other_register="USART_TDR",
        )
    )
    assert r.rules == []
    assert "ordering depends on" in r.rejected[0].reason


# --- errata that need no action ------------------------------------------


@pytest.mark.parametrize("c", ["none", "", "null"])
def test_errata_requiring_no_software_action_are_dropped(c):
    """Most errata are hardware limitations. Dropping them is correct --
    a linker that emits a constraint for every erratum on the page injects
    workarounds that correspond to nothing real."""
    r = link(item(constraint=c))
    assert r.rules == []
    assert "no software workaround required" in r.rejected[0].reason


# --- incomplete workarounds ----------------------------------------------


def test_delay_without_a_number_is_rejected():
    """"Wait some cycles" does not compile. Reporting the erratum as
    unapplied beats inventing a plausible number."""
    r = link(item(cycles=""))
    assert r.rules == []
    assert "requires ['cycles']" in r.rejected[0].reason


def test_avoid_value_without_a_value_is_rejected():
    r = link(item(constraint="avoid_value", cycles="", value=""))
    assert r.rules == []
    assert "requires ['value']" in r.rejected[0].reason


def test_unparseable_number_is_rejected():
    r = link(item(cycles="several"))
    assert r.rules == []
    assert "no number" in r.rejected[0].reason


# --- hygiene --------------------------------------------------------------


def test_duplicate_errata_ids_are_rejected_once():
    r = link(item(), item())
    assert len(r.rules) == 1
    assert "duplicate" in r.rejected[0].reason


def test_a_malformed_response_yields_nothing_rather_than_crashing():
    assert link_errata({}, make_ir(), page=1, bbox=BBOX).rules == []
    assert link_errata({"errata": "no"}, make_ir(), page=1, bbox=BBOX).rules == []


def test_rejections_are_reported_not_swallowed():
    """'We found this and chose not to act on it' is information an
    engineer needs."""
    r = link(item(constraint="warp_core_breach"), item(affected_register="DMA1_CR"))
    assert len(r.rejected) == 2
    assert all(str(x) for x in r.rejected)


def test_applying_twice_is_idempotent():
    from silicontruth.ir.errata_linker import apply_to_ir

    ir = make_ir()
    r = link(item(), ir=ir)
    apply_to_ir(ir, r)
    apply_to_ir(ir, r)
    assert len(ir.errata) == 1
