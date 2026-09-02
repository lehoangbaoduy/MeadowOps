"""Unit 12 (MEADOWOPS-INFRA-004): local CI-equivalent script (PRD line 471,
"Unit test suite scaffolded and running in CI (or a local equivalent)").

Run explicitly, like the sibling tests/frontend/ (not swept into the backend
suite's testpaths, and not one of ci.sh's own steps - it edits ci.sh itself):
    backend/.venv/bin/pytest tests/test_ci_script.py -q

The behavioral test sabotages a throwaway, gitignored copy of the script
(never the tracked original), runs it, and deletes the copy - the same
sabotage-and-restore method used at Unit 10 to prove a fix has real teeth,
applied here to prove the script's failure-propagation actually works rather
than assuming `set -e` does what it's supposed to.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_SCRIPT = REPO_ROOT / "scripts" / "ci.sh"


def test_ci_script_exists():
    assert CI_SCRIPT.is_file()


def test_ci_script_is_executable():
    mode = CI_SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR


def test_ci_script_uses_strict_mode():
    text = CI_SCRIPT.read_text()
    assert "set -euo pipefail" in text


def test_ci_script_sources_env_before_the_backend_suite():
    text = CI_SCRIPT.read_text()
    assert "source ../.env" in text


def test_ci_script_never_pipes_a_gated_command_through_a_swallowing_filter():
    # `cmd | tail` (or `| head`) reports the filter's exit code, not cmd's -
    # under `set -e` alone (no `pipefail`) that would let a failing pytest or
    # build silently report success. The script has `pipefail` too, but this
    # guards against the pattern being reintroduced at all.
    text = CI_SCRIPT.read_text()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "| tail" not in stripped
        assert "| head" not in stripped


def test_ci_script_exits_non_zero_and_stops_early_when_the_first_check_fails():
    # Sabotage a throwaway copy, never the real checked-in ci.sh - a copy
    # placed alongside it (not e.g. under tmp_path) so its own ROOT_DIR
    # self-location logic still resolves to the real repo. This means even a
    # hard kill mid-test leaves only an orphaned untracked file, never a
    # mutated tracked script.
    original = CI_SCRIPT.read_text()
    sabotaged = original.replace(
        ".venv/bin/pytest )", ".venv/bin/pytest && false )", 1
    )
    assert sabotaged != original, "sabotage target line not found in ci.sh"
    sabotage_path = CI_SCRIPT.parent / "_ci_sabotage_test.sh"
    sabotage_path.write_text(sabotaged)
    sabotage_path.chmod(0o755)
    try:
        result = subprocess.run(
            ["bash", str(sabotage_path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        sabotage_path.unlink(missing_ok=True)
    assert result.returncode != 0
    assert "all blocking checks passed" not in result.stdout
