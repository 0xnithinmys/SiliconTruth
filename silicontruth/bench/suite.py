"""The synthetic benchmark suite: five chips, each stressing something different.

The plan's five-chip scorecard needs real reference manuals, which are
copyrighted and cannot be committed. These stand in for them as a
REGRESSION suite, and every number derived from them is labelled synthetic.
They do not substitute for running the pipeline on an actual manual, and
nothing here should be read as evidence about real silicon.

What each one is for:

  uart32   32-bit, multi-column fields, three registers. The baseline.
  timer16  16-bit registers. The width-conservation check is parameterised
           by register width, and a 32-only suite never exercises that.
  gpio8    8-bit registers drawn as a single bank of 8. Different layout
           geometry, which is what the grid reconstruction keys on.
  pmic32   Reserved runs in the MIDDLE of the register, not only at the
           top, plus errata on two different registers.
  adc32    Dense single-bit fields and a write-order dependency, so the
           topological ordering in the emitters is actually exercised.
"""

from __future__ import annotations

from silicontruth.bench.synthetic import ChipSpec, ErratumSpec, FieldSpec, RegisterSpec


def _res(msb: int, lsb: int) -> FieldSpec:
    return FieldSpec(f"RESERVED_{msb}_{lsb}", msb, lsb, "r")


UART32 = ChipSpec(
    slug="uart32",
    chip="synth-uart32",
    peripheral="USART1",
    base_address=0x40011000,
    section="27.8",
    first_page=412,
    registers=[
        RegisterSpec(
            name="CR1", display="USART_CR1", offset=0x00, width=32,
            reset_value=0x00000000, description="Control register 1 (USART_CR1)",
            fields=[
                _res(31, 29),
                FieldSpec("EOBIE", 28, 28, "rw", "End of Block interrupt enable."),
                FieldSpec("RTOIE", 27, 27, "rw", "Receiver timeout interrupt enable."),
                FieldSpec("DEAT", 26, 21, "rw", "Driver Enable assertion time."),
                FieldSpec("DEDT", 20, 16, "rw", "Driver Enable de-assertion time."),
                FieldSpec("OVER8", 15, 15, "rw", "Oversampling mode."),
                FieldSpec("CMIE", 14, 14, "rw", "Character match interrupt enable."),
                FieldSpec("MME", 13, 13, "rw", "Mute mode enable."),
                FieldSpec("M0", 12, 12, "rw", "Word length bit 0."),
                FieldSpec("WAKE", 11, 11, "rw", "Receiver wakeup method."),
                FieldSpec("PCE", 10, 10, "rw", "Parity control enable."),
                FieldSpec("PS", 9, 9, "rw", "Parity selection."),
                FieldSpec("PEIE", 8, 8, "rw", "PE interrupt enable."),
                FieldSpec("TXEIE", 7, 7, "rw", "TXE interrupt enable."),
                FieldSpec("TCIE", 6, 6, "rw", "Transmission complete interrupt enable."),
                FieldSpec("RXNEIE", 5, 5, "rw", "RXNE interrupt enable."),
                FieldSpec("IDLEIE", 4, 4, "rw", "IDLE interrupt enable."),
                FieldSpec("TE", 3, 3, "rw", "Transmitter enable."),
                FieldSpec("RE", 2, 2, "rw", "Receiver enable."),
                FieldSpec("UESM", 1, 1, "rw", "USART enable in Stop mode."),
                FieldSpec("UE", 0, 0, "rw", "USART enable."),
            ],
        ),
        RegisterSpec(
            name="CR2", display="USART_CR2", offset=0x04, width=32,
            reset_value=0x00000000, description="Control register 2 (USART_CR2)",
            fields=[
                FieldSpec("ADD", 31, 24, "rw", "Address of the USART node."),
                FieldSpec("RTOEN", 23, 23, "rw", "Receiver timeout enable."),
                FieldSpec("ABRMOD", 22, 21, "rw", "Auto baud rate mode."),
                FieldSpec("ABREN", 20, 20, "rw", "Auto baud rate enable."),
                FieldSpec("MSBFIRST", 19, 19, "rw", "Most significant bit first."),
                FieldSpec("DATAINV", 18, 18, "rw", "Binary data inversion."),
                FieldSpec("TXINV", 17, 17, "rw", "TX pin active level inversion."),
                FieldSpec("RXINV", 16, 16, "rw", "RX pin active level inversion."),
                FieldSpec("SWAP", 15, 15, "rw", "Swap TX/RX pins."),
                FieldSpec("LINEN", 14, 14, "rw", "LIN mode enable."),
                FieldSpec("STOP", 13, 12, "rw", "Stop bits."),
                FieldSpec("CLKEN", 11, 11, "rw", "Clock enable."),
                FieldSpec("CPOL", 10, 10, "rw", "Clock polarity."),
                FieldSpec("CPHA", 9, 9, "rw", "Clock phase."),
                FieldSpec("LBCL", 8, 8, "rw", "Last bit clock pulse."),
                _res(7, 7),
                FieldSpec("LBDIE", 6, 6, "rw", "LIN break detection interrupt."),
                FieldSpec("LBDL", 5, 5, "rw", "LIN break detection length."),
                FieldSpec("ADDM7", 4, 4, "rw", "7-bit address detection."),
                _res(3, 0),
            ],
        ),
        RegisterSpec(
            name="BRR", display="USART_BRR", offset=0x0C, width=32,
            reset_value=0x00000000, description="Baud rate register (USART_BRR)",
            fields=[_res(31, 16), FieldSpec("BRR", 15, 0, "rw", "Baud rate divisor.")],
        ),
    ],
    errata=[
        ErratumSpec(
            "2.14.1", "USART_CR1 write not taken into account immediately",
            "USART_CR1", "delay_cycles_after_write",
            "After a write access to the USART_CR1 register, the new value is "
            "not taken into account by the peripheral until several APB cycles "
            "have elapsed. A subsequent access performed too early returns the "
            "previous value.",
            "Software must wait 16 APB cycles after writing USART_CR1 before "
            "performing any further access to the peripheral.",
            True, {"cycles": "16"},
        ),
        ErratumSpec(
            "2.3.2", "USART register access before clock enable",
            "USART_CR1", "clock_enable_before_access",
            "Accessing any USART register before the USART peripheral clock has "
            "been enabled in RCC_APB2ENR causes the access to be silently "
            "discarded and may generate a bus fault.",
            "Software must enable the USART peripheral clock before any access "
            "to USART_CR1.",
            True, {},
        ),
        ErratumSpec(
            "2.1.7", "Increased current consumption in Stop mode", "", "none",
            "The device may exhibit higher than specified current consumption "
            "in Stop mode when the USART is clocked by the HSI oscillator.",
            "None. This limitation does not affect functional behaviour and "
            "requires no software action.",
            False, {},
        ),
    ],
)


