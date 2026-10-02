# Checkpoints and safe resume

BulkRelay keeps every run in one durable directory. Milestone 5 adds enough state to continue an
interrupted run without replaying records whose final results were already persisted locally.

## Run directory

```text
.bulkrelay/runs/<run-id>/
├── run.json
├── checkpoint.json
├── results.jsonl
└── summary.json
```

`run.json` is the run manifest. It records only metadata and fingerprints, never a copy of request
headers or other config values.

`results.jsonl` is the append-only result journal and the source of truth for completed rows. Every
record is flushed and fsynced before the compact checkpoint is advanced.

`checkpoint.json` is an atomically replaced operator-friendly snapshot of counters. Resume rebuilds
completed row identities from `results.jsonl` instead of storing an ever-growing row list in the
checkpoint.

`summary.json` is written when a run stops or completes and is replaced after a successful resume.

## Resume

A normal CLI run records the resolved config path. After a graceful interruption:

```bash
uv run bulkrelay resume .bulkrelay/runs/20261002T190000Z-ab12cd34
```

If the config was moved, provide its new location:

```bash
uv run bulkrelay resume .bulkrelay/runs/20261002T190000Z-ab12cd34 \
  --config ./jobs/customers.yaml
```

The input file may also move as long as the config points to the new location and the bytes are
identical. File location is not part of the semantic job fingerprint.

## Fingerprint checks

Before any resumed HTTP request, BulkRelay repeats full preflight and verifies:

- input format;
- input SHA-256;
- input byte size;
- input record count;
- semantic job-config SHA-256.

The semantic job fingerprint covers request mapping, URL, headers, timeout, concurrency, rate-limit,
and retry policy. Only the digest is persisted. Changing any of those settings causes resume to fail
closed.

A mismatch produces an error instead of starting a new partial migration under an old checkpoint.

## Journal validation

Resume reads the existing result journal and refuses to continue if it contains:

- invalid JSON;
- blank journal lines;
- duplicate `row_number` values;
- row numbers outside the current input range;
- malformed result metadata.

Persisted success and failure rows are both considered completed. `resume` continues only records that
have no durable final result. Retrying final failures is a separate workflow and is intentionally not
part of resume semantics.

## Run states

`run.json` uses explicit states:

```text
running
stopped
forced
completed
completed_with_failures
```

`running` is also resumable because it may represent a process or machine crash before finalization.
Completed runs are not resumable. A future retry command can operate on final failed records without
conflating retry with crash recovery.

## What resume guarantees

Resume prevents replay of records whose result was durably appended to `results.jsonl`, and it refuses
to continue against changed input or changed request semantics.

It does **not** provide exactly-once delivery to an arbitrary remote API. If the process crashes or is
force-killed after a remote server commits a side effect but before BulkRelay persists the local
result, that record is ambiguous and can be sent again on resume. The same ambiguity exists after a
network timeout.

For APIs that support idempotency keys, a later milestone can close much of this gap. Until then:

- prefer graceful interruption over force-stop;
- keep retries opt-in for side-effecting POST requests;
- use the target API's native idempotency mechanism when available;
- do not describe BulkRelay as an exactly-once executor.
