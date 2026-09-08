# Pyreverse static-analysis baseline

This directory contains a deterministic code-to-UML baseline generated from
the Python sources in `src/traceable_spec`.

It answers a different question from the main research pipeline:

- Pyreverse input: existing Python code;
- Pyreverse output: class and package structure;
- main pipeline input: functional and non-functional requirements;
- main pipeline output: traceable Use Cases and activity diagrams before code
  exists.

Reproduce the baseline from the repository root:

```bash
poetry install
./scripts/run_static_analysis_baseline.sh
```

Generated files:

- `classes_traceable_spec_code_baseline.mmd` — Mermaid class diagram source;
- `packages_traceable_spec_code_baseline.mmd` — Mermaid package diagram source.

Recorded tool version for the first run: Pyreverse from Pylint 4.0.8.