TIMER16 = ChipSpec(
    slug="timer16",
    chip="synth-timer16",
    peripheral="TIM3",
    base_address=0x40000400,
    section="31.4",
    first_page=1046,
    errata_page=23,
    registers=[
        RegisterSpec(
            name="CR1", display="TIM_CR1", offset=0x00, width=16,
            reset_value=0x0000, description="Control register 1 (TIM_CR1)",
            fields=[
                _res(15, 10),
                FieldSpec("CKD", 9, 8, "rw", "Clock division."),
                FieldSpec("ARPE", 7, 7, "rw", "Auto-reload preload enable."),
                FieldSpec("CMS", 6, 5, "rw", "Center-aligned mode selection."),
                FieldSpec("DIR", 4, 4, "rw", "Direction."),
                FieldSpec("OPM", 3, 3, "rw", "One-pulse mode."),
                FieldSpec("URS", 2, 2, "rw", "Update request source."),
                FieldSpec("UDIS", 1, 1, "rw", "Update disable."),
                FieldSpec("CEN", 0, 0, "rw", "Counter enable."),
            ],
        ),
        RegisterSpec(
            name="SR", display="TIM_SR", offset=0x10, width=16,
            reset_value=0x0000, description="Status register (TIM_SR)",
            fields=[
                _res(15, 13),
                FieldSpec("CC4OF", 12, 12, "rc_w0", "Capture/compare 4 overcapture."),
                FieldSpec("CC3OF", 11, 11, "rc_w0", "Capture/compare 3 overcapture."),
                FieldSpec("CC2OF", 10, 10, "rc_w0", "Capture/compare 2 overcapture."),
                FieldSpec("CC1OF", 9, 9, "rc_w0", "Capture/compare 1 overcapture."),
                _res(8, 7),
                FieldSpec("TIF", 6, 6, "rc_w0", "Trigger interrupt flag."),
                FieldSpec("CC4IF", 5, 5, "rc_w0", "Capture/compare 4 interrupt flag."),
                FieldSpec("CC3IF", 4, 4, "rc_w0", "Capture/compare 3 interrupt flag."),
                FieldSpec("CC2IF", 3, 3, "rc_w0", "Capture/compare 2 interrupt flag."),
                FieldSpec("CC1IF", 2, 2, "rc_w0", "Capture/compare 1 interrupt flag."),
                _res(1, 1),
                FieldSpec("UIF", 0, 0, "rc_w0", "Update interrupt flag."),
            ],
        ),
    ],
    errata=[
        ErratumSpec(
            "2.8.3", "Status register requires a dummy read after clearing",
            "TIM_SR", "dummy_read_required",
            "Clearing a flag in TIM_SR does not take effect until the register "
            "has been read back, because the write buffer is not flushed by the "
            "write alone.",
            "Software must perform a read of TIM_SR after clearing any flag and "
            "discard the value.",
            True, {},
        ),
    ],
)


