# BulkRelay

> **Milestone 2:** correctness-first bulk HTTP jobs from CSV and JSONL.

BulkRelay is a small, config-driven CLI for turning flat-file records into HTTP requests without
silently accepting malformed input or misspelled configuration. Milestone 2 adds a full preflight
layer before the later reliability work on retries, rate limiting, concurrency, and resume.

## What works now

- strict, validated YAML configuration (`extra` fields are rejected);
- streaming CSV and JSONL/NDJSON input;
- CSV header/row integrity checks;
- JSONL line-level syntax and object-shape diagnostics;
- declarative JSON-body mapping from input fields and constants;
- complete preflight of every input record **before the first HTTP side effect**;
- `bulkrelay validate` for offline config/input/mapping verification;
- sequential HTTP `POST` execution;
- explicit result classification (`success`, client/server/redirect/network errors);
- append-only `results.jsonl` plus `summary.json`;
- non-zero CLI exit status when any request fails;
- a deterministic FastAPI target for local demos and tests;
- unit and integration coverage for CSV, JSONL, diagnostics, preflight, and execution.

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
```

Start the fake target API in one terminal:

```bash
uv run uvicorn examples.fake_api.app:app --reload
```

Validate a job without making any HTTP requests:

```bash
uv run bulkrelay validate examples/basic/job.yaml
```

Run it:

```bash
uv run bulkrelay run examples/basic/job.yaml
```

The demo intentionally contains one rejected record, so `run` exits with status `1` while still
writing a complete report under `.bulkrelay/runs/`.

A JSONL example uses the identical pipeline:

```bash
uv run bulkrelay validate examples/jsonl/job.yaml
uv run bulkrelay run examples/jsonl/job.yaml
```

## Configuration

```yaml
version: 1

input:
  file: customers.csv

request:
  method: POST
  url: http://127.0.0.1:8000/users
  headers:
    X-Demo-Client: bulkrelay
  json:
    email:
      from: email
    first_name:
      from: first_name
    source:
      value: bulkrelay-demo
```

`input.file` is resolved relative to the YAML config file. Unknown config fields are rejected rather
than silently ignored. See [`docs/configuration.md`](docs/configuration.md) for correctness rules.

## Input correctness

Supported extensions:

- `.csv`;
- `.jsonl`;
- `.ndjson`.

CSV has a fixed header schema, so missing mapped columns are reported before records are scanned.
JSONL may have heterogeneous object shapes, so mappings are checked on every line. JSON types are
preserved for JSONL rather than coerced to strings.

BulkRelay performs a complete streaming preflight before execution. A malformed record at the end of
a file therefore prevents **all** HTTP requests instead of failing after earlier records have already
modified the remote system.

See [`docs/input-formats.md`](docs/input-formats.md).

## Diagnostics

A typo such as:

```yaml
email:
  from: customer_email
```

against a file containing `email` produces a targeted diagnostic:

```text
missing mapped field 'customer_email'. Did you mean 'email'?
```

Malformed JSONL points at the physical line and JSON column. Unknown YAML settings include their
configuration path.

## Output

Each run creates an isolated directory:

```text
.bulkrelay/runs/<timestamp>-<id>/
├── results.jsonl
└── summary.json
```

A result records the source row/line number, HTTP status, success flag, classification, and a bounded
error message for failures.

Example failure:

```json
{
  "row_number": 3,
  "success": false,
  "classification": "http_client_error",
  "status_code": 422,
  "error": "{\"detail\":\"fake API rejected this record\"}"
}
```

## Architecture

```text
                         ┌──────────────────┐
YAML config ───────────> │ strict validation│
                         └────────┬─────────┘
                                  │
CSV / JSONL ──> source parser ──> full preflight ──> request mapping
                                  │                    │
                                  │ valid              v
                                  └──────────────> HTTP executor
                                                       │
                                                       v
                                           results.jsonl + summary.json
```

The double streaming read during `run` is deliberate at this stage: correctness wins over avoiding a
second local file scan. It guarantees that malformed input discovered late cannot cause partial
remote writes. Future checkpoint/fingerprint work will strengthen the boundary against source-file
changes between preflight and execution.

## Deliberate Milestone 2 limits

This is not yet the production-ready release described by the roadmap. There are still **no**
retries, rate limiting, concurrency, checkpoints/resume, authentication helpers, secret
interpolation, transforms, or dry-run request rendering. Those features will be introduced with
explicit failure-path tests.

## Quality checks

```bash
uv run ruff check .
uv run mypy
uv run pytest
```

CI runs the same checks on every push and pull request.

## Roadmap

1. ✅ Vertical slice: CSV → YAML config → HTTP POST → result report.
2. ✅ Correctness layer: JSONL, strict config/input validation, preflight, diagnostics, classifications.
3. Retry policy, `Retry-After`, backoff, timeouts, and rate limiting.
4. Bounded concurrency and graceful cancellation.
5. Durable checkpoints, fingerprints, and safe resume.
6. Dry-run, retry-failed workflow, auth boundaries, and secret redaction.
7. Documentation, demo polish, packaging, benchmarks, and first public release.

## Security

Do not commit production datasets, generated run directories, tokens, or credentials. See
[`SECURITY.md`](SECURITY.md).

## License

MIT.
