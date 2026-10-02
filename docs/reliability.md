# Reliability policy

BulkRelay applies the same timeout, retry, and request-rate policy to every HTTP attempt, whether records run sequentially or through the bounded-concurrency scheduler.

Concurrency is a separate concern. See [Concurrency and shutdown](concurrency.md).

## Timeouts

Timeouts are configured by HTTPX timeout phase:

```yaml
execution:
  timeout:
    connect_seconds: 10
    read_seconds: 30
    write_seconds: 30
    pool_seconds: 5
```

All values must be greater than zero.

Timeout failures are classified as `timeout_error`. When retries are enabled, timeout failures are eligible for another attempt until the configured attempt budget is exhausted.

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

`max_attempts` includes the first request. For example, `max_attempts: 4` means one initial request plus at most three retries.

Retries are opt-in. The default is `max_attempts: 1`.

That default matters because BulkRelay currently sends side-effecting `POST` requests. A timeout can occur after the remote server has already committed the operation, so automatically retrying every timeout can create duplicates on APIs that do not provide idempotency guarantees.

Enable retries only when you understand the target endpoint's retry behavior.

BulkRelay can retry configured HTTP status codes and transient transport failures such as:

- connection failures;
- connect, read, write, and pool timeouts;
- remote protocol failures;
- proxy transport failures.

Other client errors are not retried unless their status code is explicitly added to the configuration.

## Exponential backoff

When there is no valid `Retry-After` header, retries use capped exponential backoff.

The base delay after failed attempt `n` is:

```text
initial_backoff_seconds * 2^(n-1)
```

The value is capped at `max_backoff_seconds`.

`jitter_ratio` then varies the delay within a bounded range to reduce synchronized retry bursts. Set `jitter_ratio` to `0` when deterministic timing is preferable.

## Retry-After

When `respect_retry_after` is enabled, BulkRelay accepts both standard forms:

- delta seconds, such as `Retry-After: 10`;
- HTTP dates.

A valid server-provided value is treated as a minimum delay. It does not shorten BulkRelay's own backoff.

Malformed `Retry-After` values are ignored and normal backoff is used instead.

## Rate limiting

Configure the global request-start rate with:

```yaml
execution:
  rate_limit:
    requests_per_second: 10
```

The limiter controls HTTP request starts, not completed responses.

Every attempt consumes a rate-limit slot, including retries. This means higher concurrency cannot cause retry traffic to exceed the configured request rate.

Retry delays and rate limiting compose in sequence. After a retry delay expires, the next attempt still waits for the global limiter if no request slot is available yet.

## Reporting

Each final record result includes:

- `attempts`: total HTTP attempts for that record;
- `retryable`: whether the final failure class was eligible for retry;
- the final response or transport classification.

The run summary also records total HTTP attempts and how many logical records required at least one retry.

A final result with `retryable: true` means the failure class was retryable but the configured attempt budget was exhausted. It does not mean BulkRelay skipped an available retry.
