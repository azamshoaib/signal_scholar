Commands

- `uv sync` - install dependencies
- `docker compose up -d` - start Postgres; run this first and wait for it
  to be ready before `uv run pytest` or any `manage.py` command that
  touches the database
- `uv run pytest` - the whole suite
- `uv run pytest tests/test_home.py` - one test file

Rules

- Dependencies are added in `pyproject.toml`. Do not add one without
  asking

Documents

- `_docs/process.md` - how work is organized
- `_docs/scheduling.md` - how recurring jobs (recompute_scores,
  poll_followed_authors) are scheduled