GPIO8 = ChipSpec(
    slug="gpio8",
    chip="synth-gpio8",
    peripheral="PORTB",
    base_address=0x50000800,
    section="12.2",
    first_page=188,
    errata_page=7,
    registers=[
        RegisterSpec(
            name="DDR", display="PORT_DDR", offset=0x00, width=8,
            reset_value=0x00, description="Data direction register (PORT_DDR)",
            fields=[FieldSpec(f"DDR{i}", i, i, "rw", f"Pin {i} direction.")
                    for i in range(7, -1, -1)],
        ),
        RegisterSpec(
            name="ODR", display="PORT_ODR", offset=0x01, width=8,
            reset_value=0x00, description="Output data register (PORT_ODR)",
            fields=[FieldSpec(f"ODR{i}", i, i, "rw", f"Pin {i} output value.")
                    for i in range(7, -1, -1)],
        ),
        RegisterSpec(
            name="IDR", display="PORT_IDR", offset=0x02, width=8,
            reset_value=0x00, description="Input data register (PORT_IDR)",
            fields=[FieldSpec(f"IDR{i}", i, i, "ro", f"Pin {i} input value.")
                    for i in range(7, -1, -1)],
        ),
    ],
    errata=[
        ErratumSpec(
            "1.4.2", "Port reads before clock enable return zero",
            "PORT_IDR", "clock_enable_before_access",
            "Reading PORT_IDR before the port clock has been enabled returns "
            "zero for every pin regardless of the physical pin state.",
            "Software must enable the port clock before reading PORT_IDR.",
            True, {},
        ),
        ErratumSpec(
            "1.9.1", "Maximum toggle frequency reduced below 2.4 V", "", "none",
            "At supply voltages below 2.4 V the maximum achievable port toggle "
            "frequency is reduced relative to the datasheet value.",
            "Operate above 2.4 V if the maximum toggle rate is required. No "
            "register workaround exists.",
            False, {},
        ),
    ],
)


PMIC32 = ChipSpec(
    slug="pmic32",
    chip="synth-pmic32",
    peripheral="PMIC",
    base_address=0x40020000,
    section="8.3",
    first_page=74,
    errata_page=11,
    registers=[
        RegisterSpec(
            name="VOUT", display="PMIC_VOUT", offset=0x00, width=32,
            reset_value=0x00000000,
            description="Output voltage control (PMIC_VOUT)",
            fields=[
                FieldSpec("LOCK", 31, 31, "rw", "Register write lock."),
                _res(30, 26),
                FieldSpec("RAMP", 25, 24, "rw", "Output ramp rate."),
                _res(23, 20),
                FieldSpec("VSEL2", 19, 12, "rw", "Rail 2 voltage select."),
                _res(11, 8),
                FieldSpec("VSEL1", 7, 0, "rw", "Rail 1 voltage select."),
            ],
        ),
        RegisterSpec(
            name="ENABLE", display="PMIC_ENABLE", offset=0x08, width=32,
            reset_value=0x00000000,
            description="Rail enable control (PMIC_ENABLE)",
            fields=[
                _res(31, 4),
                FieldSpec("EN4", 3, 3, "rw", "Rail 4 enable."),
                FieldSpec("EN3", 2, 2, "rw", "Rail 3 enable."),
                FieldSpec("EN2", 1, 1, "rw", "Rail 2 enable."),
                FieldSpec("EN1", 0, 0, "rw", "Rail 1 enable."),
            ],
        ),
    ],
    errata=[
        ErratumSpec(
            "3.2.1", "Reserved VSEL1 code damages the output stage",
            "PMIC_VOUT", "avoid_value",
            "Programming the VSEL1 field of PMIC_VOUT with the value 0xFF "
            "drives the output stage beyond its rated voltage and can damage "
            "the regulator and any connected load.",
            "Software must never write the value 0xFF to the VSEL1 field of "
            "PMIC_VOUT.",
            True, {"value": "0xFF", "field": "VSEL1"},
        ),
        ErratumSpec(
            "3.5.4", "Enable register must settle before voltage changes",
            "PMIC_VOUT", "delay_cycles_after_write",
            "A write to PMIC_VOUT issued too soon after PMIC_ENABLE is "
            "latched against the previous rail configuration.",
            "Software must wait 64 cycles after writing PMIC_ENABLE before "
            "writing PMIC_VOUT.",
            True, {"cycles": "64"},
        ),
    ],
)


