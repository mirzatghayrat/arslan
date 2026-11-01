"""CAP6b/cache gates distinguish built adapters from built protections."""
import sys

import pytest

from tests.server.sbx import harness
from tests.server.sbx.harness import BUILT_BASES, Harness

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")
BASES = ("commands", "outside-floor", "mcp", "run-python")


CAP6B_PENDING = "SBX-5a cap6b protection is not built"


def pending(base, *, cap6b=False):
    if base == "outside-floor" and cap6b:
        return pytest.param(base, marks=pytest.mark.xfail(
            "cap6b" not in harness.BUILT_FEATURES, strict=True,
            raises=pytest.RaisesExc(AssertionError, match="^" + CAP6B_PENDING), reason=CAP6B_PENDING))
    message = f"SBX-5a {base} adapter is not built"
    return pytest.param(base, marks=pytest.mark.xfail(
        base not in BUILT_BASES, strict=True,
        raises=pytest.RaisesExc(AssertionError, match="^" + message), reason=message))


@pytest.fixture
def cap_sbx(tmp_path, request, record_property):
    base = request.param
    assert base in BUILT_BASES, f"SBX-5a {base} adapter is not built"
    if any(m.kwargs.get("reason") == CAP6B_PENDING for m in request.node.iter_markers("xfail")):
        # Only the selected feature cases stop here. Once built, all probe and
        # fixture errors are ordinary failures, including AssertionError.
        assert "cap6b" in harness.BUILT_FEATURES, CAP6B_PENDING
    h = Harness(tmp_path, base)
    # Test inputs, not computed policy: wide grants must not cancel exclusions.
    h.plugin_root = h.home / "user-chosen-plugin-folder"
    h.data_root = h.root / "data"
    h.cache_root = h.root / ("mcp-cache" if base == "mcp" else "commands-cache")
    h.peer_cache = h.root / ("commands-cache" if base == "mcp" else "mcp-cache")
    h.granted_folders = [h.home]
    for folder in (h.plugin_root, h.data_root, h.cache_root, h.peer_cache):
        folder.mkdir(parents=True, exist_ok=True)
    try:
        result = h.python("pass", probe="cap6b-smoke")
        assert result.returncode == 0, result.stderr
        yield h
    finally:
        h.record_executions(record_property, request.config.getoption("--sbx-artifacts"))


def target_folder(h, name):
    return {"skills": h.home / ".agents" / "skills", "plugin": h.plugin_root,
            "data": h.data_root, "npm": h.home / ".npm", "cache": h.home / ".cache",
            "Library-Caches": h.home / "Library" / "Caches"}[name]


def refuse(h, target, action):
    # Scratch sentinels establish access and existence outside the sandbox.
    assert target.read_text() == "original"
    result = h.python("""
import errno, pathlib, sys
pathlib.Path('ordinary').write_text('ok')
p = pathlib.Path(sys.argv[1])
try:
    p.read_text() if sys.argv[2] == 'read' else p.write_text('changed')
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    raise AssertionError('CAP6b/cache boundary opened: ' + sys.argv[2])
print('checked')
""", target, action, probe="cap6b-" + action)
    assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
    assert target.read_text() == "original"


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("name,cap_sbx", [
    pytest.param(name, base, marks=pending(base, cap6b=name in {"skills", "plugin"}).marks)
    for base in BASES for name in ("skills", "plugin", "data")], indirect=["cap_sbx"])
def test_cap6b_write_denied(cap_sbx, name):
    folder = target_folder(cap_sbx, name)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "sentinel"
    target.write_text("original")
    if cap_sbx.base == "outside-floor":
        # CAP6b must not close ordinary credentials in the approved outside run.
        credential = cap_sbx.home / ".ssh" / "scratch-key"
        credential.parent.mkdir(exist_ok=True)
        credential.write_text("scratch")
        result = cap_sbx.python("import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())",
                                 credential, probe="outside-credential-control")
        assert result.returncode == 0 and result.stdout.strip() == "scratch", result.stderr
    refuse(cap_sbx, target, "write")


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("name,cap_sbx", [
    pytest.param(name, base, marks=pending(base, cap6b=name in {"skills", "plugin"}).marks)
    for base in ("commands", "outside-floor", "run-python")
    for name in ("skills", "plugin", "data")], indirect=["cap_sbx"])
def test_cap6b_read_denied(cap_sbx, name):
    folder = target_folder(cap_sbx, name)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "sentinel"
    target.write_text("original")
    refuse(cap_sbx, target, "read")


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("cap_sbx", [pending(b, cap6b=True) for b in BASES], indirect=True)
@pytest.mark.parametrize("through_alias", [False, True], ids=["real-name", "home-link"])
def test_cap6b_symlink_root(cap_sbx, through_alias):
    real = cap_sbx.work / "agent-source"
    (real / "skills").mkdir(parents=True)
    alias = cap_sbx.home / ".agents"
    alias.symlink_to(real, target_is_directory=True)
    target = real / "skills" / "sentinel"
    target.write_text("original")
    refuse(cap_sbx, alias / "skills" / "sentinel" if through_alias else target, "write")


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("cap_sbx", [pending(b) for b in ("commands", "mcp", "run-python")], indirect=True)
@pytest.mark.parametrize("name", ["npm", "cache", "Library-Caches"])
def test_shared_cache_is_not_writable(cap_sbx, name):
    folder = target_folder(cap_sbx, name)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "sentinel"
    target.write_text("original")
    if cap_sbx.base != "run-python":
        result = cap_sbx.python("import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())",
                                 target, probe="shared-cache-read-control")
        assert result.returncode == 0 and result.stdout.strip() == "original", result.stderr
    refuse(cap_sbx, target, "write")


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("cap_sbx", [pending("mcp")], indirect=True)
def test_commands_cache_is_not_visible_to_mcp(cap_sbx):
    assert cap_sbx.peer_cache.resolve() != cap_sbx.cache_root.resolve()
    target = cap_sbx.peer_cache / "package"
    target.write_text("original")
    result = cap_sbx.python("import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('own')",
                             cap_sbx.cache_root / "own", probe="mcp-owned-cache-control")
    assert result.returncode == 0, result.stderr
    refuse(cap_sbx, target, "read")


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("cap_sbx,name", [
    pytest.param(base, name, marks=pending(base, cap6b=name in {"skills", "plugin"}).marks)
    for base in BASES for name in ("skills", "plugin", "data", "npm")
    if not (base == "outside-floor" and name == "npm")], indirect=["cap_sbx"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_links_do_not_open_write_paths(cap_sbx, name, kind):
    folder = target_folder(cap_sbx, name)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "sentinel"
    target.write_text("original")
    if kind == "symlink":
        alias = cap_sbx.work / "alias"
        alias.symlink_to(target)
        refuse(cap_sbx, alias, "write")
        return
    assert target.stat().st_dev == cap_sbx.work.stat().st_dev
    result = cap_sbx.python("""
import errno, os, pathlib, sys
pathlib.Path('local').write_text('ok')
os.link('local', 'local-alias')
assert pathlib.Path('local-alias').read_text() == 'ok'
try:
    os.link(sys.argv[1], 'alias')
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    try:
        pathlib.Path('alias').write_text('changed')
    except OSError as exc:
        assert exc.errno in (errno.EPERM, errno.EACCES), exc
    else:
        raise AssertionError('hard-link write allowed')
print('checked')
""", target, probe="cap6b-hardlink")
    assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
    assert target.read_text() == "original"
