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
