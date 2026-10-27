"""Generate tests/fixtures/usart1_valid.json — a known-good PeripheralIR (T-032).

Hand-transcribed from the STM32H7 reference manual (RM0433), USART1 control and
baud-rate registers. This is deliberately real: the Z3 gate is built against a
register map an embedded engineer would recognise, not a synthetic toy.

Run:  python tests/build_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path

from silicontruth.ir.schema import (
    BitField,
    PeripheralIR,
    Provenance,
    Register,
    Source,
)

USART1_BASE = 0x4001_1000


def prov(page: int, row: int, *, source: Source = Source.DATASHEET) -> Provenance:
    """Synthetic but well-formed provenance. Real runs fill this from crop metadata."""
    y = 200.0 + row * 28.0
    return Provenance(
        page=page,
        bbox=(120.0, y, 2280.0, y + 26.0),
        source=source,
        mask_id=f"mask-p{page}-r{row}",
    )


def bf(
    name: str,
    lsb: int,
    msb: int,
    *,
    access: str = "rw",
    reserved: bool = False,
    page: int = 2054,
    row: int = 0,
    desc: str = "",
) -> BitField:
    return BitField(
        name=name,
        lsb=lsb,
        msb=msb,
        access=access,  # type: ignore[arg-type]
        reserved=reserved,
        description=desc,
        provenance=prov(page, row),
    )


def usart1_cr1() -> Register:
    """USART_CR1 — 32 bits, fully accounted: 29 defined + 3 reserved."""
    singles = [
        ("UE", 0, "USART enable"),
        ("UESM", 1, "USART enable in Stop mode"),
        ("RE", 2, "Receiver enable"),
        ("TE", 3, "Transmitter enable"),
        ("IDLEIE", 4, "IDLE interrupt enable"),
        ("RXNEIE", 5, "RXNE interrupt enable"),
        ("TCIE", 6, "Transmission complete interrupt enable"),
        ("TXEIE", 7, "TXE interrupt enable"),
        ("PEIE", 8, "Parity error interrupt enable"),
        ("PS", 9, "Parity selection"),
        ("PCE", 10, "Parity control enable"),
        ("WAKE", 11, "Receiver wakeup method"),
        ("M0", 12, "Word length bit 0"),
        ("MME", 13, "Mute mode enable"),
        ("CMIE", 14, "Character match interrupt enable"),
        ("OVER8", 15, "Oversampling mode"),
        ("RTOIE", 26, "Receiver timeout interrupt enable"),
        ("EOBIE", 27, "End of block interrupt enable"),
        ("M1", 28, "Word length bit 1"),
    ]
    fields = [bf(n, b, b, row=i, desc=d) for i, (n, b, d) in enumerate(singles)]
    fields.append(bf("DEDT", 16, 20, row=20, desc="Driver enable de-assertion time"))
    fields.append(bf("DEAT", 21, 25, row=21, desc="Driver enable assertion time"))
    fields.append(bf("RESERVED_31_29", 29, 31, access="ro", reserved=True, row=22))

    return Register(
        name="CR1",
        offset=0x00,
        width=32,
        reset_value=0x0000_0000,
        access="rw",
        fields=fields,
        provenance=prov(2054, 0),
    )


def usart1_cr2() -> Register:
    """USART_CR2 — a trimmed but fully-accounted 32-bit control register."""
    fields = [
        bf("RESERVED_3_0", 0, 3, access="ro", reserved=True, page=2058, row=0),
        bf("ADDM7", 4, 4, page=2058, row=1, desc="7-bit / 4-bit address detection"),
        bf("LBDL", 5, 5, page=2058, row=2, desc="LIN break detection length"),
        bf("LBDIE", 6, 6, page=2058, row=3, desc="LIN break detection interrupt enable"),
        bf("RESERVED_7", 7, 7, access="ro", reserved=True, page=2058, row=4),
        bf("LBCL", 8, 8, page=2058, row=5, desc="Last bit clock pulse"),
        bf("CPHA", 9, 9, page=2058, row=6, desc="Clock phase"),
        bf("CPOL", 10, 10, page=2058, row=7, desc="Clock polarity"),
        bf("CLKEN", 11, 11, page=2058, row=8, desc="Clock enable"),
        bf("STOP", 12, 13, page=2058, row=9, desc="STOP bits"),
        bf("LINEN", 14, 14, page=2058, row=10, desc="LIN mode enable"),
        bf("SWAP", 15, 15, page=2058, row=11, desc="Swap TX/RX pins"),
        bf("RXINV", 16, 16, page=2058, row=12, desc="RX pin active level inversion"),
        bf("TXINV", 17, 17, page=2058, row=13, desc="TX pin active level inversion"),
        bf("DATAINV", 18, 18, page=2058, row=14, desc="Binary data inversion"),
        bf("MSBFIRST", 19, 19, page=2058, row=15, desc="Most significant bit first"),
        bf("ABREN", 20, 20, page=2058, row=16, desc="Auto baud rate enable"),
        bf("ABRMOD", 21, 22, page=2058, row=17, desc="Auto baud rate mode"),
        bf("RTOEN", 23, 23, page=2058, row=18, desc="Receiver timeout enable"),
        bf("ADD", 24, 31, page=2058, row=19, desc="Address of the USART node"),
    ]
    return Register(
        name="CR2",
        offset=0x04,
        width=32,
        reset_value=0x0000_0000,
        access="rw",
        fields=fields,
        provenance=prov(2058, 0),
    )


def usart1_brr() -> Register:
    """USART_BRR — baud rate register. 16 live bits, 16 reserved."""
    return Register(
        name="BRR",
        offset=0x0C,
        width=32,
        reset_value=0x0000_0000,
        access="rw",
        fields=[
            bf("BRR", 0, 15, page=2064, row=0, desc="USART baud rate divider"),
            bf("RESERVED_31_16", 16, 31, access="ro", reserved=True, page=2064, row=1),
        ],
        provenance=prov(2064, 0),
    )


def build() -> PeripheralIR:
    return PeripheralIR(
        chip="STM32H743",
        peripheral="USART1",
        base_address=USART1_BASE,
        registers=[usart1_cr1(), usart1_cr2(), usart1_brr()],
        errata=[],
        timing=[],
    )


if __name__ == "__main__":
    ir = build()
    out = Path(__file__).parent / "fixtures" / "usart1_valid.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ir.model_dump(mode="json"), indent=2), encoding="utf-8")
    print(f"wrote {out}  ({len(ir.registers)} registers)")
