# Daily log

## Oct 28 (Day 3)
- Repo bootstrapped: tree, pyproject (pinned), .gitignore, .env.example, LICENSE, README skeleton.
- `PeripheralIR` schema written and FROZEN (tag `schema-v1`). Arithmetic prohibition enforced
  in the docstring and by keeping `mask`/`absolute_address` as Python properties.
- Z3 verification gate implemented and passing: 10/10 corruptions caught, 17.5ms clean audit
  (budget 50ms).
- Deviation from plan: corruption #5 (rw -> rc_w0 access swap) replaced with a field-exceeds-
  width defect. An access swap has no numeric contradiction for an SMT solver to prove false;
  it belongs in the Renode oracle (failure mode C). Documented in the test module docstring.
- Environment note: PyPI reachable but slow; z3-solver needed `--timeout 120 --retries 5`.
  Installed 5.3.2.0, not the 4.13.0.0 pinned in pyproject — see TODO below.

### TODO next
- Reconcile the z3-solver pin in pyproject.toml with the installed 5.3.2.0.
- T-034/T-035: PDF render + coordinate spans (no API key needed).
- T-012: smoke the Meta models once MODEL_API_KEY is available.

## Oct 28 (Day 3) — later: T-012 API smoke

**Key is valid; inference is blocked by billing.**

- `GET /models` → 200. Authentication works.
- All four pinned model IDs exist **exactly as written** in `.env`:
  `muse-spark-1.3-contributor`, `muse-spark-1.3`, `sam-3.1`, `muse-wonder-1.0`. No renaming needed.
- Open question 8 ANSWERED: `muse-wonder-full-1.0` is not on this key (9 models listed).
  Plan around `muse-wonder-1.0`, as the build plan already assumed.
- Every inference call → **HTTP 402 `billing_not_configured`**:
  "your team needs to resolve a billing issue first"
  → https://dev.meta.ai/billing/?team_id=1505596744959810

**Blocked until billing clears:** T-038 (page locator), T-041 (SAM segmentation),
T-055 (IR extraction), T-058 (errata linker) — the whole perception half.

**Not blocked:** PDF render + coordinate spans (T-034/35/36), SVD emitter (T-075/76),
Next.js scaffold (T-104). Proceeding with those.

Reusable smoke harness at `scripts/smoke_api.py` — rerun it the moment billing clears:
`python scripts/smoke_api.py`

## Oct 28 — Groq fallback evaluated and REJECTED

User has no Meta billing; chose Groq free tier as the fallback. Smoked it
(`scripts/smoke_groq.py`). **Not viable.**

11 models on the key. The only Meta-owned ones are
`meta-llama/llama-prompt-guard-2-{22m,86m}` — 512-token safety classifiers,
classification only. Unusable for register extraction.

The other 9 (`openai/gpt-oss-*`, `qwen/qwen3.8-27b`, `whisper-*`, `allam-2-7b`,
`canopylabs/*`) are not Meta models. Using them would break the hackathon's
"built with Meta's models" requirement. There is also no vision model on the
key at all, so Stage 1 could not work regardless.

**Local inference also ruled out:** llama3.1:8b OOMs on 5.9GB RAM / 4GB VRAM
(`failed to allocate CUDA_Host buffer`). No vision model fits.

### Remaining viable paths for the perception layer
1. **Meta credits** — user confirms they WERE ACCEPTED, so credits should be
   provisioned. The 402 names a team_id, which points at a setup step rather
   than a real charge. Highest value, costs nothing. **Recommended.**
2. **OpenRouter ~$10** — `meta-llama/llama-4-scout`: $0.10/1M input,
   1,310,720 ctx, vision. Same price as Muse Spark 1.3 with a larger window.
3. **Cerebras / Together free tiers** — unverified, may serve Llama.

### Confirmed good news
- torch 2.11.0+cu128 with **CUDA available** on the GTX 1650 → local SAM 2.1
  segmentation is feasible and free, regardless of which text model we use.

