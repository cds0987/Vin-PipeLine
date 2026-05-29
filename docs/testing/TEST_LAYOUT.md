# Test Layout

The test suite is organized around two goals:

1. `tests/general/`
   Happy-path workflow coverage for the main system flows.
   These tests answer "does the expected end-to-end behavior still work?"

2. Domain folders for edge cases and lower-level behavior
   These tests focus on failure modes, validation, and domain-specific rules.

## Directory guide

- `tests/general/`
  Core workflow smoke tests for API, pipeline, and streaming.

- `tests/api/`
  API validation, coordination, and request-level edge cases.

- `tests/adapters/`
  Adapter behavior such as S3 scanning logic and source integration rules.

- `tests/pipeline/`
  Parse, chunk, clean, embed, index, and orchestration edge cases.

- `tests/retrieval/`
  Search scoring, thresholding, and retrieval-specific behavior.

- `tests/stores/`
  Vector store and metadata store behavior, including integrations.

- `tests/streaming/`
  Kafka mapping, retries, DLQ handling, and consumer edge cases.

- `tests/utils/`
  Utility helpers such as storage, mapping, and AI provider behavior.

## Running tests

Use the default suite:

```powershell
pytest tests -q
```

If the local environment has issues with pytest's temp-dir plugin, this repo also works with:

```powershell
pytest tests -q -p no:tmpdir
```
