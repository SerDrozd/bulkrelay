# Concurrency and shutdown

BulkRelay uses bounded concurrency so large inputs do not turn into an unbounded number of asyncio tasks.

## Bounded concurrency

Configure the maximum number of logical records that may be active at once:

```yaml
execution:
  concurrency: 8
```

`concurrency` accepts values from `1` through `100` and defaults to `1`.

The scheduler keeps at most `concurrency` record tasks active. When one record reaches a final result, another record may enter the active window. This bounds both task count and in-flight work even when the input contains hundreds of thousands of rows.

A record keeps its concurrency slot while it retries. Every HTTP attempt still passes through the same global request-rate limiter, so these controls are independent:

- `concurrency` limits active logical records;
- `rate_limit.requests_per_second` limits HTTP request starts, including retries.

Increasing concurrency does not bypass the configured request rate.

## Result ordering

With `concurrency > 1`, records can finish in a different order from the input.

`results.jsonl` is append-only and records results in completion order. Each entry keeps its original `row_number`, which is the stable link back to the source file.

Do not rely on journal line position when joining results back to the input.

## Graceful shutdown

The first `Ctrl+C` requests a cooperative stop:

1. BulkRelay stops scheduling new records.
2. Records already in the active window are allowed to finish, including configured retries.
3. Final results are persisted to `results.jsonl`.
4. The checkpoint and summary are updated.
5. The CLI exits with status `130`.

This is intentionally different from cancelling every task immediately. For a migration tool, a known final result for work already in progress is usually more useful than a faster shutdown with more ambiguous requests.

An interrupted run can be continued with `bulkrelay resume` after the stored input and configuration fingerprints are verified. See [Checkpoints and safe resume](resume.md).

## Force stop

Pressing `Ctrl+C` a second time escalates the shutdown and cancels the remaining in-flight record tasks.

BulkRelay still writes run state when possible, marks the run as forced, and exits with status `130`.

A cancelled local HTTP coroutine does not prove that the remote server did not commit the request. The server may have completed the operation before the response reached BulkRelay. For that reason, a forced stop can leave ambiguous remote side effects.

Prefer the first, graceful interrupt unless immediate termination is necessary.

## Summary fields after interruption

A stopped run separates the number of source records from the number of records that reached a durable final result:

```json
{
  "total": 3,
  "succeeded": 3,
  "failed": 0,
  "attempts": 3,
  "retried": 0,
  "input_total": 8,
  "stopped_early": true,
  "forced": false,
  "unprocessed": 5
}
```

`total` is the number of records with a persisted final result. `input_total` is the number of records that passed preflight. `unprocessed` is the number of source records that still have no durable final result.
