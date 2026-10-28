# realtest — the first real datasheet

Everything in the benchmark suite is synthetic: drawn by this project and read
back by it. That makes it a regression instrument, not evidence. This directory
is the other kind of test — a real manufacturer document, scored against ground
truth the project did not author.

**Subject:** RP2040 datasheet (642 pages, Raspberry Pi), peripheral `UART0` at
`0x40034000`.
**Ground truth:** `RP2040.svd` from the pico-sdk — the vendor's own published
register map.

## Reproduce

```bash
cd realtest
mkdir -p downloads

curl -L -o downloads/rp2040.svd \
  https://raw.githubusercontent.com/raspberrypi/pico-sdk/master/src/rp2040/hardware_regs/RP2040.svd
curl -L -o downloads/rp2040-datasheet.pdf \
  https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf

# Which pages carry the register tables
python -I mapregs.py downloads/rp2040-datasheet.pdf

cd ..
python -m silicontruth.cli pipeline realtest/downloads/rp2040-datasheet.pdf \
    --pages 433 434 435 --chip rp2040 --peripheral UART0 \
    --base 0x40034000 -o realtest/out --fixtures realtest/fixtures

cd realtest
python -I score.py downloads/rp2040.svd out/chip.svd UART0
```

The downloads are gitignored — they are a few MB and not ours to redistribute.
The scripts are committed.

## Result

See "The first real datasheet" in the top-level README. In short: of five
registers on those pages it extracted one, and everything it reported about
that one was exact — base address, offset and field bit range all match the
vendor SVD, with zero wrong fields. The other two pages were refused rather
than guessed at.

The two limitations it exposed are in the ingest layer, not the gates:
a required register-level reset value this document does not print, and
one-register-per-page extraction against pages that carry several.

## The scripts

| file | what |
|---|---|
| `gt.py` | parse a CMSIS-SVD into `{peripheral: {register: {fields}}}` |
| `score.py` | diff an emitted SVD against the vendor's, field by field |
| `mapregs.py` | find which datasheet page documents which register |
| `findpages.py` | locate pages containing given strings |
| `peek.py` | dump one page's text layer |

`gt.py` takes the peripheral name from the element directly under
`<peripheral>`, not the first match anywhere in the block — `RESETS` contains a
*field* called `UART0`, and a naive search scores against the wrong peripheral
entirely.
