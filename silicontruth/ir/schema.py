"""PeripheralIR — the contract between the probabilistic half and the deterministic half.

THE TWO INVARIANTS OF THIS CODEBASE
-----------------------------------
1. No LLM output reaches code generation without passing Z3.
2. No generated code is claimed correct without executing in Renode.

THE ARITHMETIC PROHIBITION
--------------------------
No field in this schema may ever be populated by a model doing arithmetic.
The model reports what the table *says* (offset: 0x0C, lsb: 8, msb: 15).
Everything derived -- absolute addresses, bitmasks, width sums, alignment --
is computed in Python and proved in Z3, never in prose.

Provenance is likewise owned by Python. If the model supplies a bounding box,
it can hallucinate one; the crop metadata is the only trustworthy source.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Register widths we accept. Anything else is an extraction failure, not a chip quirk.
RegisterWidth = Literal[8, 16, 32]

# Access modes, in CMSIS-SVD vocabulary.
#   rw     read-write
#   ro     read-only
#   wo     write-only
#   rc_w0  read, clear by writing 0
#   rc_w1  read, clear by writing 1
#   w1c    write 1 to clear
Access = Literal["rw", "ro", "wo", "rc_w0", "rc_w1", "w1c"]


class Source(str, Enum):
    DATASHEET = "datasheet"
    ERRATA = "errata"


class ErrataConstraint(str, Enum):
    """The closed set of workarounds we know how to emit into a driver.

    Closed on purpose. A model proposing anything outside this set is rejected and
    logged rather than coerced -- see errata_linker guardrail (T-059).
    """

    DELAY_CYCLES_AFTER_WRITE = "delay_cycles_after_write"
    DUMMY_READ_REQUIRED = "dummy_read_required"
    WRITE_ORDER_DEPENDENCY = "write_order_dependency"
    CLOCK_ENABLE_BEFORE_ACCESS = "clock_enable_before_access"
    AVOID_VALUE = "avoid_value"


class Provenance(BaseModel):
    """Where a fact came from. Filled in Python from crop metadata, never by the model."""

    model_config = ConfigDict(frozen=True)

    page: int = Field(ge=1, description="1-indexed page in the source PDF")
    bbox: tuple[float, float, float, float] = Field(
        description="(x0, y0, x1, y1) in RENDER_DPI pixel space, not PDF points"
    )
    source: Source
    errata_id: str | None = None
    mask_id: str | None = Field(default=None, description="SAM 3.1 mask, for the UI overlay")

    @model_validator(mode="after")
    def _bbox_is_well_formed(self) -> Provenance:
        x0, y0, x1, y1 = self.bbox
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"degenerate bbox {self.bbox}: expected x0<x1 and y0<y1")
        return self


class BitField(BaseModel):
    """One field within a register. [lsb, msb] inclusive, as datasheets write it."""

    name: str
    lsb: int = Field(ge=0, le=31)
    msb: int = Field(ge=0, le=31)
    access: Access
    reset_value: int = 0
    description: str = ""
    reserved: bool = False
    provenance: Provenance

    @model_validator(mode="after")
    def _lsb_not_above_msb(self) -> BitField:
        # Caught here as a schema error AND again in Z3 as corruption #7 -- the
        # redundancy is deliberate: this validator can be bypassed by constructing
        # the object directly, the Z3 gate cannot.
        if self.lsb > self.msb:
            raise ValueError(f"{self.name}: lsb {self.lsb} > msb {self.msb}")
        return self

    @property
    def width(self) -> int:
        return self.msb - self.lsb + 1

    @property
    def mask(self) -> int:
        """Computed in Python. Never asked of the model."""
        return ((1 << self.width) - 1) << self.lsb


class Register(BaseModel):
    name: str
    offset: int = Field(ge=0, description="Byte offset from the peripheral base address")
    width: RegisterWidth
    reset_value: int = 0
    access: Access
    fields: list[BitField] = Field(default_factory=list)
    provenance: Provenance

    # Set by the verifier, not by extraction. A register that fails Z3 three times
    # is marked unverified and excluded from codegen rather than silently emitted.
    verified: bool = False
    unverified_reason: str | None = None

    def absolute_address(self, base_address: int) -> int:
        """Computed in Python. Proved in Z3. Never asked of the model."""
        return base_address + self.offset

    @property
    def reserved_mask(self) -> int:
        m = 0
        for f in self.fields:
            if f.reserved:
                m |= f.mask
        return m


class ErrataRule(BaseModel):
    errata_id: str
    title: str
    affected_register: str
    constraint: ErrataConstraint
    params: dict[str, int | str] = Field(default_factory=dict)
    provenance: Provenance


class TimingConstraint(BaseModel):
    """An AC timing bound lifted from a waveform diagram, checked against a real capture."""

    parameter_name: str = Field(description="e.g. t_SU:STA, t_HD:DAT")
    signal: str = Field(description="e.g. SCL, SDA")
    edge: Literal["rising", "falling", "both"] = "both"
    min_ns: float | None = None
    max_ns: float | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def _has_a_bound(self) -> TimingConstraint:
        if self.min_ns is None and self.max_ns is None:
            raise ValueError(f"{self.parameter_name}: needs at least one of min_ns/max_ns")
        return self


class PeripheralIR(BaseModel):
    chip: str
    peripheral: str
    base_address: int = Field(ge=0)
    registers: list[Register] = Field(default_factory=list)
    errata: list[ErrataRule] = Field(default_factory=list)
    timing: list[TimingConstraint] = Field(default_factory=list)

    def register_by_name(self, name: str) -> Register | None:
        return next((r for r in self.registers if r.name == name), None)

    def errata_for(self, register_name: str) -> list[ErrataRule]:
        return [e for e in self.errata if e.affected_register == register_name]

    @property
    def verified_registers(self) -> list[Register]:
        """The only registers codegen is allowed to touch."""
        return [r for r in self.registers if r.verified]

    @property
    def unverified_registers(self) -> list[Register]:
        """Surfaced loudly in the UI. A visible honest gap beats a silent wrong offset."""
        return [r for r in self.registers if not r.verified]
