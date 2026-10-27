"""T-088/T-089 — parse the Renode MMIO trace and render a verdict.

INVARIANT #2: no generated code is claimed correct without executing in Renode.
This module is the judge of that execution.

It is deliberately separable from Renode itself: `parse_trace` takes text, so
the assertion logic is testable against recorded and synthetic traces without
the emulator installed. The Modal container supplies real traces; the test suite
supplies adversarial ones.

The verdict shape is fixed, because the repair loop and the UI both consume it:

    {"status": "FAIL",
     "fault_pc": "0x08000142",
     "mmio_addr": "0x40011000",
     "violation": "ERRATA_2_14_1_DELAY_MISSING"}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum

# Emitted by the generated peripheral. Keep in sync with renode_peripheral.TRACE_PREFIX.
#
# Horizontal whitespace only ([ \t]), never \s: the optional trailing note must
# not be allowed to cross a newline, or it swallows the NEXT line's prefix and
# the parser silently loses half the transactions.
MMIO_LINE = re.compile(
    r"SILICONTRUTH_MMIO[ \t]+(?P<kind>READ|WRITE)[ \t]+"
    r"0x(?P<offset>[0-9A-Fa-f]+)[ \t]+(?P<name>[^\s]+)[ \t]+"
    r"0x(?P<value>[0-9A-Fa-f]+)[ \t]+\[(?P<verdict>PASS|FAIL)\]"
    r"(?:[ \t]+(?P<note>[^\s]+))?[ \t]*$",
    re.MULTILINE,
)

# Renode prints the faulting PC when the CPU aborts.
PC_LINE = re.compile(r"(?:PC|pc)[=:]?\s*0x(?P<pc>[0-9A-Fa-f]{4,16})")

CPU_ABORT = re.compile(
    r"(CPU abort|HardFault|Unhandled exception|cpu: abort|EscalatedFault)", re.I
)


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NO_TRACE = "NO_TRACE"


@dataclass(frozen=True)
class MmioTransaction:
    index: int
    kind: str  # READ | WRITE
    offset: int
    register: str
    value: int
    verdict: str  # PASS | FAIL
    note: str | None = None

    def render(self, base_address: int = 0) -> str:
        """The line the UI's bus-trace pane shows."""
        addr = base_address + self.offset
        s = f"{self.kind:<5} 0x{addr:08X} -> 0x{self.value:08X} [{self.verdict}]"
        return f"{s} {self.note}" if self.note else s


@dataclass
class OracleVerdict:
    status: Status
    transactions: list[MmioTransaction] = field(default_factory=list)
    fault_pc: str | None = None
    mmio_addr: str | None = None
    violation: str | None = None
    message: str = ""

    @property
    def passed(self) -> bool:
        return self.status is Status.PASS

    @property
    def exit_code(self) -> int:
        """Non-zero on failure, so the /goal audit and CI can gate on it."""
        return 0 if self.passed else 1

    def to_json(self) -> str:
        """The exact shape the repair loop consumes."""
        payload: dict[str, object] = {"status": self.status.value}
        if self.fault_pc:
            payload["fault_pc"] = self.fault_pc
        if self.mmio_addr:
            payload["mmio_addr"] = self.mmio_addr
        if self.violation:
            payload["violation"] = self.violation
        if self.message:
            payload["message"] = self.message
        payload["transactions"] = len(self.transactions)
        return json.dumps(payload)

    def summary(self) -> str:
        if self.status is Status.PASS:
            return f"PASS: {len(self.transactions)} MMIO transactions, no violations"
        if self.status is Status.NO_TRACE:
            return "NO_TRACE: the firmware produced no MMIO activity"
        return f"FAIL: {self.violation} at {self.mmio_addr} (pc {self.fault_pc or '?'})"


def parse_trace(text: str, *, base_address: int = 0) -> list[MmioTransaction]:
    """Extract MMIO transactions from a Renode console log."""
    out: list[MmioTransaction] = []
    for i, m in enumerate(MMIO_LINE.finditer(text)):
        out.append(
            MmioTransaction(
                index=i,
                kind=m.group("kind"),
                offset=int(m.group("offset"), 16),
                register=m.group("name"),
                value=int(m.group("value"), 16),
                verdict=m.group("verdict"),
                note=m.group("note"),
            )
        )
    return out


def find_fault_pc(text: str) -> str | None:
    """The PC at the point of failure, which is what the repair loop needs to
    locate the offending line of C."""
    matches = PC_LINE.findall(text)
    if not matches:
        return None
    return f"0x{matches[-1].upper().zfill(8)}"


def evaluate(
    text: str,
    *,
    base_address: int = 0,
    require_transactions: bool = True,
) -> OracleVerdict:
    """Judge a Renode run.

    A run fails if any transaction is marked FAIL, if the CPU aborted, or if
    `require_transactions` and the firmware never touched the peripheral --
    silence is not success. A driver that does nothing must not pass.
    """
    txns = parse_trace(text, base_address=base_address)

    failed = next((t for t in txns if t.verdict == "FAIL"), None)
    if failed is not None:
        return OracleVerdict(
            status=Status.FAIL,
            transactions=txns,
            fault_pc=find_fault_pc(text),
            mmio_addr=f"0x{base_address + failed.offset:08X}",
            violation=failed.note or "MMIO_ASSERTION_FAILED",
            message=f"{failed.kind} to {failed.register} rejected by the peripheral model",
        )

    if CPU_ABORT.search(text):
        return OracleVerdict(
            status=Status.FAIL,
            transactions=txns,
            fault_pc=find_fault_pc(text),
            mmio_addr=f"0x{base_address + txns[-1].offset:08X}" if txns else None,
            violation="CPU_ABORT",
            message="the CPU faulted during execution",
        )

    if require_transactions and not txns:
        return OracleVerdict(
            status=Status.NO_TRACE,
            transactions=[],
            violation="NO_MMIO_ACTIVITY",
            message=(
                "the firmware ran but never accessed the peripheral. "
                "A driver that does nothing is not a driver that works."
            ),
        )

    return OracleVerdict(status=Status.PASS, transactions=txns)


def render_bus_trace(verdict: OracleVerdict, base_address: int = 0) -> str:
    """The right-hand pane's monospace view."""
    return "\n".join(t.render(base_address) for t in verdict.transactions)
