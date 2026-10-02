# BulkRelay

[![CI](https://github.com/SerDrozd/bulkrelay/actions/workflows/ci.yml/badge.svg)](https://github.com/SerDrozd/bulkrelay/actions/workflows/ci.yml)

Reliable bulk HTTP jobs from CSV and JSONL files.

BulkRelay is a Python CLI for migrations, backfills, and one-off API jobs where a simple `for row in csv: requests.post(...)` script is not enough.

It validates the full input before sending anything, keeps concurrency and request rate bounded, handles retryable failures, records every final result, and can resume interrupted runs without replaying rows that were already persisted locally.

> **Status:** alpha. The execution and recovery model is tested, but the CLI and configuration format may still change before `0.1.0`.

## Why BulkRelay exists

Bulk API work usually starts simple and stops being simple when something goes wrong.

A migration script has to answer questions such as:

- What happens when row 18,431 is malformed?
- What happens after a `429` or temporary `503`?
- Can retries exceed the target API's rate limit?
- What if the process is interrupted halfway through?
- How do you know which rows actually finished?
- Is it safe to resume after the input file or config changed?

BulkRelay handles those concerns explicitly so the job can stay small without being fragile.

## What it does

- Reads CSV and JSONL/NDJSON input as a stream.
- Validates the complete input and request mapping before the first HTTP side effect.
- Builds JSON `POST` requests from input fields and constant values.
- Rejects unknown config keys, duplicate YAML keys, malformed input, and invalid mappings.
- Runs a bounded number of records concurrently instead of creating one task per row.
- Applies one global requests-per-second limit to all attempts, including retries.
- Supports connect, read, write, and pool timeouts.
- Supports configurable retry status codes, exponential backoff, jitter, and `Retry-After`.
- Stops gracefully on the first `Ctrl+C` and force-cancels on the second.
- Writes an append-only `results.jsonl` journal plus run metadata and summary files.
- Verifies input and configuration fingerprints before resuming an interrupted run.
- Detects malformed or duplicate entries in an existing result journal before resume.

## Quick start

BulkRelay currently targets Python 3.12+ and uses [uv](https://docs.astral.sh/uv/) for development.

```bash
git clone https://github.com/SerDrozd/bulkrelay.git
cd bulkrelay
uv sync
```

Start the bundled fake API in one terminal:

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

The basic demo includes one intentional `422` response so you can see how a permanent failure is recorded without hiding the rest of the run.

## Job configuration

A job is a YAML file that points to an input file and describes the request to build for each record.

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

`max_attempts` includes the first request. Retries are disabled by default because automatically retrying an ambiguous `POST` can create duplicates when the target API does not support idempotency.

See [Configuration](docs/configuration.md) for the full contract.

## Preflight before side effects

BulkRelay validates the entire source before execution starts.

That means a malformed record near the end of a file causes the run to fail before any HTTP request is sent. This is intentional. A bulk migration should not discover a structural input problem after it has already modified the remote system.

Supported input formats:

| Format | Behavior |
| --- | --- |
| CSV | UTF-8, unique non-empty headers, values mapped as strings |
| JSONL / NDJSON | One JSON object per line, JSON types preserved |

See [Input formats](docs/input-formats.md).

## Reliability model

### Bounded concurrency

`execution.concurrency` limits the number of logical records that can be active at once.

BulkRelay does not create one asyncio task per source row. It keeps a bounded active window and starts another record only when a slot becomes available.

### Rate limiting

`execution.rate_limit.requests_per_second` controls HTTP request starts across the whole run. Retries use the same limiter, so increasing concurrency cannot bypass the configured request rate.

### Retries

Retries are policy-driven, not "retry every error".

By default, the retryable status set is:

```text
408 425 429 500 502 503 504
```

Transient transport failures are also eligible when retries are enabled. Normal permanent client errors such as `400`, `401`, `403`, `404`, and `422` are not retried unless the config explicitly says otherwise.

If a retryable response contains `Retry-After`, BulkRelay treats it as a minimum delay. Otherwise it uses capped exponential backoff with jitter.

See [Reliability policy](docs/reliability.md).

## Run output

Every run gets its own directory:

```text
.bulkrelay/runs/<run-id>/
├── run.json
├── checkpoint.json
├── results.jsonl
└── summary.json
```

`results.jsonl` is the append-only journal of completed records. With concurrent execution, entries are written in completion order, so `row_number` is the stable link back to the source input.

A failed result may look like this:

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

The summary keeps logical record counts separate from actual HTTP attempts:

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
  "resumed": false,
  "unprocessed": 0
}
```

## Interruption and resume

The first `Ctrl+C` stops scheduling new records and lets active records finish. A second `Ctrl+C` cancels the remaining in-flight tasks.

Resume an interrupted run with:

```bash
uv run bulkrelay resume .bulkrelay/runs/<run-id>
```

Before sending another request, BulkRelay:

1. runs preflight again;
2. verifies the input format, SHA-256, byte size, and record count;
3. verifies the semantic job configuration fingerprint;
4. validates the existing result journal;
5. rebuilds the set of completed source rows;
6. schedules only records that do not already have a durable final result.

If the input or relevant job configuration changed, resume fails closed.

This prevents replay of rows whose results were already persisted locally. It does **not** provide exactly-once delivery to an arbitrary remote API. If the remote server commits a request and the local process dies before the result is written, that row is ambiguous and may be sent again.

See [Checkpoints and safe resume](docs/resume.md).

## Architecture

```text
                 YAML config
                     |
                     v
              strict validation
                     |
CSV / JSONL -> full preflight -> request mapping
                                     |
                                     v
                            bounded scheduler
                              /    |    \
                             v     v     v
                          record record record
                              \    |    /
                               \   |   /
                           global rate limiter
                                   |
                                   v
                              HTTP attempt
                              /          \
                         success        failure
                                           |
                                  retry classification
                                    /            \
                              retryable          final
                                  |                |
                         backoff / Retry-After     |
                                  |                |
                                  +-------> result journal
```

The scheduler, retry policy, rate limiter, and run-state layer are separate modules so each behavior can be tested without requiring a live third-party API.

## Current limitations

BulkRelay is intentionally narrow at this stage.

- Requests are currently `POST` only.
- There are no built-in OAuth flows or provider-specific authentication helpers.
- Secret interpolation and log redaction are not implemented yet.
- There is no dry-run request renderer yet.
- There is no separate retry-failed command for completed runs yet.
- Idempotency-key support is not implemented yet.
- Resume protects locally persisted results, not remote exactly-once delivery.

These are product boundaries, not hidden guarantees.

## Development

Install the project and development tools:

```bash
uv sync
```

Run the quality checks:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

The current test suite covers config and input validation, request mapping, retry policy, rate limiting, concurrency, shutdown behavior, run-state corruption checks, and interrupted-run recovery.

## Documentation

- [Configuration](docs/configuration.md)
- [Input formats](docs/input-formats.md)
- [Reliability policy](docs/reliability.md)
- [Concurrency and shutdown](docs/concurrency.md)
- [Checkpoints and safe resume](docs/resume.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Roadmap

The next work is focused on operational safety and release polish:

- secret interpolation and redaction;
- dry-run request rendering;
- explicit idempotency-key support;
- retrying selected failures from completed runs;
- packaging and install UX;
- reproducible benchmarks;
- release documentation and demo assets.

## License

MIT. See [LICENSE](LICENSE).
