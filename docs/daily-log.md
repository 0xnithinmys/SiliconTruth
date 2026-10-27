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
