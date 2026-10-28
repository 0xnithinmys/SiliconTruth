This image is one page of a silicon errata document for a microcontroller.

An erratum describes a way in which the real chip differs from its
reference manual. Report every erratum on this page that requires software
to do something differently.

For each one, report:

- `errata_id` exactly as printed, e.g. "2.14.1".
- `title` exactly as printed.
- `affected_register` -- the register name the workaround acts on, as
  printed, e.g. "USART_CR1". If the erratum names no specific register,
  report an empty string.
- `constraint` -- which of the following the workaround requires. Choose
  the single closest match, or "none" if it is not one of these:
    * `delay_cycles_after_write` -- software must wait a number of cycles
      or a period of time after writing the register before accessing it
      again.
    * `dummy_read_required` -- software must perform a read whose value is
      discarded, to flush or synchronise.
    * `write_order_dependency` -- two or more registers must be written in
      a specific order.
    * `clock_enable_before_access` -- a clock or power domain must be
      enabled before the register may be accessed at all.
    * `avoid_value` -- a specific value or range must never be written.
- The numbers the workaround depends on, each as the string printed on the
  page. Report an EMPTY STRING for any that the text does not state:
    * `cycles` -- a cycle count, e.g. "16".
    * `ns`, `us` -- a time, if stated in those units.
    * `value` -- a forbidden value, e.g. "0x3F".
    * `other_register` -- the second register in an ordering dependency.
    * `field` -- the bitfield the erratum is scoped to, if it names one,
      e.g. "DEAT". Leave empty if the erratum concerns the whole register.
- `quote` -- the sentence from the page that states the requirement.

Rules:

- Report only what the page states. Do not infer a workaround that is not
  written down, and do not generalise one erratum to other registers.
- If an erratum is documented but requires no software action, do not
  report it.
- Do not compute anything. If the text says "wait 16 APB cycles", report
  cycles as "16"; do not convert it to nanoseconds.
- If you are unsure which constraint applies, report "none" rather than
  guessing. An erratum reported with the wrong constraint produces a
  workaround that does not work, which is worse than no workaround.
