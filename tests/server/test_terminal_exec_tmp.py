"""zsh here-documents use $TMPPREFIX (default /tmp/zsh), not TMPDIR. In the 0.1.49
bench /tmp was not writable and every `python3 - <<'PY'` save failed with
"can't create temp file for here document". Commands now keep both in the
process temp dir."""
import tempfile

from server.services import terminal_exec


async def test_heredoc_temp_files_stay_in_the_process_temp_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", None)          # re-read TMPDIR
    out = await terminal_exec.run('printf "%s|%s\\n" "$TMPDIR" "$TMPPREFIX"; cat <<EOF\nheredoc ok\nEOF',
                                  cwd=tmp_path)
    first, second = out["stdout"].splitlines()[:2]
    tmpdir, prefix = first.split("|")
    assert out["ok"] and second == "heredoc ok"
    assert tmpdir == str(tmp_path) and prefix == str(tmp_path / "zsh")
