# Concurrency and shutdown

Milestone 4 adds bounded concurrent execution without changing BulkRelay's retry and rate-limit
semantics.

## Bounded concurrency

```yaml
execution:
  concurrency: 8
```

`concurrency` is the maximum number of logical records that may be active at once. It accepts values
from `1` through `100` and defaults to `1`.

BulkRelay does **not** create one asyncio task per input row. The scheduler keeps only a window of at
most `concurrency` record tasks alive. When one record finishes, the next record may enter the window.
This keeps task count and in-flight work bounded even for very large files.

A record keeps its concurrency slot while it retries. Every individual HTTP attempt still passes
through the single global requests-per-second limiter. Therefore these controls remain independent:

- `concurrency` bounds simultaneous logical records;
- `rate_limit.requests_per_second` bounds HTTP request starts, including retries.

High concurrency does not bypass the rate limit.

Because records can finish out of order, `results.jsonl` is append-only in completion order when
`concurrency > 1`. Every entry retains its stable `row_number`, so callers should use that field rather
than line position when joining results back to the source data.

## Graceful Ctrl+C

The first `Ctrl+C` requests a cooperative stop:

1. no new input records are started;
2. records already in the active window are allowed to finish, including their configured retries;
3. completed results are written to `results.jsonl`;
4. `summary.json` records how many input records remain unprocessed;
5. the CLI exits with status `130`.

This is deliberately different from cancelling every asyncio task immediately. A migration tool
should prefer a known result for work already in progress.

Milestone 4 does not yet have durable checkpoints or resume. If a graceful stop leaves records
unprocessed, do not assume that blindly rerunning a non-idempotent POST job is safe. Check the remote
system first or wait for Milestone 5's checkpoint/resume layer.

## Force stop

Pressing `Ctrl+C` a second time escalates the stop and cancels remaining in-flight record tasks.
The CLI still writes a summary when it can, marks the run as forced, and exits with status `130`.

A forced cancellation creates an important ambiguity: cancelling the local HTTP coroutine does not
prove that the remote server did not commit the request. The response may simply not have reached
BulkRelay yet. The CLI therefore warns explicitly that remote side effects may be unknown.

Prefer the first, graceful interrupt unless immediate termination is necessary.

## Summary fields after interruption

A stopped run includes enough information to distinguish source size from completed work:

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

`total` remains the number of records with a final recorded result. `input_total` is the number of
records that passed preflight. `unprocessed` is the difference between them.
