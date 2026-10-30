"""SBX-4 (v0.1.64), the build half for run_python, the artifact checks and MCP (4a), first part: what does not wait
for SBX-2's base.

- `computation_profile` writes its venv lines sorted. With a linked interpreter (a venv) it allows two
  process-exec paths and reads two pyvenv.cfg files. It wrote them in set order, which follows the hash seed,
  so one policy had several texts (found by ③Hands in SBX-1's byte-for-byte check).
- `_SEATBELT_PROFILE`, the legacy allow-default text no product caller reached, is gone (§9). Without a
  profile there is no wrapper, so a caller fails closed.
"""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from server.services import code_sandbox

REPO = Path(__file__).resolve().parents[3]


def test_the_venv_lines_do_not_follow_the_hash_seed(tmp_path):
    for folder in ("py/bin", "py/lib", "venv/bin", "venv/lib", "ws"):
        (tmp_path / folder).mkdir(parents=True)
    (tmp_path / "py/bin/python3").write_text("x")
    (tmp_path / "venv/bin/python").symlink_to(tmp_path / "py/bin/python3")
    code = ("import sys; from pathlib import Path; from server.services import code_sandbox; "
            "sys.stdout.write(code_sandbox.computation_profile(sys.argv[1], Path(sys.argv[2])))")
    texts = {subprocess.run([sys.executable, "-c", code, str(tmp_path / "venv/bin/python"), str(tmp_path / "ws")],
                            cwd=REPO, capture_output=True, text=True, check=True,
                            env={**os.environ, "PYTHONHASHSEED": str(seed)}).stdout for seed in range(12)}
    assert len(texts) == 1
    text = texts.pop()
    for marker in ("(allow process-exec ", "pyvenv.cfg"):
        lines = [line for line in text.splitlines() if marker in line]
        assert len(lines) == 2 and lines == sorted(lines), marker


def test_without_a_profile_there_is_no_wrapper(monkeypatch):
    monkeypatch.setattr(code_sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(code_sandbox, "Path", lambda _path: SimpleNamespace(exists=lambda: True))
    assert code_sandbox._seatbelt_wrapper(None) is None
    profile = "(version 1)\n(deny default)\n"
    assert code_sandbox._seatbelt_wrapper(profile) == ["/usr/bin/sandbox-exec", "-p", profile]
    assert not hasattr(code_sandbox, "_SEATBELT_PROFILE")
