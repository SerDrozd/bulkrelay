# Security policy

BulkRelay sends user-controlled data to user-configured HTTP endpoints. Job files, input files, and generated run output can contain sensitive information.

## Reporting a vulnerability

Please do not open a public GitHub issue for a security vulnerability.

Use GitHub private vulnerability reporting when it is available for this repository. If private reporting is not available, contact the maintainer at `serhii.drozdov.work@gmail.com`.

Include enough information to reproduce the issue, but do not send real credentials, production records, or unrelated private data.

## Sensitive data

Do not commit:

- API keys or bearer tokens;
- passwords or other credentials;
- production customer exports;
- generated `.bulkrelay/` run directories;
- result journals or summaries containing sensitive response data.

BulkRelay currently accepts literal request headers from YAML configuration. A configuration file containing credentials should be treated as sensitive.

Environment-variable interpolation and automatic secret redaction are not implemented yet. Do not assume that values placed in a job configuration are hidden from every local file or diagnostic path.

## Run output

`results.jsonl` can contain response bodies or error details returned by the target API.

Review generated run data before attaching it to an issue, pull request, support request, or public discussion. The default `.gitignore` excludes `.bulkrelay/`, but ignore rules should not be treated as a security boundary.
