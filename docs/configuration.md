# Configuration correctness

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