### Response
Building a **pluggable provider abstraction** so the pipeline is not coupled to
any one vendor, then continuing with the entire deterministic half, which needs
no model API at all.

---

## Day 3 — Wed Oct 28, 2026

### The block is gone, and it was partly mine

A new Meta Model API key does inference. The 402 `billing_not_configured`
wall is down, so Groq is dropped and the project is back on the original
plan.

The first call still failed, and that failure was instructive.
`muse-spark-1.3` is a **reasoning model**: it spends completion tokens on
an internal pass before emitting anything visible, and returns
`content: null` with `finish_reason="length"` when `max_tokens` runs out
during that pass. Measured:

| Task | reasoning_tokens | total |
|---|---|---|
| Reply with exactly "OK" | 208 | 231 |
| Three-field JSON object | 385 | — |
| Full 21-field register read | ~2-4k | — |
| Illegible page at 50 DPI | 8190 (exhausted) | — |

A 16-token budget therefore looks exactly like a broken endpoint. That
made two real bugs in `provider.py` reachable: `complete()` returned
`None` from a `-> str` function, and `extract()` called
`json.loads(None)`, a `TypeError` its `except json.JSONDecodeError` did
not catch. Both now raise `Truncated`, naming the finish reason and the
reasoning spend so the remedy is mechanical.

Also wrong: the meta backend wired `vision_model` to `SAM_MODEL`. `sam-3.1`
is a segmentation model on `/v1/responses` and 404s on
`/chat/completions`. The model that *reads* a crop is Spark; SAM only
locates the table.

### What now runs

PDF to verified C, in two commands, on the Meta API. 21 fields read, Z3
pass, SVD valid, 3/3 errata linked with 0 spurious, every generated mask
matching ground truth.

### Three codegen bugs found by reading the generated C

All three compiled, looked plausible, and were wrong:

1. `clock_enable_before_access` emitted `CR1 |= CR1`. The enable bit is in
   RCC, which this IR does not describe, so there was nothing to write and
   the fallback fabricated a self-OR. Now a declared-but-undefined hook:
   an unimplemented workaround is a link error.
2. `avoid_value` emitted `if (CR1 == 63) return -1;` at init -- a read-side
   check on a register nothing had written, comparing a whole 32-bit
   register against a value scoped to the 6-bit DEAT field. Now a
   field-scoped setter that refuses the write.
3. `write_order_dependency` emitted a comment claiming the sequence
   enforced the ordering while registers were still written in offset
   order. Now topologically sorted, with a cycle as a hard error.

Also closed a hole in the errata guardrail: stripping the peripheral prefix
mapped `SPI2_CR1` onto this peripheral's `CR1`, so an erratum for a
different silicon block would have been applied here.

### The uncomfortable result

The naive baseline reads this fixture **correctly**: 20/20 masks, all three
trials. **This fixture does not demonstrate that verification improves
accuracy on clean input.** It is recorded in the README that way.

My first scorer said 5%. That was a bug in the scorer -- it read
`(0x1U << EOBIE_SHIFT)` as `0x1`. A baseline measured with a broken scorer
is a straw man, so it was fixed and rerun before any number was quoted.

What the baseline does show is variance: errata cited per trial 3/3, 3/3,
**0/3** on identical input. The defensible claim is **detectability, not
accuracy** -- and the DPI sweep's summary was corrected too, because it
printed "no false negatives" after a run in which no wrong read occurred.

### What is first tomorrow

1. Deploy the Modal container (`modal deploy`) and run `smoke` -- the
   compile and emulate gates are the last unexecuted invariant.
2. Rust HAL via `svd2rust` (T-093/094).
3. Get one real reference manual locally and run the pipeline on it;
   T-061's acceptance says 2 real chips and the synthetic page does not
   satisfy it.

### Spend

Still trivial. Reasoning tokens dominate: roughly 2-4k completion tokens
per register read, so the ~$0.31/chip model in the plan holds with room to
spare.

