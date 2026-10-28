"""Stage 4: cross-reference an errata document against the register IR.

This is the component that justifies the whole project. Anyone can read a
register table. The reason a chatbot cannot do this job is that the
register description on page 412 of the reference manual is *wrong*
unless it is read together with a workaround printed on page 19 of a
different document -- and chunked vector retrieval severs precisely that
link, because the two chunks share almost no vocabulary.

Two guardrails define this module, and both exist because the failure
mode here is not "no workaround" but "a confident wrong workaround":

  1. ErrataConstraint is a CLOSED set. A constraint outside it is
     rejected and logged, never coerced to the nearest member. Coercion
     would turn "we do not know what this erratum requires" into a
     specific code change that nobody can justify.

  2. An erratum must name a register that actually exists in the IR.
     Injecting a delay into a register the datasheet never described
     means writing to an address nobody verified.

An erratum that requires no software action is dropped, which is not a
failure: most errata are hardware limitations. A linker that reports a
constraint for every erratum on the page is over-eager, and over-eager
here means emitting workarounds that correspond to nothing real.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path

from pydantic import ValidationError

from silicontruth.ingest.pdf_render import BBox, render_page
from silicontruth.ir.schema import (
    ErrataConstraint,
    ErrataRule,
    PeripheralIR,
    Provenance,
    Source,
)
from silicontruth.models.provider import Provider

PROMPT_PATH = Path(__file__).parent / "prompts" / "errata_link.md"

# The params each constraint needs in order to generate real code. A
# workaround missing its number is not a workaround: "wait some cycles"
# does not compile.
REQUIRED_PARAMS: dict[ErrataConstraint, tuple[str, ...]] = {
    ErrataConstraint.DELAY_CYCLES_AFTER_WRITE: ("cycles",),
    ErrataConstraint.AVOID_VALUE: ("value",),
    ErrataConstraint.WRITE_ORDER_DEPENDENCY: ("other_register",),
    ErrataConstraint.DUMMY_READ_REQUIRED: (),
    ErrataConstraint.CLOCK_ENABLE_BEFORE_ACCESS: (),
}

INT_PARAMS = {"cycles", "ns", "us", "value"}

ERRATA_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "errata": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "errata_id": {"type": "string"},
                    "title": {"type": "string"},
                    "affected_register": {"type": "string"},
                    "constraint": {"type": "string"},
                    "cycles": {"type": "string"},
                    "ns": {"type": "string"},
                    "us": {"type": "string"},
                    "value": {"type": "string"},
                    "other_register": {"type": "string"},
                    "field": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": [
                    "errata_id",
                    "title",
                    "affected_register",
                    "constraint",
                    "cycles",
                    "ns",
                    "us",
                    "value",
                    "other_register",
                    "field",
                    "quote",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["errata"],
    "additionalProperties": False,
}


@dataclass
class Rejection:
    """An erratum that was read but not applied, and exactly why.

    Surfaced rather than swallowed: "we found this and chose not to act on
    it" is information an engineer needs, and it is the difference between
    a tool that is silent and one that is trustworthy.
    """

    errata_id: str
    title: str
    reason: str

    def __str__(self) -> str:
        return f"[{self.errata_id}] {self.title}: {self.reason}"


@dataclass
class LinkReport:
    rules: list[ErrataRule] = dc_field(default_factory=list)
    rejected: list[Rejection] = dc_field(default_factory=list)
    raw: dict = dc_field(default_factory=dict)

    @property
    def applied_ids(self) -> list[str]:
        return [r.errata_id for r in self.rules]


def _split_register(register: str) -> tuple[str, str]:
    """"USART_CR1" -> ("USART", "CR1"). Bare "CR1" -> ("", "CR1").

    Datasheets qualify register names by peripheral; the IR stores the
    register's own name.
    """
    r = register.strip()
    if "_" in r:
        prefix, short = r.split("_", 1)
        return prefix, short
    return "", r


def _peripheral_base(name: str) -> str:
    """"USART1" -> "USART", "SPI2" -> "SPI". Instance number removed."""
    return re.sub(r"\d+$", "", name.strip()).upper()


def _match_register(
    register: str, ir: PeripheralIR, known: dict
) -> tuple[str, str | None]:
    """Resolve an errata register name against the IR.

    Returns (short_name, rejection_reason). The prefix check is NOT
    cosmetic: stripping it blindly maps "SPI2_CR1" onto this peripheral's
    "CR1", so an erratum belonging to an entirely different peripheral
    would be applied here -- injecting a delay, or a forbidden value, into
    a register the erratum never mentioned. Same register name, different
    silicon block.
    """
    prefix, short = _split_register(register)
    if not short:
        return "", "names no affected register"
    if prefix and _peripheral_base(prefix) != _peripheral_base(ir.peripheral):
        return short, (
            f"belongs to peripheral {prefix!r}, but this IR describes "
            f"{ir.peripheral!r}; refusing to apply it to {short!r} here"
        )
    if short not in known:
        return short, (
            f"affects register {short!r}, which is not in the IR "
            f"(known: {sorted(known)})"
        )
    return short, None


def _parse_param(key: str, raw: str) -> int | str:
    """Params arrive as printed strings. Numbers are parsed HERE, in
    Python, for the same reason offsets are: a model asked to convert
    '16 APB cycles' to an integer is a model that can return 160."""
    text = (raw or "").strip()
    if key not in INT_PARAMS:
        return text
    cleaned = re.sub(r"[\s_]", "", text)
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", cleaned):
        return int(cleaned, 16)
    m = re.match(r"^(\d+)", cleaned)
    if not m:
        raise ValueError(f"{key}: no number in {raw!r}")
    return int(m.group(1))


def link_errata(
    raw: dict,
    ir: PeripheralIR,
    *,
    page: int,
    bbox: BBox,
) -> LinkReport:
    """Turn a raw errata read into ErrataRules. Pure: no network, no model.

    Everything that can reject an erratum lives here, so the guardrails are
    testable without inference -- which matters, because the guardrails are
    the point.
    """
    report = LinkReport(raw=raw)
    known = {r.name: r for r in ir.registers}

    items = raw.get("errata")
    if not isinstance(items, list):
        return report

    valid = {c.value for c in ErrataConstraint}
    seen: set[str] = set()

    for item in items:
        eid = str(item.get("errata_id") or "").strip() or "<no id>"
        title = str(item.get("title") or "").strip()
        constraint_raw = str(item.get("constraint") or "").strip().lower()

        if eid in seen:
            report.rejected.append(
                Rejection(eid, title, "duplicate errata_id on the same page")
            )
            continue
        seen.add(eid)

        # Most errata are hardware limitations needing no software action.
        # Dropping them is correct behaviour, not a miss.
        if constraint_raw in ("", "none", "null"):
            report.rejected.append(
                Rejection(eid, title, "no software workaround required")
            )
            continue

        # GUARDRAIL 1: the closed set. Not coerced to the nearest member --
        # "we do not know what this requires" must not become a specific
        # code change nobody can justify.
        if constraint_raw not in valid:
            report.rejected.append(
                Rejection(
                    eid,
                    title,
                    f"constraint {constraint_raw!r} is outside the supported set "
                    f"{sorted(valid)}; rejected rather than coerced",
                )
            )
            continue
        constraint = ErrataConstraint(constraint_raw)

        # GUARDRAIL 2: the register must exist in the IR, and must belong to
        # THIS peripheral. A workaround on a register nobody described
        # writes to an address nobody verified.
        affected, why = _match_register(
            str(item.get("affected_register") or ""), ir, known
        )
        if why:
            report.rejected.append(Rejection(eid, title, why))
            continue

        # The numbers the workaround depends on.
        params: dict[str, int | str] = {}
        bad = False
        for key in ("cycles", "ns", "us", "value", "other_register", "field"):
            raw_val = str(item.get(key) or "").strip()
            if not raw_val:
                continue
            try:
                params[key] = _parse_param(key, raw_val)
            except ValueError as e:
                report.rejected.append(Rejection(eid, title, str(e)))
                bad = True
                break
        if bad:
            continue

        missing = [k for k in REQUIRED_PARAMS[constraint] if k not in params]
        if missing:
            # "wait some cycles" does not compile. Better to report the
            # erratum as unapplied than to invent a plausible number.
            report.rejected.append(
                Rejection(
                    eid,
                    title,
                    f"{constraint.value} requires {missing} but the page did "
                    "not state it",
                )
            )
            continue

        if constraint is ErrataConstraint.WRITE_ORDER_DEPENDENCY:
            other, why = _match_register(
                str(params.get("other_register", "")), ir, known
            )
            if why:
                report.rejected.append(
                    Rejection(eid, title, f"ordering depends on a register that {why}")
                )
                continue
            params["other_register"] = other

        try:
            report.rules.append(
                ErrataRule(
                    errata_id=eid,
                    title=title,
                    affected_register=affected,
                    constraint=constraint,
                    params=params,
                    provenance=Provenance(
                        page=page,
                        bbox=(
                            float(bbox[0]),
                            float(bbox[1]),
                            float(bbox[2]),
                            float(bbox[3]),
                        ),
                        source=Source.ERRATA,
                        errata_id=eid,
                    ),
                )
            )
        except ValidationError as e:
            report.rejected.append(Rejection(eid, title, f"schema rejected it: {e}"))

    return report


def extract_errata(
    provider: Provider,
    ir: PeripheralIR,
    pdf: Path | str,
    page_number: int,
    *,
    dpi: int = 200,
    max_tokens: int = 12288,
) -> LinkReport:
    """Read one errata page and link it against the IR."""
    provider.require_vision()
    rp = render_page(pdf, page_number, dpi=dpi)
    uri = "data:image/png;base64," + base64.b64encode(rp.png).decode()
    raw = provider.extract(
        PROMPT_PATH.read_text(encoding="utf-8"),
        schema=ERRATA_SCHEMA,
        images=[uri],
        max_tokens=max_tokens,
    )
    return link_errata(
        raw,
        ir,
        page=page_number,
        bbox=(0.0, 0.0, float(rp.width), float(rp.height)),
    )


def apply_to_ir(ir: PeripheralIR, report: LinkReport) -> PeripheralIR:
    """Attach the linked rules to the IR.

    Replaces rather than appends: re-running the linker on the same page
    should be idempotent, not accumulate duplicate workarounds.
    """
    ir.errata = list(report.rules)
    return ir
