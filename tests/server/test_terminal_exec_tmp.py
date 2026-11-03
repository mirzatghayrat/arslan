"""zsh here-documents use $TMPPREFIX (default /tmp/zsh), not TMPDIR. In the 0.1.49
bench /tmp was not writable and every `python3 - <<'PY'` save failed with
"can't create temp file for here document". Commands keep both in their own temp
folder: since SBX-3 §1a that is the run's (`run_temp`), under the process temp dir."""
import tempfile
from pathlib import Path

from server.services import run_temp, terminal_exec


async def test_heredoc_temp_files_stay_in_the_commands_own_temp_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", None)          # re-read TMPDIR
    out = await terminal_exec.run('printf "%s|%s\\n" "$TMPDIR" "$TMPPREFIX"; cat <<EOF\nheredoc ok\nEOF',
                                  cwd=tmp_path)
    first, second = out["stdout"].splitlines()[:2]
    tmpdir, prefix = first.split("|")
    assert out["ok"] and second == "heredoc ok"
    assert Path(tmpdir).parent == run_temp.root() and run_temp.root().parent == tmp_path.resolve()
    assert prefix == str(Path(tmpdir) / "zsh")
