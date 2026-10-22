"""Here-documents are written under TMPDIR, inside the process temp dir. In the 0.1.49 bench /tmp was not
writable and every `python3 - <<'PY'` save failed with "can't create temp file for here document" (zsh
used $TMPPREFIX; since S2a-3 the shell is bash, which uses TMPDIR)."""
import tempfile

from server.services import terminal_exec


async def test_heredoc_temp_files_stay_in_the_process_temp_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", None)          # re-read TMPDIR
    out = await terminal_exec.run('printf "%s\\n" "$TMPDIR"; cat <<EOF\nheredoc ok\nEOF', cwd=tmp_path)
    first, second = out["stdout"].splitlines()[:2]
    assert out["ok"] and second == "heredoc ok"
    assert first == str(tmp_path)
