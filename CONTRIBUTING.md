# Contributing

Thanks for taking the time to improve BulkRelay.

BulkRelay handles side-effecting HTTP jobs, so changes that affect execution, retries, resume behavior, or run state should be tested against failure cases, not only the happy path.

## Development setup

BulkRelay uses Python 3.12 and `uv`.

```bash
uv sync --all-groups
```

Run the project locally with:

```bash
uv run bulkrelay --help
```

## Quality checks

Before opening a pull request, run:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

All three checks should pass.

## Making changes

Keep changes focused and avoid mixing unrelated refactors with feature work.

For execution or reliability changes, add tests for the relevant failure paths. Examples include:

- timeouts;
- retryable and non-retryable responses;
- `Retry-After`;
- interrupted runs;
- resume safety;
- corrupted run state;
- bounded concurrency.

Do not add real credentials, production datasets, customer data, local `.bulkrelay/` run directories, or generated reports to the repository.

## Pull requests

A good pull request should explain:

- what changed;
- why the change is needed;
- what behavior is intentionally unchanged;
- how the change was tested.

Small, reviewable pull requests are preferred.
