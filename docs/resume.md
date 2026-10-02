# Checkpoints and safe resume

BulkRelay keeps durable state for every run so interrupted jobs can continue without replaying records whose final results were already persisted locally.

## Run directory

```text
.bulkrelay/runs/<run-id>/
├── run.json
├── checkpoint.json
├── results.jsonl
└── summary.json
```

`run.json` is the run manifest. It stores run metadata and fingerprints, not a copy of request headers or the full configuration.

`results.jsonl` is the append-only result journal and the source of truth for completed rows. Each final result is flushed and fsynced before the compact checkpoint advances.

`checkpoint.json` is an atomically replaced snapshot of counters. BulkRelay does not store an ever-growing list of completed row numbers in the checkpoint. On resume, completed row identities are rebuilt from `results.jsonl`.

`summary.json` records the latest run summary and is replaced after a successful resume.

## Resume an interrupted run

A normal run records the resolved configuration path.

Resume with:

```bash
uv run bulkrelay resume .bulkrelay/runs/20261002T190000Z-ab12cd34
```

If the configuration file moved, provide its new location:

```bash
uv run bulkrelay resume .bulkrelay/runs/20261002T190000Z-ab12cd34 \
  --config ./jobs/customers.yaml
```

The input file may also move if the configuration points to the new location and the file bytes are unchanged. The file path itself is not part of the semantic job fingerprint.

## Fingerprint checks

Before a resumed HTTP request is allowed to start, BulkRelay runs preflight again and verifies:

- input format;
- input SHA-256;
- input byte size;
- input record count;
- semantic job-configuration SHA-256.

The semantic job fingerprint covers the parts of the configuration that can change execution behavior, including request mapping, URL, headers, timeout policy, concurrency, rate limit, and retry policy.

Only the digest is stored in run state. If one of those semantics changes, resume fails closed instead of continuing an old run under a new configuration.

## Journal validation

Before rebuilding completed row state, BulkRelay validates the existing result journal.

Resume is refused if the journal contains:

- invalid JSON;
- blank lines;
- duplicate `row_number` values;
- row numbers outside the current input range;
- malformed result metadata.

Both successful and failed final results count as completed records. `resume` schedules only source rows that do not already have a durable final result.

Retrying failed rows from a completed run is a separate workflow. It is intentionally not part of resume semantics.

## Run states

`run.json` uses explicit states:

```text
running
stopped
forced
completed
completed_with_failures
```

A `running` run may be resumed because it can represent a process or machine crash before finalization.

Completed runs are not resumable. This prevents resume from being used as an implicit retry command after a job has already reached a final state.

## What resume guarantees

Resume prevents replay of records whose final result was durably appended to `results.jsonl`.

It also refuses to continue if the input or relevant execution semantics changed since the original run.

Resume does not provide exactly-once delivery to an arbitrary remote API.

There is an unavoidable ambiguous window if the remote server commits a request and the BulkRelay process dies before the final result is persisted locally. The same ambiguity can occur after a network timeout. In either case, a later resume may send that source row again.

Until explicit idempotency-key support is available:

- prefer graceful interruption over force stop;
- keep retries disabled unless the target endpoint's retry semantics are known;
- use the target API's native idempotency mechanism when possible;
- do not treat BulkRelay as an exactly-once executor.
