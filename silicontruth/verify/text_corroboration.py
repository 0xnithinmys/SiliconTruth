"""Check every extracted name against the page's own text layer.

WHY THIS EXISTS. The Z3 audit proves four arithmetic properties of a
register: aligned address, no overlapping fields, full bit-width
accounting, and a clean reserved reset. Those catch a bit that is dropped
or double-counted. They cannot catch a *consistent relabeling*.

Measured, at 42 DPI on the committed fixture:

    truth              model returned
    EOBIE  [28:28]     M1     [28:28]   <- invented
    RTOIE  [27:27]     EOBIE  [27:27]   <- slid down one
    DEAT   [26:21]     RTOIE  [26:26]   <- slid down one
                       DEAT   [25:21]   <- narrowed to make room

Three fields wrong, one field invented -- and the result still tiles bits
0..31 exactly once with no overlap and no gap. All four Z3 constraints are
genuinely satisfied. The gate passed a wrong read, three times.

That is a false negative, the most serious failure this project can
produce, and it is not fixable inside the solver: there is no arithmetic
contradiction to find. The error is not in the numbers, it is in the
names.

So this module adds the orthogonal check. A field name the model returns
must actually be PRINTED on the page. `M1` appears nowhere in the fixture's
text, so it is caught the moment it is looked for. This is deterministic,
needs no model, and runs in milliseconds.

LIMITS, stated because the check is worthless if its scope is misread:

* It needs a text layer. A scanned manual that is pure raster has none,
  and then this check reports UNAVAILABLE -- never PASS. Claiming
  corroboration from an empty span list would be exactly the kind of
  vacuous pass this module was written to eliminate.
* It validates that a name was printed, not that it was printed in that
  bit position. A relabeling that only swaps two names which both appear
  on the page survives it. Narrowing that gap is what the per-column
  position check (future work) is for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from enum import Enum

from silicontruth.ingest.pdf_render import TextSpan
from silicontruth.ir.schema import PeripheralIR, Register


class Corroboration(str, Enum):
    CORROBORATED = "corroborated"
    VIOLATIONS = "violations"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class NameViolation:
    register: str
    field: str
    detail: str

    def __str__(self) -> str:
        return f"[text_corroboration] {self.register}.{self.field}: {self.detail}"


@dataclass
class CorroborationResult:
    status: Corroboration
    violations: list[NameViolation] = dc_field(default_factory=list)
    checked: int = 0
    reason: str = ""

    @property
    def passed(self) -> bool:
        """UNAVAILABLE is deliberately NOT passed.

        A check that could not run has not been satisfied, and reporting it
        as a pass is how a gate becomes decorative.
        """
        return self.status is Corroboration.CORROBORATED

    def summary(self) -> str:
        if self.status is Corroboration.UNAVAILABLE:
            return f"UNAVAILABLE: {self.reason}"
        if self.status is Corroboration.CORROBORATED:
            return f"PASS: {self.checked} name(s) found in the page text"
        return f"FAIL: {len(self.violations)} name(s) not printed on the page"


def _normalise(text: str) -> str:
    """Datasheet glyph runs arrive with stray punctuation and case."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _vocabulary(spans: list[TextSpan]) -> tuple[set[str], str]:
    """Build both a token set and a flattened string of the page's text.

    Two forms are needed because PyMuPDF hands back spans at CHARACTER
    granularity -- `TextSpan(text='2')` -- so a multi-character name like
    EOBIE is never a span of its own. Reading them individually is how the
    first version of this check came to reject every field on the page,
    including the four that were printed on it.

    `to_reading_order` reassembles characters into lines, which recovers
    tokens for the bit-grid rows. It does not always recover the spaces
    inside running prose ("Controlregister1(USART_CR1)"), so the flattened
    string supports a substring fallback for names that ended up glued to
    a neighbour.
    """
    from silicontruth.ingest.pdf_render import to_reading_order

    text = to_reading_order(spans)
    tokens = {
        n for piece in re.split(r"\s+", text) if (n := _normalise(piece))
    }
    return tokens, _normalise(text)


def corroborate_register(
    register: Register, spans: list[TextSpan]
) -> CorroborationResult:
    """Check this register's field names against the page's printed text."""
    if not spans:
        return CorroborationResult(
            status=Corroboration.UNAVAILABLE,
            reason="no text layer on this page (scanned raster?); "
            "name corroboration cannot run",
        )

    tokens, flat = _vocabulary(spans)
    violations: list[NameViolation] = []
    checked = 0

    for f in register.fields:
        if f.reserved:
            # Reserved runs are renamed RESERVED_<msb>_<lsb> by the
            # extractor, so their names are ours, not the page's. Checking
            # them would be checking our own naming convention.
            continue
        checked += 1
        name = _normalise(f.name)
        # A token match is the strong form. The substring fallback catches
        # names glued to a neighbour by lost inter-word spacing; it is
        # weaker for very short names, which can occur inside longer words,
        # and that weakness is accepted deliberately: a false FAILURE here
        # would block a correct read, which is worse than a missed catch on
        # a two-letter name.
        if name and name not in tokens and name not in flat:
            violations.append(
                NameViolation(
                    register=register.name,
                    field=f.name,
                    detail=(
                        f"the name {f.name!r} does not appear in the text of "
                        f"page {f.provenance.page}; it was not read off the "
                        "page but invented"
                    ),
                )
            )

    status = (
        Corroboration.VIOLATIONS if violations else Corroboration.CORROBORATED
    )
    return CorroborationResult(status=status, violations=violations, checked=checked)


def corroborate(ir: PeripheralIR, spans_by_page: dict[int, list[TextSpan]]):
    """Check an entire IR, page by page.

    Returns a CorroborationResult covering every register. A single page
    with no text layer makes the whole result UNAVAILABLE rather than
    partially passed, because a per-register mixture is too easy to
    misread as a pass.
    """
    all_violations: list[NameViolation] = []
    checked = 0
    for reg in ir.registers:
        spans = spans_by_page.get(reg.provenance.page, [])
        r = corroborate_register(reg, spans)
        if r.status is Corroboration.UNAVAILABLE:
            return CorroborationResult(
                status=Corroboration.UNAVAILABLE,
                reason=f"page {reg.provenance.page}: {r.reason}",
            )
        all_violations.extend(r.violations)
        checked += r.checked

    status = (
        Corroboration.VIOLATIONS if all_violations else Corroboration.CORROBORATED
    )
    return CorroborationResult(
        status=status, violations=all_violations, checked=checked
    )
