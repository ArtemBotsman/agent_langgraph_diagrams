# Reproducibility and defense demo

## Release candidate checklist

- Python version: 3.11.
- Dependencies are locked in `poetry.lock`.
- Offline CI performs lock validation, Ruff, mypy, pytest, benchmark/hash
  verification, mutation-suite verification and package build.
- CI never receives an LLM key and never performs a paid call.
- Live runs require both a local `.env` and the explicit `--allow-live` flag.
- A non-empty result directory is never overwritten.
- A failed pipeline writes reports and returns exit code 2.
- Hidden evaluation is not part of CI and remains sealed until scientific
  freeze.

## One-command offline demonstration

```bash
poetry install --with evaluation
poetry run traceable-spec \
  examples/event_signup_specification_req.json \
  artifacts/single_runs/event-signup-demo-b0 \
  --mode B0_RULE
```

The result folder contains:

- `input.json` — exact external input;
- `generated_specification.json` — complete typed result;
- `use_cases/*.md` — human-readable UC descriptions;
- `stories/*.json` — user and system stories;
- `activity_diagrams/*.mmd` — deterministic Mermaid sources;
- `trace_manifest.json` — all forward/reverse trace links;
- `validation_reports.json` — detected issues and quality gates;
- `evaluation_report.json` and `quality_report.md` — automatic measures;
- `run_manifest.json` — mode, model/provider metadata, input hash and Git state;
- `checkpoints.sqlite` and sanitized call telemetry additionally appear in FULL.

## Full two-agent demonstration

```bash
poetry run traceable-spec \
  examples/event_signup_specification_req.json \
  artifacts/single_runs/event-signup-demo-full \
  --mode FULL --allow-live --env-file .env
```

Before this command, set a call/token budget in `.env`. Never show or commit
the file. The defense should use saved PNG/JSON as a backup so a provider outage
or HTTP 429 cannot break the presentation.

## Offline quality gate

```bash
poetry check --lock
poetry run ruff check .
poetry run mypy src
poetry run pytest
poetry run python scripts/validate_synthetic_benchmark.py
poetry run python scripts/freeze_synthetic_benchmark.py
poetry run python scripts/run_validator_mutation_suite.py --check-existing
poetry run python scripts/verify_saved_experiment.py \
  artifacts/benchmark_runs/b0-dev20-r3-2026-09-09
poetry run python scripts/verify_saved_experiment.py \
  artifacts/benchmark_runs/repeated-b0-b1-full-dev001-2026-09-09
poetry build
```

Expected current result: 82 tests, 30/30 benchmark cases valid, frozen hashes
unchanged, 15/15 declared mutation classes detected, wheel and sdist built.

## Saved-result verification and error analysis

The verifier recalculates aggregate metrics, repeat stability and SHA-256 from
saved result bundles. It never calls an LLM:

```bash
poetry run python scripts/verify_saved_experiment.py \
  artifacts/benchmark_runs/b0-dev20-r3-2026-09-09 --write-report
poetry run python scripts/analyze_saved_experiment.py \
  artifacts/benchmark_runs/b0-dev20-r3-2026-09-09 --write-report
```

The error report separates exceptions, controlled pipeline failures, final E2E
failures, unresolved validation issues and issues detected then repaired.

## Optional private raw evidence

Public bundles keep prompt/response hashes and sanitized telemetry. A strict
experiment may additionally capture exact request and response JSON in a
private directory:

```bash
poetry run python scripts/run_benchmark_experiment.py \
  --condition B1_ONESHOT --case-id B1-DEV-002 --repeats 1 \
  --allow-live --max-live-calls 10 --max-live-tokens 100000 \
  --max-estimated-cost-usd 0.10 \
  --capture-raw-private-dir .private_experiment_evidence
```

This mode is explicit. The directory has restrictive permissions, the API key
is never part of the recorded request, its absolute path is not written into
the public experiment config, and `.private_experiment_evidence/` is ignored by
Git. Apply the approved provider retention policy before enabling it.

## Controlled component variants (управляемые варианты без отдельных компонентов)

The same runner now defines two variants of the developed system:

- `FULL_NO_CRITIC` keeps generators, deterministic validators and repair but
  disables both semantic critic calls; the saved reports explicitly say that
  the critic was disabled;
- `FULL_NO_REPAIR` keeps generation, validators and critics but sets the repair
  limit to zero, so the first rejected result becomes a controlled failure.

Together with `FULL`, these are the required three internal configurations.
They are implemented, tested and executed on three representative DEV cases.
B0/B1 remain comparison baselines, not internal component variants.

## Staged paid-run budget

The reproducible estimate is in
`artifacts/research_summary_2026-09-09/live_dev20_budget_estimate.json`.
Based on the DEV-001 pilot and current conservative peak/cache-miss DeepSeek
prices, the recommended first step is three representative cases once:
approximately 212,070 tokens and $0.15 expected, guarded by 60 calls, 450,000
tokens and a $0.40 soft cost threshold. The full DEV20 × 3 B1/FULL estimate is
about 4.41M tokens and $3.20 at peak pricing, guarded at $7.00. Recalculate
after the representative stage because the estimate extrapolates one case.

Running all four live conditions (`B1`, `FULL`, `FULL_NO_CRITIC`,
`FULL_NO_REPAIR`) on the three representative cases once is conservatively
estimated at 546,520 tokens, 125 calls and $0.38 peak; recommended guards are
160 calls, 1.2M tokens and $0.90. The two component variants currently inherit FULL usage
in the estimate until their first real measurement.

## Five-minute defense scenario

1. Show the six-field `SpecificationReq` input.
2. Show the root graph and explain that it orchestrates two agents.
3. Open one UC Markdown file and its user/system stories.
4. Open the Activity PNG and trace one node back to a scenario step and FR.
5. Show `quality_report.md` and one intentional mutation detected by a validator.
6. Show B0/B1/FULL pilot and B0 DEV20 charts; state all limitations.
7. If live access fails, continue with saved artifacts; do not retry indefinitely.

## Remaining non-engineering gates

Two independent experts, supervisor approval, scientific freeze tag, full paid
DEV comparison and one-time hidden evaluation cannot be replaced by code or by
the author. They must remain marked pending until actually completed.
