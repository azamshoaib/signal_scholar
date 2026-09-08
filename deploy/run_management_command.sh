#!/bin/sh
# deploy/run_management_command.sh
#
# Usage: deploy/run_management_command.sh <manage.py-subcommand> [args...]
#   e.g. deploy/run_management_command.sh recompute_scores
#
# Wraps a Django management command so it can be run unattended from cron (or
# by hand on a deployed host): it runs `uv run python manage.py "$@"` from
# the repo root, captures the command's combined stdout+stderr into a new
# timestamped file under logs/, and on a non-zero exit appends a grep-able
# `FAILED: <subcommand> exited <code>` line to that log file. The wrapper
# itself exits with the same code the wrapped command exited with, so an
# external scheduler (cron, systemd, etc.) can detect failure.
#
# See _docs/scheduling.md for how this is scheduled and how to check logs
# for failures.

set -eu

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <manage.py-subcommand> [args...]" >&2
    exit 1
fi

subcommand=$1

# Resolve the repo root from this script's own location so the wrapped
# command always runs "from the repo root", regardless of the caller's
# working directory. The log directory, however, is created relative to the
# caller's working directory (see _docs/scheduling.md / tests), so a
# deployment's crontab (which `cd`s into the repo root before invoking this
# script) naturally gets logs/ under the repo root, while tests can isolate
# logs by invoking this script with a different working directory.
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)

log_dir="logs"
mkdir -p "$log_dir"

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
log_file="$log_dir/${subcommand}-${timestamp}.log"

set +e
(cd "$repo_root" && uv run python manage.py "$@") >"$log_file" 2>&1
exit_code=$?
set -e

if [ "$exit_code" -ne 0 ]; then
    echo "FAILED: ${subcommand} exited ${exit_code}" >>"$log_file"
fi

exit "$exit_code"
