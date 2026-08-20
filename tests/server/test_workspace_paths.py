"""workspace_paths — the ONLY boundary the file tools have.

Spec 2026-08-20 P1 §0 fact 2: file tools run inside the sidecar process and
never pass through seatbelt, so the kernel is NOT on this path. This pure
module IS the jail; every rule below is load-bearing and must stay
mutation-killable.
"""

import pytest

from server.services.workspace_paths import (
    PathEscape,
    SecretFile,
    is_secret_name,
    resolve_in_workspace,
)


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "notes.md").write_text("hello")
    (root / "sub").mkdir()
    (root / "sub" / "deep.txt").write_text("deep")
    return root.resolve()


def test_plain_relative_path_resolves(ws):
    assert resolve_in_workspace("notes.md", ws) == ws / "notes.md"
    assert resolve_in_workspace("sub/deep.txt", ws) == ws / "sub" / "deep.txt"


def test_dotdot_escape_refused(ws):
    for bad in ("../outside.txt", "sub/../../outside.txt", "../../etc/passwd"):
        with pytest.raises(PathEscape):
            resolve_in_workspace(bad, ws)


def test_absolute_path_outside_refused(ws):
    with pytest.raises(PathEscape):
        resolve_in_workspace("/etc/passwd", ws)


def test_absolute_path_inside_accepted(ws):
    assert resolve_in_workspace(str(ws / "notes.md"), ws) == ws / "notes.md"


def test_symlink_pointing_outside_refused(ws, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("private")
    (ws / "link.txt").symlink_to(outside)
    # The name is inside the workspace; the FILE is not. Realpath decides.
    with pytest.raises(PathEscape):
        resolve_in_workspace("link.txt", ws)


def test_symlinked_dir_escape_refused(ws, tmp_path):
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    (outside_dir / "x.txt").write_text("x")
    (ws / "escape").symlink_to(outside_dir)
    with pytest.raises(PathEscape):
        resolve_in_workspace("escape/x.txt", ws)


def test_sibling_prefix_trap_refused(tmp_path):
    """`/ws-evil` must NOT pass a `/ws` root — the classic startswith bug."""
    root = (tmp_path / "ws").resolve()
    root.mkdir()
    evil = tmp_path / "ws-evil"
    evil.mkdir()
    (evil / "f.txt").write_text("x")
    with pytest.raises(PathEscape):
        resolve_in_workspace(str(evil / "f.txt"), root)


def test_write_to_new_file_judged_by_parent(ws):
    """A file that does not exist yet still resolves — the parent decides."""
    out = resolve_in_workspace("sub/new.txt", ws, for_write=True)
    assert out == ws / "sub" / "new.txt"


def test_write_to_new_file_outside_refused(ws, tmp_path):
    with pytest.raises(PathEscape):
        resolve_in_workspace(str(tmp_path / "new-outside.txt"), ws, for_write=True)


def test_write_through_escaping_symlinked_dir_refused(ws, tmp_path):
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    (ws / "escape").symlink_to(outside_dir)
    with pytest.raises(PathEscape):
        resolve_in_workspace("escape/new.txt", ws, for_write=True)


def test_write_into_missing_parent_refused(ws):
    """A parent that does not exist cannot be proven inside — refuse rather
    than create a path whose realpath is unknowable."""
    with pytest.raises(PathEscape):
        resolve_in_workspace("nope/deeper/new.txt", ws, for_write=True)


def test_empty_path_refused(ws):
    for bad in ("", "   ", None):
        with pytest.raises(PathEscape):
            resolve_in_workspace(bad, ws)


def test_no_workspace_root_refused():
    with pytest.raises(PathEscape):
        resolve_in_workspace("notes.md", None)


# ── secret-name guard (spec §2.6) ──────────────────────────────────────────
def test_secret_names_recognised():
    for name in (".env", ".env.local", ".env.production", "server.key", "cert.pem",
                 "id_rsa", "id_ed25519", "keystore.p12", "bundle.pfx"):
        assert is_secret_name(name) is True, name


def test_ordinary_names_not_secret():
    for name in ("notes.md", "environment.md", "monkey.txt", "keyboard.json",
                 "README.md", "identity.ts"):
        assert is_secret_name(name) is False, name


def test_resolve_refuses_secret_on_read(ws):
    (ws / ".env").write_text("SECRET=1")
    with pytest.raises(SecretFile):
        resolve_in_workspace(".env", ws)


def test_secret_refusal_is_distinct_from_escape(ws):
    """The two refusals mean different things to the user — an escape is a
    mistake, a secret is a policy. They must not collapse into one message."""
    (ws / "id_rsa").write_text("k")
    with pytest.raises(SecretFile):
        resolve_in_workspace("id_rsa", ws)
    with pytest.raises(PathEscape):
        resolve_in_workspace("../x", ws)
