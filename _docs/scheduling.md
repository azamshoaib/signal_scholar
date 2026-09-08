# Scheduling recurring jobs

SignalScholar has two management commands that need to run on a fixed
schedule once the project is deployed: `recompute_scores` (#14) and
`poll_followed_authors` (#26). They're scheduled via plain cron plus a
thin shell wrapper — no task queue (Celery/Redis) — per the current stack
decision.

## What runs, and why on that schedule

- `recompute_scores` runs daily at `0 3 * * *` (03:00, an off-peak hour).
  Its inputs — for example citation velocity's age-based calculation —
  only meaningfully change once a day, so running it more often would burn
  compute without producing any observable change in scores.
- `poll_followed_authors` runs hourly at `0 * * * *`. It calls the
  external, rate-limited OpenAlex API once per followed author. Hourly is
  a reasonable balance: OpenAlex's rate limits turned out to be more
  permissive than Semantic Scholar's (per the grooming for #8/#9), so
  hourly polling doesn't hammer the API, while still surfacing newly
  published papers without too much delay.

Both jobs are invoked through `deploy/run_management_command.sh`, which
wraps `uv run python manage.py <subcommand>`, captures its combined
stdout/stderr into a timestamped log file, and marks the log with a
`FAILED:` line (and propagates the exit code) if the command fails. See
that script's header comment for the exact contract.

## How to change the schedule

Edit `deploy/crontab`. It's a plain crontab file — the two lines set the
minute/hour/day-of-month/month/day-of-week fields in standard cron syntax,
followed by the command to run. After editing, re-install it on the host
with:

```
crontab deploy/crontab
```

Remember to keep the placeholder path (`/path/to/signal_scholar`) pointed
at that host's actual checkout path, and to double check the hour is still
off-peak for that host's timezone (cron uses the system's configured
timezone, so `0 3 * * *` may not be 03:00 UTC unless the host is set to
UTC).

## Where logs land, and how to check for failures

Each run writes a fresh timestamped log file:

```
logs/<subcommand>-<UTC timestamp>.log   e.g. logs/recompute_scores-20260308T030001Z.log
```

`deploy/crontab` also redirects cron's own stdout/stderr for each line to
`logs/cron.log` (append mode), which mostly catches things going wrong
before the wrapper script itself starts (e.g. `cd` failing because the
placeholder path wasn't updated).

To find every failed run, grep the per-command log files for the `FAILED:`
marker the wrapper appends on non-zero exit:

```
grep FAILED logs/*.log
```

or, to just list the failing log files:

```
grep -l '^FAILED:' logs/*.log
```

## This is deploy-target-agnostic tooling, not something to run locally via cron

`deploy/run_management_command.sh` and `deploy/crontab` assume an
environment where `uv run python manage.py ...` already works against a
real database via environment variables — i.e. a real deployed host, once
#29 has picked one. They are not meant to be installed via actual `cron`
against the local dev `docker compose` setup on a developer's machine.
Actually installing `deploy/crontab` on a real server is tracked
separately as #45, blocked on #29.
