"""ALG-KK-OPS-START-SERVER: start.sh runs the repository's own interpreter.

THE ONE BRANCH WORTH PINNING IS THE ONE BEING ADDED. The script used to invoke
bare `python`, which resolved to /usr/bin/python and failed with "No module
named uvicorn" on a machine where nothing was missing. That message names a
DEPENDENCY when the INTERPRETER is wrong, and it sends a reader to pip install —
which outside the venv makes the symptom vanish and leaves the script wrong.

These tests never bind a port: every case fails before the exec.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
START_SH = REPO / "start.sh"


def _repo_without_venv(tmp_path: Path) -> Path:
    """A copy of start.sh beside a data/ dir and NO venv."""
    shutil.copy(START_SH, tmp_path / "start.sh")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "master.db").write_bytes(b"")
    return tmp_path


def _run(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(cwd / "start.sh")],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )


def test_a_missing_venv_fails_and_names_the_venv(tmp_path):
    """THE DEFECT, stated as the property it broke. The old script fell through
    to whatever `python` meant on the PATH and blamed uvicorn."""
    r = _run(_repo_without_venv(tmp_path))

    assert r.returncode != 0
    out = r.stdout + r.stderr
    assert "venv" in out, "the failure did not name the venv"
    assert "uvicorn" not in out.lower().split("install")[0], \
        "the failure blamed a dependency"


def test_the_message_says_it_is_not_a_missing_dependency(tmp_path):
    """Explicit, because the whole defect was a message that misdirected the
    repair towards pip install."""
    r = _run(_repo_without_venv(tmp_path))
    assert "NOT a missing dependency" in (r.stdout + r.stderr)


def test_it_never_reaches_the_system_python(tmp_path):
    """With no venv the script must stop, not fall back. Asserted by the
    absence of any uvicorn startup banner or bind."""
    r = _run(_repo_without_venv(tmp_path))
    out = r.stdout + r.stderr
    assert "Uvicorn running" not in out
    assert "Application startup" not in out


def test_the_real_script_carries_no_bare_python_invocation():
    """A regression guard on the text itself: the repository's only shell script
    must not call the interpreter by bare name again."""
    body = START_SH.read_text()
    offenders = [
        line.strip() for line in body.splitlines()
        if line.strip().startswith(("python ", "python3 ", "python -", "python3 -"))
    ]
    assert offenders == [], f"start.sh calls a bare interpreter: {offenders}"


def test_the_real_script_still_serves_the_gated_app():
    """ALG-KK-AUTH-GATE puts the single middleware on the PARENT gate app,
    registered before the Mount at /, so serving web.app directly bypasses
    authentication ENTIRELY rather than partially. This is a text check rather
    than an execution test because the stubbed happy path was offered and
    declined as more fixture machinery than a five-line script deserves."""
    body = START_SH.read_text()
    assert "authgate.app:app" in body
    assert "exec \"$PY\" -m uvicorn authgate.app:app" in body
    launched = [l for l in body.splitlines() if "-m uvicorn" in l and not l.strip().startswith("#")]
    assert len(launched) == 1, launched
    assert "web.app:app" not in launched[0]
