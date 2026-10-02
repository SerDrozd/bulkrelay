# Configuration

BulkRelay configuration is intentionally strict. Unknown YAML fields are errors rather than ignored
settings, which makes misspelled options visible before a migration begins.

```yaml
version: 1

input:
  file: customers.jsonl

request:
  method: POST
  url: https://api.example.com/customers
  json:
    email:
      from: email
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
  max_attempts: 3
  statuses: [408, 425, 429, 500, 502, 503, 504]
  initial_backoff_seconds: 1
  max_backoff_seconds: 30
  jitter_ratio: 0.2
  respect_retry_after: true
```

Each output field must define exactly one source:

- `from`: copy a value from the input record;
- `value`: use a constant JSON-compatible value.

The request body mapping must not be empty. Input file paths are resolved relative to the config file.

Before execution, BulkRelay performs a complete streaming preflight of the input file and mapping. It
does not send HTTP requests if the file is malformed or if any input record cannot satisfy the
mapping.

Duplicate YAML keys are rejected as syntax errors. BulkRelay also materializes every mapped request
body during preflight and verifies that it can be encoded as standards-compliant JSON, including
rejecting non-finite numeric values and YAML-only values such as unquoted dates.

## Reliability defaults

If `execution` and `retry` are omitted, BulkRelay uses bounded defaults:

- connect timeout: 10 seconds;
- read/write timeout: 30 seconds;
- pool timeout: 5 seconds;
- no rate limit;
- one attempt by default (retries are opt-in);
- retry statuses: `408`, `425`, `429`, `500`, `502`, `503`, `504`;
- exponential backoff starting at 1 second, capped at 30 seconds;
- 20% jitter;
- `Retry-After` respected.

See [`reliability.md`](reliability.md) for exact semantics.