### Day 3, later: three gates, and the suite that found three false positives

Pushed the input quality down until the read broke, and got the worst
possible result: **three false negatives**. At 50/42/36 DPI the model
invented a field `M1` and slid EOBIE/RTOIE/DEAT down to make room. The
bits still tiled 0..31 exactly once with no gap or overlap, so every Z3
constraint was genuinely satisfied. The gate passed a wrong read three
times.

No solver fixes that; the error is in the names. Added two orthogonal
checks: was the name printed on the page at all, and is it printed in that
bit's column. Both derive from the PDF text layer, need no model, and run
in milliseconds. Re-running the sweep: all three caught, correct reads
still pass.

Wiring them in exposed something worse. `audit(mark=True)` set `verified`
purely from its own result, so re-running it on an IR from disk silently
re-verified a register corroboration had rejected -- and `build` then
emitted a full SVD and C HAL from an IR whose every register was marked
UNVERIFIED. Gates are monotonic now.

Then built a 5-chip synthetic suite, and its first run found **three false
positives** -- gates rejecting correct reads:

- alignment hardcoded to 4 bytes, failing 8-bit registers at 0x00/0x01/0x02
- `PORT_IDR` rejected against peripheral `PORTB` (instance suffixes are not
  always digits)
- two long field names merged by the tokenizer, reported as a disagreement

All three fixed; the grid check now abstains rather than guessing. Final:
118/118 fields, 7/7 errata, 0 spurious, 0 false negatives, 0 false
positives.

Also: SAM segmentation (built against the observed `<|box;...|>` token
format, not the empty `annotations` array the envelope suggests), the Rust
HAL, the source-page pane with clickable region overlays, and an
orchestrator that revealed `build` had never written the Rust HAL at all.

### What is first tomorrow

Nothing I can do alone. The four remaining items all need the user:
`modal deploy`, one real datasheet PDF, the Vercel deploy, and the video.

### Day 3, later: the UI was showing one gate out of four

The replay pane and the backend had drifted, and the drift all pointed the
same way -- the UI looked better than the run.

`extract` recorded nothing. Only `build` opened a recorder, so the only
events in any run.jsonl were codegen: the perception half, the half a judge
would actually doubt, was absent. `extract` now records page renders, every
register with its page and bbox, and all three audit verdicts.

Both commands write one run.jsonl, and both opened it in `"w"`, so `build`
erased what `extract` had just written. Appending alone was not enough: the
file then held two `run_start`s, a `run_end` in the middle of the timeline,
and a `t_ms` clock that jumped back to zero halfway through, because the
second process started its own `perf_counter`. The recorder now resumes --
drops the trailing `run_end`, pushes its origin back to where the previous
clock stopped -- so two invocations leave exactly one bracketed, monotonic
run. Six tests pin that; there were none before.

On the front end, `ProofPane` printed `bitfield overlaps: 0` and
`width conservation: 32/32 bits` as string literals, read from nothing. It
showed one gate when there are four, so name corroboration and the grid
check -- the two gates added *because* Z3 passed a wrong read three times --
were invisible. The base address was hardcoded to `0x40011000`, wrong for
four of the five benchmark chips, and the artifact list was four hardcoded
`usart1_*` filenames, so `gpio8` and `pmic32` rendered an empty code pane
and the Rust HAL never appeared for anyone.

All of it now comes from the recorded events, via `web/lib/pipeline.ts`. A
gate with no event renders **NOT RUN**, not green: Renode has never
executed, and the uart32 badge reads "3 OF 4 GATES PASSED" rather than the
old unconditional "100% VERIFIED ON RENODE".

Honest consequence worth stating: the other four fixtures were recorded
before the new gates existed, so their pages now read "1 OF 4". That is
accurate -- those runs really do only have a Z3 event -- and re-recording
them costs API calls, so it is a decision for the user rather than
something to paper over.

### Still blocked on the user

`modal deploy`, one real datasheet PDF, the Vercel deploy, the video.
