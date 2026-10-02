# BulkRelay

> **Milestone 4:** bounded concurrent bulk HTTP jobs with graceful interruption semantics.

BulkRelay is a config-driven CLI for turning CSV or JSONL records into reliable HTTP requests. It
validates the complete input before the first remote side effect, then executes records through a bounded-concurrency scheduler under explicit timeout, retry,
and rate-limit policy and writes an auditable result report.

## What works now

- strict YAML configuration with duplicate-key and unknown-field rejection;
- streaming CSV and JSONL/NDJSON input;
- complete preflight of every record **before the first HTTP side effect**;
- declarative JSON-body mapping from input fields and constants;
- `bulkrelay validate` for offline config/input/mapping verification;
- bounded concurrent HTTP `POST` execution with configurable `concurrency`;
- phase-specific connect/read/write/pool timeouts;
- configurable retryable HTTP statuses and transport failures;
- capped exponential backoff with bounded jitter;
- `Retry-After` support for delta-seconds and HTTP-date values;
- global requests-per-second pacing applied to every attempt, including retries;
- first-`Ctrl+C` graceful stop that finishes only already-active records;
- second-`Ctrl+C` escalation that cancels remaining in-flight tasks;
- explicit result classification for HTTP, timeout, and network failures;
- per-record attempt counts and retryability metadata;
- append-only `results.jsonl` plus `summary.json`;
- deterministic fake API scenarios for success, rejection, 429, 503, timeout, recovery, and concurrent work;
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

### Concurrency demo

The fake `/concurrent/users` endpoint deliberately pauses each request for 250 ms. Four input records
can be executed with a bounded window of four active records:

```bash
uv run bulkrelay run examples/concurrency/job.yaml
```

`concurrency` limits active logical records; it does not disable the global rate limiter. Retries keep
their record slot and every retry attempt still passes through the same request-start limiter.

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
  concurrency: 8
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
See [`docs/configuration.md`](docs/configuration.md), [`docs/reliability.md`](docs/reliability.md),
and [`docs/concurrency.md`](docs/concurrency.md).

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

With concurrent execution, `results.jsonl` is written in completion order; `row_number` remains the
stable source identity for each result.

The summary includes source size, completed logical records, and actual HTTP work separately:

```json
{
  "total": 100,
  "succeeded": 99,
  "failed": 1,
  "attempts": 114,
  "retried": 9,
  "input_total": 100,
  "stopped_early": false,
  "forced": false,
  "unprocessed": 0
}
```

## Architecture

```text
                         ┌──────────────────┐
YAML config ───────────> │ strict validation│
                         └────────┬─────────┘
                                  │
CSV / JSONL ──> source parser ──> full preflight ──> request mapping
                                                        │
                                                        v
                                           bounded task window
                                          (≤ concurrency records)
                                            /      |       \
                                           v       v        v
                                      record    record    record
                                        │          │         │
                                        └──── shared ────────┘
                                               │
                                       global rate limiter
                                               │
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
                                  └──────────> global rate limiter
```

The scheduler never creates one task per source record. It keeps only a bounded active window. On the
first interrupt it stops filling that window and lets existing record tasks finish. A second interrupt
cancels the remaining tasks and marks the run as forced.

## Graceful interruption

First `Ctrl+C`:

```text
stop scheduling new records → finish active records → write summary → exit 130
```

Second `Ctrl+C`:

```text
cancel active tasks → write forced summary → exit 130
```

Forced cancellation can leave remote side effects ambiguous: the server may have committed a request
before the local coroutine was cancelled. See [`docs/concurrency.md`](docs/concurrency.md).

## Deliberate Milestone 4 limits

This is still an alpha portfolio build, not the first public release. There are **no** durable
checkpoints/resume, authentication helpers, secret interpolation/redaction, transforms, dry-run
request rendering, or idempotency-key support yet. Because resume is not available, a stopped job must
not be blindly rerun against a non-idempotent endpoint.

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
4. ✅ Bounded concurrency and graceful cancellation.
5. Durable checkpoints, fingerprints, and safe resume.
6. Dry-run, retry-failed workflow, auth boundaries, and secret redaction.
7. Documentation, demo polish, packaging, benchmarks, and first public release.

## Security

Do not commit production datasets, generated run directories, tokens, or credentials. See
[`SECURITY.md`](SECURITY.md).

## License

MIT.
