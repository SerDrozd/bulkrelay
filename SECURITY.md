# Security

BulkRelay sends user-controlled data to user-configured HTTP endpoints. Do not commit API keys,
tokens, credentials, production exports, or generated run reports.

For the current milestone, authentication helpers and secret interpolation are intentionally not
implemented. When they are added, secrets will be read from environment/config boundaries and
redacted from logs and reports.

Please report security issues privately to the repository owner rather than opening a public issue.
