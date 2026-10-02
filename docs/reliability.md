# Reliability policy

Milestone 3 adds explicit reliability controls around each HTTP attempt. BulkRelay still executes
records sequentially; bounded concurrency belongs to Milestone 4.

## Timeouts

Timeouts are configured per HTTPX timeout phase:

```yaml
execution:
  timeout:
    connect_seconds: 10
    read_seconds: 30
    write_seconds: 30
    pool_seconds: 5
```

All values must be greater than zero. Timeout failures are recorded as `timeout_error` and are
retryable by default until the configured attempt budget is exhausted.

## Retry policy

```yaml
retry:
  max_attempts: 4
  statuses: [408, 425, 429, 500, 502, 503, 504]
  initial_backoff_seconds: 1
  max_backoff_seconds: 30
  jitter_ratio: 0.2
  respect_retry_after: true
```

`max_attempts` includes the first request. For example, `max_attempts: 4` allows one initial request
plus at most three retries.

Retries are deliberately **opt-in**: the default is `max_attempts: 1`. BulkRelay currently sends
`POST` requests, and an ambiguous timeout can happen after the remote server has already committed a
side effect. Until idempotency-key support lands, silently retrying such a request by default could
create duplicates. If you enable retries, choose an endpoint whose retry semantics you understand.

BulkRelay retries configured HTTP status codes and transient transport failures such as timeouts,
connection failures, remote protocol failures, and proxy transport errors. Other 4xx responses are
not retried unless the user explicitly adds the status code.

### Backoff

Without a valid `Retry-After` header, retries use capped exponential backoff. The delay after failed
attempt `n` is based on:

```text
initial_backoff_seconds × 2^(n-1)
```

capped at `max_backoff_seconds`. `jitter_ratio` then varies that delay within a bounded percentage to
avoid synchronized retry storms. Set it to `0` for deterministic behavior.

### Retry-After

When enabled, BulkRelay accepts both forms defined for `Retry-After`:

- delta seconds, for example `Retry-After: 10`;
- HTTP dates.

A server-provided value is treated as a minimum delay. It never shortens BulkRelay's own backoff.
Malformed `Retry-After` values are ignored and normal backoff is used.

## Rate limiting

```yaml
execution:
  rate_limit:
    requests_per_second: 10
```

The limiter controls **request starts**, not completed responses. Every HTTP attempt consumes a rate
limit slot, including retries. This distinction matters when an endpoint is both slow and
rate-limited.

Rate limiting and retry delays compose safely: after a retry delay expires, the next attempt still
waits for the global rate limiter if necessary.

## Reporting

Each record now reports:

- `attempts`: total HTTP attempts for that record;
- `retryable`: whether the final failure class was eligible for retry;
- final response/error classification.

The run summary also includes total HTTP attempts and the number of records that required at least
one retry.

A `retryable: true` final failure means the configured attempt budget was exhausted; it does **not**
mean BulkRelay silently abandoned retries early.
