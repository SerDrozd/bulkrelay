# Contributing

1. Create a focused branch.
2. Run `uv sync --all-groups`.
3. Run `uv run ruff check .`, `uv run mypy`, and `uv run pytest` before opening a PR.
4. Keep changes scoped; reliability features should include failure-path tests.
5. Do not add secrets, credentials, production datasets, or generated `.bulkrelay/` run data.
