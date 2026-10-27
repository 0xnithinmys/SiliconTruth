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
| CMSIS-SVD emitter + structural validation | done |
| C HAL emitter + errata injection | done: 5/5 errata constraints |
| Renode peripheral + platform + script | done |
| MMIO oracle (trace parse + verdict) | done: keystone gate passes both ways |
| `/goal` acceptance gate | done: exit codes verified |
| CLI (`verify`/`build`/`oracle`/`replay`/`doctor`) | done |
| Run recorder to JSONL fixtures | done |
| Next.js 15 workbench, keyless replay | done: prerendered (SSG) |
| SAM 3.1 segmentation | BLOCKED: no inference provider |
| Muse Spark IR extraction | BLOCKED: no inference provider |
| Errata cross-reference from PDFs | BLOCKED: no inference provider |
| `svd2rust` / `arm-gcc -Werror` / Renode execution | needs the Modal container |
| Rust HAL | not started |
| Muse Code 4-worktree fan-out | not started |

**111 tests green** (z3 14, svd 19, hal 20, oracle 29, retry 15, pdf 14).
Everything not marked BLOCKED runs with no credentials.

### Why the perception half is blocked

The Meta Model API key authenticates (`GET /models` returns 200, nine models)
but every inference call returns **HTTP 402 `billing_not_configured`**. Groq's
free tier was evaluated as a fallback and rejected: its only Meta-owned models
are 512-token prompt-guard classifiers, and it serves no vision model at all.
Local inference OOMs on 5.9 GB RAM. See `docs/daily-log.md`.

The deterministic half -- which is the project's substance -- does not depend
on any of that, and is complete.

---

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