ADC32 = ChipSpec(
    slug="adc32",
    chip="synth-adc32",
    peripheral="ADC1",
    base_address=0x40012000,
    section="18.6",
    first_page=320,
    errata_page=15,
    registers=[
        RegisterSpec(
            name="CR", display="ADC_CR", offset=0x08, width=32,
            reset_value=0x00000000, description="Control register (ADC_CR)",
            fields=[
                FieldSpec("ADCAL", 31, 31, "rw", "Calibration."),
                FieldSpec("ADCALDIF", 30, 30, "rw", "Differential calibration."),
                FieldSpec("DEEPPWD", 29, 29, "rw", "Deep power down."),
                FieldSpec("ADVREGEN", 28, 28, "rw", "Voltage regulator enable."),
                _res(27, 6),
                FieldSpec("JADSTP", 5, 5, "rw", "Injected conversion stop."),
                FieldSpec("ADSTP", 4, 4, "rw", "Regular conversion stop."),
                FieldSpec("JADSTART", 3, 3, "rw", "Injected conversion start."),
                FieldSpec("ADSTART", 2, 2, "rw", "Regular conversion start."),
                FieldSpec("ADDIS", 1, 1, "rw", "Disable."),
                FieldSpec("ADEN", 0, 0, "rw", "Enable."),
            ],
        ),
        RegisterSpec(
            name="CFGR", display="ADC_CFGR", offset=0x0C, width=32,
            reset_value=0x00000000,
            description="Configuration register (ADC_CFGR)",
            fields=[
                FieldSpec("JQDIS", 31, 31, "rw", "Injected queue disable."),
                FieldSpec("AWD1CH", 30, 26, "rw", "Watchdog 1 channel."),
                FieldSpec("JAUTO", 25, 25, "rw", "Automatic injected group."),
                FieldSpec("JAWD1EN", 24, 24, "rw", "Watchdog 1 on injected."),
                FieldSpec("AWD1EN", 23, 23, "rw", "Watchdog 1 on regular."),
                FieldSpec("AWD1SGL", 22, 22, "rw", "Watchdog 1 single channel."),
                FieldSpec("JQM", 21, 21, "rw", "Injected queue mode."),
                FieldSpec("JDISCEN", 20, 20, "rw", "Injected discontinuous."),
                FieldSpec("DISCNUM", 19, 17, "rw", "Discontinuous channel count."),
                FieldSpec("DISCEN", 16, 16, "rw", "Discontinuous mode."),
                _res(15, 14),
                FieldSpec("AUTDLY", 13, 13, "rw", "Delayed conversion."),
                FieldSpec("CONT", 12, 12, "rw", "Continuous conversion."),
                FieldSpec("OVRMOD", 11, 11, "rw", "Overrun mode."),
                FieldSpec("EXTEN", 10, 9, "rw", "External trigger enable."),
                FieldSpec("EXTSEL", 8, 5, "rw", "External trigger selection."),
                FieldSpec("RES", 4, 3, "rw", "Resolution."),
                FieldSpec("ALIGN", 2, 2, "rw", "Data alignment."),
                FieldSpec("DMACFG", 1, 1, "rw", "DMA configuration."),
                FieldSpec("DMAEN", 0, 0, "rw", "DMA enable."),
            ],
        ),
    ],
    errata=[
        ErratumSpec(
            "2.2.6", "ADC_CFGR must be written before ADC_CR",
            "ADC_CR", "write_order_dependency",
            "Writing ADC_CR before ADC_CFGR latches the control settings "
            "against the previous configuration, so the first conversion "
            "after reset uses the wrong resolution.",
            "Software must write ADC_CFGR before ADC_CR.",
            True, {"other_register": "ADC_CFGR"},
        ),
        ErratumSpec(
            "2.7.9", "Temperature sensor accuracy outside 0-50 C", "", "none",
            "The internal temperature sensor exceeds its specified accuracy "
            "outside the 0 to 50 degree range.",
            "None required; apply the calibration values from system memory "
            "if higher accuracy is needed.",
            False, {},
        ),
    ],
)


SUITE: list[ChipSpec] = [UART32, TIMER16, GPIO8, PMIC32, ADC32]


def by_slug(slug: str) -> ChipSpec:
    for spec in SUITE:
        if spec.slug == slug:
            return spec
    raise KeyError(f"no such chip: {slug} (have: {[s.slug for s in SUITE]})")
