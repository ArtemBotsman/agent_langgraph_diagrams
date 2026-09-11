# Examples

## One complete run (один полный запуск)

The project CLI accepts the supervisor-agreed `SpecificationReq` JSON and writes
UC, user/system stories, Activity Mermaid, trace, validation and quality files
into one result directory.

Offline deterministic baseline (no key and no tokens):

```bash
poetry run traceable-spec \
  examples/event_signup_specification_req.json \
  artifacts/single_runs/event-signup-b0 \
  --mode B0_RULE
```

Full two-agent LangGraph pipeline (network/paid calls require an explicit flag):

```bash
poetry run traceable-spec \
  examples/event_signup_specification_req.json \
  artifacts/single_runs/event-signup-full \
  --mode FULL --allow-live --env-file .env
```

The command never overwrites a non-empty output directory. A failed pipeline
still writes its reports and exits with code `2`, so critical errors are visible
to a human or CI process.

## `run_uc_scripted_pipeline.py`

Offline vertical slice of the Use Cases LangGraph using **`ScriptedLLMClient`**.

This is a **scripted/fake** client for orchestration testing. It is **not** a real
model call and must not be presented as AI generation quality evidence.

```bash
poetry run python examples/run_uc_scripted_pipeline.py
```
