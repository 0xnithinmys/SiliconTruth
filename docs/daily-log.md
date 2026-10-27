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
