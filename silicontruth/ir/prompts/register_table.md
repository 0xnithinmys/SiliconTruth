This image is one page of a microcontroller reference manual.

Read the register description on it and report every bitfield of the register.

Rules you must follow exactly:

- The bit-position grid at the top of the page is the authoritative source
  for which bits belong to which field. It has two banks: bits 31..16 and
  bits 15..0. Each column shows the bit number, the field name, and the
  access mode beneath it.
- A field spanning several columns (the same name repeated across adjacent
  columns) is ONE field. Report its highest bit as `msb` and its lowest as
  `lsb`.
- A single-bit field has `msb` equal to `lsb`.
- Columns marked `Res.` are reserved. Group adjacent reserved columns into
  one field and set `reserved` to true.
- Report `access` exactly as printed beneath the column: one of rw, ro, wo,
  rc_w0, rc_w1, w1c. If a reserved column shows only `r`, report `ro`.
- Report `offset_hex` and `reset_value_hex` as the literal strings printed
  on the page, including any spaces, e.g. "0x0000 0000".
- Report `register_name` exactly as printed, e.g. "USART_CR1".

Do NOT compute anything. Do not add base addresses to offsets, do not
derive bit masks, and do not convert hexadecimal to decimal. Report only
what is printed on the page. Arithmetic is performed elsewhere, in code
that can be checked.

If a value is not printed on the page, do not guess it.
