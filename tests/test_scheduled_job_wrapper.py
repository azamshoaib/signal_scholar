"""Tests for deploy/run_management_command.sh.

Per GitHub issue #28: invokes the wrapper script as a real subprocess (no
mocking of the script itself, no Django test client). Each test runs the
wrapper with its cwd set to a pytest `tmp_path`, so the `logs/` directory
the wrapper creates lands under that temp directory instead of the repo's
real `logs/` directory.

The success case runs `check`, Django's built-in system-check subcommand,
which exits 0 and touches no database -- confirmed by running it with an
unreachable POSTGRES_HOST/POSTGRES_PORT and seeing it still exit 0. That
means this test file needs no `docker compose up -d` first.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "deploy" / "run_management_command.sh"


def test_wrapper_succeeds_and_logs_cleanly_for_check(tmp_path):
    result = subprocess.run(
        [str(WRAPPER), "check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    log_files = list((tmp_path / "logs").glob("check-*.log"))
    assert len(log_files) == 1, f"expected exactly one log file, got {log_files}"

    log_content = log_files[0].read_text()
    assert "FAILED:" not in log_content


def test_wrapper_fails_and_logs_failure_for_nonexistent_subcommand(tmp_path):
    result = subprocess.run(
        [str(WRAPPER), "this_command_does_not_exist"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0

    log_files = list(
        (tmp_path / "logs").glob("this_command_does_not_exist-*.log")
    )
    assert len(log_files) == 1, f"expected exactly one log file, got {log_files}"
    log_file = log_files[0]

    log_content = log_file.read_text()
    assert re.search(
        r"^FAILED: this_command_does_not_exist exited \d+$",
        log_content,
        re.MULTILINE,
    ), log_content

    # Per the issue: the literal check the tooling relies on is grep-able,
    # not just a Python substring match.
    grep_result = subprocess.run(["grep", "-q", "^FAILED:", str(log_file)])
    assert grep_result.returncode == 0
