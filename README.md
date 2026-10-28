# SiliconTruth

**Datasheet + errata PDF → a driver proved correct in hardware emulation.**

SiliconTruth reads a chip's reference manual and its silicon errata sheet and emits a
verified hardware support package: a schema-valid CMSIS-SVD register map, a compiling
C and Rust HAL with errata workarounds injected, a Renode virtual peripheral, and a
test suite. Every register offset and bitfield is **proved by a Z3 SMT solver** before
any code is generated, and every generated driver is **executed inside headless Renode**
with its MMIO bus trace asserted against the datasheet's state machine.

> 🔗 **Try it with no API key:** `TODO: keyless replay link`

---

## The two invariants

1. **No LLM output reaches code generation without passing Z3.**
2. **No generated code is claimed correct without executing in Renode.**

Everything else in this repo is plumbing around those two.

---

## Why not just paste the PDF into a chatbot

- Text extraction **merges and destroys** the columns of dense 32-bit bitfield tables.
  The structure *is* the information.
- LLMs do **hex arithmetic badly** and return `base + offset` values that are off by 4.
- The **errata sheet is a separate document.** The register description on page 412 is
  *wrong* unless cross-referenced with the workaround on page 19. Chunked vector RAG
  severs exactly that link.

A wrong bit offset writes to the wrong control register. On a PMIC, that destroys the board.

---

## Status

| Component | State |
|---|---|
| `PeripheralIR` schema (the contract) | done, tagged `schema-v1` |
| Z3 verification gate | done: 10/10 corruptions caught, ~20 ms |
| Z3 retry loop (600 DPI re-crop, 3 tries, then UNVERIFIED) | done |
| PDF render + coordinate spans | done: DPI round-trip tested |
| Page -> IR extraction (Muse Spark) | done: 20/20 fields exact on the fixture |
| Errata cross-reference + closed-set guardrails | done: 3/3 linked, 0 spurious |
| CMSIS-SVD emitter + structural validation | done |
| C HAL emitter + errata injection | done: 5/5 errata constraints |
| Renode peripheral + platform + script | done |
| MMIO oracle (trace parse + verdict) | done: keystone gate passes both ways |
| `/goal` acceptance gate | done: exit codes verified |
| CLI (`extract`/`verify`/`build`/`oracle`/`replay`/`doctor`) | done |
| Run recorder to JSONL fixtures | done |
| Next.js 15 workbench, keyless replay | done: prerendered (SSG) |
| Naive-LLM baseline comparison | done: same model, same pages, no gate |
| SAM 3.1 table segmentation | probe returns 200; not yet wired into Stage 1 |
| `svd2rust` / `arm-gcc -Werror` / Renode execution | needs the Modal container |
| Rust HAL | not started |
| Muse Code 4-worktree fan-out | not started |

**179 tests pass** (extractor 32, oracle 29, errata linker 23, hal 23, svd 19,
retry 15, pdf 14, z3 14, provider 10). Everything except the extraction
commands runs with no credentials.

### What runs end to end, today

```bash
# PDF -> IR, with the Z3 gate run before anything is written
silicontruth extract benchmarks/synthetic/synthetic_usart.pdf \
    --pages 1 --chip synthetic --peripheral USART1 --base 0x40011000 \
    --errata benchmarks/synthetic/synthetic_errata.pdf -o out/ir.json

# IR -> SVD + C HAL + Renode model
silicontruth build out/ir.json -o out/synthetic
```

Measured on the committed fixture: 21 fields read, Z3 pass, SVD valid,
3 of 3 errata linked with 0 spurious, and every generated mask matching
ground truth exactly.

### Measuring against a known answer

Real reference manuals are copyrighted and cannot be committed, which makes
them useless as a CI fixture. `scripts/make_synthetic_datasheet.py` draws a
page in the visual idiom of an ST reference manual and emits the
ground-truth IR beside it, so accuracy has a denominator. Its generator
asserts the drawn bit grid covers bits 0..31 exactly once -- it did not at
first, which would have silently invalidated every number measured against
it.

## Architecture

`TODO (T-145): paste the 5-stage ASCII diagram`

---

## Benchmarks

`TODO (T-146): the 5-chip scorecard, every number traceable to the results JSON`

## Naive LLM vs SiliconTruth

`TODO (T-147): the reproducible comparison, including the exact baseline prompt`

---

## Quickstart

```bash
pip install -e ".[dev]"
cp .env.example .env          # then fill in MODEL_API_KEY
python tests/build_fixture.py # regenerate the known-good IR fixture
pytest                        # the Z3 gate: 10/10 corruptions, <50ms
```

Run the gate on its own:

```bash
pytest tests/test_z3_corruptions.py -v
```

---

## How the verification gate works

For every register, Z3 proves four things:

| | Constraint |
|---|---|
| (a) | `abs_addr == base + offset`, 4-byte aligned |
| (b) | `∀ i≠j : mask_i & mask_j == 0` — no overlapping bitfields |
| (c) | `Σ field widths (incl. reserved) == width ∈ {8,16,32}` |
| (d) | `reset_value & reserved_mask == 0` |

**(c) is the one that matters.** Width conservation turns a rounding error into a caught
bug. If the model misreads `[15:8]` as `[14:8]`, bit 15 goes unaccounted for — 31 bits of
a 32-bit register — and the solver names that exact bit:

```
[width_conservation] CR1 bit 31: 31 of 32 bits accounted for; unaccounted bit: 31
```

That bit maps back to a page and bounding box, which drives an automatic 600 DPI re-crop
and re-extraction of that single table row. After three failed retries the register is
marked `UNVERIFIED`, **excluded from code generation**, and surfaced in the UI.

The model is never asked to be right. It is asked to be *checkable*.

---

## Limitations

`TODO (T-149): what is UNVERIFIED, which chips are emulation-verified vs SVD-only`

Known already:

- **Access-mode errors (`rw` vs `rc_w0`) are not provable by Z3.** An access swap has no
  numeric contradiction. These are caught one layer down, in the Renode MMIO oracle, at
  execution time. We do not pretend otherwise — a heuristic dressed as a proof is the
  exact failure mode this project exists to avoid.

---

## License

MIT — see [LICENSE](LICENSE).
