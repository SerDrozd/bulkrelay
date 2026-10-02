# BulkRelay

> **Milestone 1:** reliable foundations for turning CSV records into HTTP POST requests.

BulkRelay is a small, config-driven CLI for bulk HTTP jobs. This first vertical slice deliberately
implements one path end-to-end before adding concurrency, retries, rate limiting, checkpoints, and
resume semantics.

## What works now

- validated YAML job configuration;
- streaming CSV input;
- declarative JSON-body mapping from CSV columns and constants;
- sequential HTTP `POST` execution;
- per-record success/failure capture;
- append-only `results.jsonl` plus `summary.json`;
- non-zero CLI exit status when any record fails;
- a deterministic FastAPI target for local demos and tests;
- unit and integration coverage for the complete vertical slice.

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
```

Start the fake target API in one terminal:

```bash
uv run uvicorn examples.fake_api.app:app --reload
```

Run the example job in another:

```bash
uv run bulkrelay run examples/basic/job.yaml
```

The demo intentionally contains one rejected record, so the command exits with status `1` while
still writing a complete report under `.bulkrelay/runs/`.

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

`input.file` is resolved relative to the YAML config file, which keeps examples and migration jobs
portable.

## Output

Each run creates an isolated directory:

```text
.bulkrelay/runs/<timestamp>-<id>/
├── results.jsonl
└── summary.json
```

A result row currently records the input row number, HTTP status, success flag, and a bounded error
message for failures.

## Architecture

```text
YAML config ──> Pydantic validation
                    │
CSV ──> streaming reader ──> declarative mapper ──> HTTP executor
                                                     │
                                                     v
                                      results.jsonl + summary.json
```

The CLI is intentionally thin. Configuration, input, mapping, execution, and reporting are separate
modules so later reliability features can be added without turning the command layer into the core.

## Deliberate Milestone 1 limits

This is not yet the production-ready release described by the project roadmap. The first milestone
intentionally has **no** retries, rate limiting, concurrency, checkpoints/resume, authentication
helpers, secret interpolation, JSONL input, or transforms. Those belong to later milestones and will
be introduced with explicit failure-path tests.

## Quality checks

```bash
uv run ruff check .
uv run mypy
uv run pytest
```

CI runs the same checks on every push and pull request.

## Roadmap

1. ✅ Vertical slice: CSV → YAML config → HTTP POST → result report.
2. Input/config correctness and richer validation.
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
