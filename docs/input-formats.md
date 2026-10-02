# Input formats

BulkRelay Milestone 2 supports streaming **CSV** and **JSONL/NDJSON** files.

## CSV

CSV files must be UTF-8 (UTF-8 with BOM is accepted) and must contain one non-empty, unique header
name per column. BulkRelay rejects duplicate or blank headers, rows with extra values, and rows with
fewer values than the declared header.

CSV values are strings. An empty CSV field therefore maps to `""` rather than `null`.

## JSONL / NDJSON

Every physical line must contain exactly one JSON object. Blank lines, malformed JSON, and scalar or
array roots are rejected with the source line number in the diagnostic.

Unlike CSV, JSONL preserves JSON types. Numbers remain numbers, booleans remain booleans, and nested
objects/arrays can be mapped as complete values.

JSONL is allowed to have heterogeneous object shapes, but every record must contain every field used
by the configured request mapping. BulkRelay validates all records before making the first HTTP
request, so late shape drift cannot cause a partially executed migration.
