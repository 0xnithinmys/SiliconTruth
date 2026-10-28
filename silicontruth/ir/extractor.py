"""Stage 3: a rendered page -> a PeripheralIR, with no arithmetic by the model.

The division of labour here IS the project's thesis, so it is worth
stating plainly:

    The model reports only what is PRINTED.  Strings, as printed.
    Python performs every calculation.       Hex parsing, widths, masks.
    Z3 decides whether the result is sound.  This module never judges.

So extract_register asks for offset_hex as the literal string on the page
and parses it here; it asks for msb and lsb and computes width here. A
model that is never asked to do arithmetic cannot get arithmetic wrong,
and what remains -- did it read the right digits -- is exactly what the
width-conservation check can catch.

Note what this module deliberately does NOT do: it does not repair, fill
in, or drop anything. An extraction that misses bit 7 is passed through
to the auditor intact, because a gap that Z3 names is a caught bug, while
a gap this module quietly patched is a shipped one.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path

from pydantic import ValidationError

from silicontruth.ingest.pdf_render import BBox, RenderedPage, crop_png, render_page
from silicontruth.ir.schema import (
    BitField,
    PeripheralIR,
    Provenance,
    Register,
    Source,
)
from silicontruth.models.provider import Provider

PROMPT_PATH = Path(__file__).parent / "prompts" / "register_table.md"

VALID_ACCESS = {"rw", "ro", "wo", "rc_w0", "rc_w1", "w1c"}

# Strict json_schema for the extraction. Every property is required and
# additionalProperties is false, because a model allowed to invent a key is
# a model whose output cannot be validated.
# One register object. Kept as its own schema because the page-level schema
# below is just a list of these, and the retry loop re-reads exactly one.
REGISTER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "register_name": {"type": "string"},
        "offset_hex": {"type": "string"},
        "reset_value_hex": {"type": "string"},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "msb": {"type": "integer"},
                    "lsb": {"type": "integer"},
                    "access": {"type": "string"},
                    "reserved": {"type": "boolean"},
                    "description": {"type": "string"},
                    # Layout B prints a reset per field and none for the
                    # register. Asking for it here is what lets those pages
                    # be read at all.
                    "reset_hex": {"type": "string"},
                },
                "required": [
                    "name",
                    "msb",
                    "lsb",
                    "access",
                    "reserved",
                    "description",
                    "reset_hex",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["register_name", "offset_hex", "reset_value_hex", "fields"],
    "additionalProperties": False,
}

# What a page returns: every register documented on it.
#
# A real datasheet page carries several -- RP2040 page 433 holds UARTFBRD and
# UARTLCR_H -- and reading one per page threw the rest away. Every synthetic
# benchmark page happens to carry exactly one register, which is why this
# went unnoticed until a real document was tried.
PAGE_SCHEMA: dict = {
    "type": "object",
    "properties": {"registers": {"type": "array", "items": REGISTER_SCHEMA}},
    "required": ["registers"],
    "additionalProperties": False,
}

# Back-compat alias: the retry loop and the tests name this one.
EXTRACTION_SCHEMA = REGISTER_SCHEMA


class ExtractionError(RuntimeError):
    """The response could not be turned into IR at all.

    Distinct from a Z3 violation: this means the output was unusable, not
    that the register was described incorrectly.
    """


@dataclass
class ExtractionReport:
    """What happened, in enough detail to debug a bad read.

    warnings holds things that are suspicious but not fatal. They do not
    stop the IR being built, because stopping here would pre-empt the
    auditor, which is the component actually qualified to decide.
    """

    register: Register
    raw: dict
    warnings: list[str] = dc_field(default_factory=list)


def parse_hex(text: str, *, what: str) -> int:
    """Parse a hex literal as printed in a datasheet.

    Datasheets group hex digits for legibility -- "0x0000 0000",
    "0x4001_1000" -- and a reset value that silently parses to the wrong
    number is precisely the class of defect this project exists to stop.
    So this is strict: it accepts the grouping characters datasheets
    actually use, and rejects everything else loudly.
    """
    if not isinstance(text, str):
        raise ExtractionError(f"{what}: expected a string, got {type(text).__name__}")
    cleaned = re.sub(r"[\s_]", "", text.strip())
    if not re.fullmatch(r"0[xX][0-9a-fA-F]+", cleaned):
        raise ExtractionError(f"{what}: not a hex literal: {text!r}")
    return int(cleaned, 16)


def normalise_access(raw: str, *, reserved: bool) -> tuple[str, str | None]:
    """Map a printed access letter to SVD vocabulary.

    Returns (access, warning). Reserved cells are conventionally printed as
    a bare "r", which is "ro". Anything unrecognised becomes "rw" with a
    warning rather than an exception, because access is not Z3-provable in
    the first place -- it is the Renode oracle's job to catch it, and
    raising here would stop the pipeline before that oracle ever runs.
    """
    a = (raw or "").strip().lower()
    if a in VALID_ACCESS:
        return a, None
    if a == "r":
        return "ro", None
    if a == "w":
        return "wo", None
    if reserved and not a:
        return "ro", None
    return "rw", (
        f"access {raw!r} is not an SVD access mode; defaulted to 'rw'. "
        "Access is not provable by Z3 -- the Renode oracle decides this one."
    )


def _provenance(page: int, bbox: BBox, mask_id: str | None = None) -> Provenance:
    """Filled in Python from crop metadata.

    The model is never asked where it looked: that answer would have to be
    believed, whereas this one can be checked.
    """
    return Provenance(
        page=page,
        bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
        source=Source.DATASHEET,
        mask_id=mask_id,
    )


def build_register(
    raw: dict,
    *,
    page: int,
    bbox: BBox,
    width: int = 32,
    mask_id: str | None = None,
) -> ExtractionReport:
    """Turn a raw response into a Register. Pure: no network, no model.

    Separated from the call so the whole translation layer -- hex parsing,
    access mapping, provenance -- is testable without inference.
    """
    warnings: list[str] = []

    name = str(raw.get("register_name") or "").strip()
    if not name:
        raise ExtractionError("register_name missing from response")
    # Datasheets print "USART_CR1"; SVD wants the register's own name.
    short = name.split("_", 1)[1] if "_" in name else name

    offset = parse_hex(raw.get("offset_hex", ""), what="offset_hex")
    # An ABSENT reset value is not a broken page.
    #
    # ST prints "Reset value: 0x0000 0000" once per register. ARM PrimeCell
    # documents -- the RP2040 datasheet among them -- print a reset per FIELD
    # and nothing per register, so the model correctly returns "" and the
    # whole page used to be discarded with `not a hex literal: ''`. Measured:
    # that threw away two of three real pages and four of five registers.
    #
    # It is recorded as unknown rather than defaulted silently, because
    # `reset_value` defaults to 0 and gate 1's reserved-bit constraint is
    # `reset & reserved_mask == 0` -- which 0 satisfies always. See
    # Register.reset_value_known.
    raw_reset = str(raw.get("reset_value_hex") or "").strip()
    reset_known = bool(raw_reset)
    reset = parse_hex(raw_reset, what="reset_value_hex") if reset_known else 0
    if not reset_known:
        warnings.append(
            "no register-level reset value printed on this page; the "
            "reserved-bit check will report as not run rather than pass"
        )

    raw_fields = raw.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ExtractionError(f"{name}: response contained no fields")

    prov = _provenance(page, bbox, mask_id)
    fields: list[BitField] = []
    for i, f in enumerate(raw_fields):
        fname = str(f.get("name") or "").strip()
        if not fname:
            warnings.append(f"field {i} has no name; kept as FIELD_{i}")
            fname = f"FIELD_{i}"
        if bool(f.get("reserved")):
            # Datasheets print every reserved run as "Res.", so a register
            # with three of them yields three identically-named fields --
            # and "Res." is not a C identifier either. Rename to something
            # unique and legal. This touches the NAME only: msb and lsb are
            # untouched, so the bits these fields account for still reach
            # the width-conservation check exactly as read.
            fname = f"RESERVED_{f.get('msb')}_{f.get('lsb')}"
        try:
            msb, lsb = int(f["msb"]), int(f["lsb"])
        except (KeyError, TypeError, ValueError) as e:
            raise ExtractionError(f"{name}.{fname}: bad msb/lsb: {e}") from e

        reserved = bool(f.get("reserved"))
        if msb < lsb:
            # NOT swapped. The obvious "fix" is to exchange the two numbers
            # so the field looks sane, and that is precisely how a wrong
            # driver ships: the repair invents a field nobody read off the
            # page. The IR contract cannot represent msb < lsb anyway, so
            # the only honest outcomes are to re-read the region (what the
            # retry loop does with this exception) or to mark the register
            # UNVERIFIED. Both are better than a plausible guess.
            raise ExtractionError(
                f"{name}.{fname}: msb {msb} < lsb {lsb}; the read is "
                "untrustworthy. Re-read the region rather than swapping them."
            )
        access, w = normalise_access(str(f.get("access", "")), reserved=reserved)
        if w:
            warnings.append(f"{fname}: {w}")

        try:
            fields.append(
                BitField(
                    name=fname,
                    lsb=lsb,
                    msb=msb,
                    access=access,  # type: ignore[arg-type]
                    description=str(f.get("description") or ""),
                    reserved=reserved,
                    provenance=prov,
                )
            )
        except ValidationError as e:
            # The schema is the contract. Anything it refuses is an
            # unusable read, surfaced as ExtractionError so callers need
            # only know about one exception type.
            raise ExtractionError(f"{name}.{fname}: {e}") from e

    try:
        register = Register(
            name=short,
            offset=offset,
            width=width,  # type: ignore[arg-type]
            reset_value=reset,
            reset_value_known=reset_known,
            access="rw",
            fields=fields,
            provenance=prov,
            verified=False,  # Only the Z3 auditor may set this.
        )
    except ValidationError as e:
        raise ExtractionError(f"{name}: {e}") from e
    return ExtractionReport(register=register, raw=raw, warnings=warnings)


def extract_register(
    provider: Provider,
    pdf: Path | str,
    page_number: int,
    *,
    bbox: BBox | None = None,
    dpi: int = 200,
    width: int = 32,
    max_tokens: int = 8192,
    mask_id: str | None = None,
    rendered: RenderedPage | None = None,
) -> ExtractionReport:
    """Read one register description off one page.

    bbox is in PDF points. When given, only that region is sent -- which is
    what the Z3 retry loop uses to re-read a single failing table row at
    higher DPI instead of re-reading the whole page.
    """
    provider.require_vision()
    rp = rendered or render_page(pdf, page_number, dpi=dpi)
    if bbox is None:
        png = rp.png
        region: BBox = (0.0, 0.0, float(rp.width), float(rp.height))
    else:
        png = crop_png(rp, bbox)
        region = bbox

    uri = "data:image/png;base64," + base64.b64encode(png).decode()
    raw = provider.extract(
        PROMPT_PATH.read_text(encoding="utf-8"),
        schema=EXTRACTION_SCHEMA,
        images=[uri],
        max_tokens=max_tokens,
    )
    return build_register(
        raw, page=page_number, bbox=region, width=width, mask_id=mask_id
    )


def to_ir(
    reports: list[ExtractionReport],
    *,
    chip: str,
    peripheral: str,
    base_address: int,
) -> PeripheralIR:
    """Assemble registers into the IR the auditor consumes.

    base_address is supplied by the caller, never by the model: adding a
    base to an offset is arithmetic, and arithmetic belongs in
    Register.absolute_address(), where Z3 can check it.
    """
    return PeripheralIR(
        chip=chip,
        peripheral=peripheral,
        base_address=base_address,
        registers=[r.register for r in reports],
    )
