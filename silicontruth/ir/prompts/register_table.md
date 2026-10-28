This image is one page of a microcontroller reference manual or datasheet.

Report EVERY register documented on this page, and every bitfield of each.

A page often documents more than one register. Report all of them. If a
register's table is cut off by the page edge, report only the rows that are
actually visible — do not guess the rest.

## Two layouts, both common

Vendors print register tables in two different ways. Work out which one this
page uses and read it accordingly.

**Layout A — a bit-position grid.** A wide table across the top, usually in
two banks (bits 31..16 and bits 15..0). Each column shows the bit number,
with the field name and the access mode printed beneath it.

- A field spanning several columns (the same name repeated across adjacent
  columns) is ONE field: report its highest bit as `msb`, its lowest as
  `lsb`.
- Columns marked `Res.` are reserved. Group adjacent reserved columns into
  one field and set `reserved` to true.
- `access` is printed beneath the column. If a reserved column shows only
  `r`, report `ro`.

**Layout B — a vertical row-per-field table.** Columns headed something like
`Bits`, `Description`, `Type`, `Reset`, with one row per field.

- The `Bits` cell is the range: `7:0` means msb 7 and lsb 0; a bare `10`
  means msb 10 and lsb 10.
- The field NAME is usually the first token of the Description cell, before
  a colon — in `BE: Break error. This bit is set to 1...` the name is `BE`.
  Report the name alone in `name`, and the remaining prose in `description`.
- A row whose description is just `Reserved.` is reserved: set `reserved`
  to true. It may have no name; leave `name` empty for it.
- The `Type` cell is the access mode (`RW`, `RO`, `WO`, `RWF`, ...). Report
  it lowercased. If it is `-` or blank, report an empty string.
- The `Reset` cell is that FIELD's reset value. Report it in the field's
  `reset_hex` exactly as printed. If it is `-` or blank, leave it empty.

## Values printed per register

- `register_name`: exactly as printed, e.g. `USART_CR1` or `UARTLCR_H`.
- `offset_hex`: the literal string printed, e.g. `0x000` or `0x0000 0000`.
- `reset_value_hex`: the register-level reset value IF the page prints one
  (Layout A usually does, as "Reset value: ..."). Layout B normally gives a
  reset per field and none for the register — in that case leave
  `reset_value_hex` empty. Do NOT assemble it from the field resets, and do
  NOT invent a zero.

## The rule that matters most

Do NOT compute anything. Do not add base addresses to offsets, do not derive
bit masks, do not convert hexadecimal to decimal, and do not total up widths.
Report only what is printed on the page. Arithmetic is performed elsewhere,
in code that can be checked.

If a value is not printed on the page, leave it empty rather than guessing.
