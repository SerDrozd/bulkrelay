# BulkRelay

> **Milestone 3:** correctness-first bulk HTTP jobs with explicit retry, timeout, and rate-limit policy.

BulkRelay is a config-driven CLI for turning CSV or JSONL records into reliable HTTP requests. It
validates the complete input before the first remote side effect, then executes each record under a
bounded timeout/retry policy and writes an auditable result report.

## What works now

- strict YAML configuration with duplicate-key and unknown-field rejection;
- streaming CSV and JSONL/NDJSON input;
- complete preflight of every record **before the first HTTP side effect**;
- declarative JSON-body mapping from input fields and constants;
- `bulkrelay validate` for offline config/input/mapping verification;
- sequential HTTP `POST` execution;
- phase-specific connect/read/write/pool timeouts;
- configurable retryable HTTP statuses and transport failures;
- capped exponential backoff with bounded jitter;
- `Retry-After` support for delta-seconds and HTTP-date values;
- global requests-per-second pacing applied to every attempt, including retries;
- explicit result classification for HTTP, timeout, and network failures;
- per-record attempt counts and retryability metadata;
- append-only `results.jsonl` plus `summary.json`;
- deterministic fake API scenarios for success, rejection, 429, 503, timeout, and recovery;
- unit and integration tests for correctness and reliability behavior.

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
```

Start the fake target API in one terminal:

```bash
uv run uvicorn examples.fake_api.app:app --reload
```

Validate a job without making HTTP requests:

```bash
uv run bulkrelay validate examples/basic/job.yaml
```

Run it:

```bash
uv run bulkrelay run examples/basic/job.yaml
```

The basic demo intentionally contains one permanent `422` rejection, so `run` exits with status `1`
while still writing a complete report under `.bulkrelay/runs/`.

### Reliability demo

The fake `/unstable/users` endpoint returns `503` twice per email and then recovers. Reset its counters
and run the job:

```bash
curl -X POST http://127.0.0.1:8000/reset
uv run bulkrelay run examples/reliability/job.yaml
```

Each record should succeed on its third attempt. The report will record those attempts rather than
hiding them behind a final `201`.

## Configuration

```yaml
version: 1

input:
  file: customers.csv

request:
  method: POST
  url: https://api.example.com/v1/customers
  headers:
    X-Demo-Client: bulkrelay
  json:
    email:
      from: email
    first_name:
      from: first_name
    source:
      value: migration

execution:
  timeout:
    connect_seconds: 10
    read_seconds: 30
    write_seconds: 30
    pool_seconds: 5
  rate_limit:
    requests_per_second: 10

retry:
  max_attempts: 4
  statuses: [408, 425, 429, 500, 502, 503, 504]
  initial_backoff_seconds: 1
  max_backoff_seconds: 30
  jitter_ratio: 0.2
  respect_retry_after: true
```

`max_attempts` includes the initial request. A value of `4` therefore allows at most three retries.
Retries are opt-in (`max_attempts` defaults to `1`) because retrying an ambiguous `POST` timeout can
duplicate a remote side effect when the target API does not support idempotency.
See [`docs/configuration.md`](docs/configuration.md) and [`docs/reliability.md`](docs/reliability.md).

## Correctness before side effects

BulkRelay performs a complete streaming preflight before execution. A malformed record at the end of
a file therefore prevents **all** HTTP requests instead of failing after earlier records have already
modified the remote system.

Supported extensions:

- `.csv`;
- `.jsonl`;
- `.ndjson`.

See [`docs/input-formats.md`](docs/input-formats.md).

## Retry semantics

Retries are explicit rather than "retry every error".

Default retryable statuses are:

```text
408 425 429 500 502 503 504
```

Transient HTTPX transport failures such as timeouts and connection failures are retryable. A normal
`400`, `401`, `403`, `404`, or `422` is not retried unless explicitly configured.

When a retryable response includes `Retry-After`, BulkRelay treats it as a minimum wait. Otherwise it
uses capped exponential backoff plus jitter. Every retry still passes through the global rate limiter.

## Output

Each run creates an isolated directory:

```text
.bulkrelay/runs/<timestamp>-<id>/
├── results.jsonl
└── summary.json
```

A final failed record may look like:

```json
{
  "row_number": 3,
  "success": false,
  "classification": "http_server_error",
  "status_code": 503,
  "attempts": 3,
  "retryable": true,
  "error": "{\"detail\":\"still unavailable\"}"
}
```

`retryable: true` on a final failure means the retry budget was exhausted, not that BulkRelay skipped
an available retry.

The summary includes logical records and actual HTTP work separately:

```json
{
  "total": 100,
  "succeeded": 99,
  "failed": 1,
  "attempts": 114,
  "retried": 9
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
                                  └──────────> rate limiter
                                                   │
                                                   v
                                              HTTP attempt
                                             /            \
                                       success         failure
                                                        │
                                              retry classification
                                                        │
                                      ┌─────────────────┴──────────────┐
                                      │ retryable + budget remains     │ final
                                      v                                v
                               Retry-After / backoff              result report
                                      │
                                      └──────────> rate limiter
```

Execution is intentionally sequential in Milestone 3. The rate limiter is already isolated behind a
small async component so Milestone 4 can add bounded workers without changing retry semantics.

## Deliberate Milestone 3 limits

This is still an alpha portfolio build, not the first public release. There are **no** bounded
concurrent workers, graceful cancellation protocol, durable checkpoints/resume, authentication
helpers, secret interpolation/redaction, transforms, or dry-run request rendering yet.

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
3. ✅ Reliability layer: timeout policy, retries, `Retry-After`, exponential backoff, jitter, rate limit.
4. Bounded concurrency and graceful cancellation.
5. Durable checkpoints, fingerprints, and safe resume.
6. Dry-run, retry-failed workflow, auth boundaries, and secret redaction.
7. Documentation, demo polish, packaging, benchmarks, and first public release.

## Security

Do not commit production datasets, generated run directories, tokens, or credentials. See
[`SECURITY.md`](SECURITY.md).

## License

MIT.
