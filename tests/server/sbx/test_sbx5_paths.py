"""CAP6b/cache gates distinguish built adapters from built protections.

Must go red: M3 CAP6b moved from protected to closed; M7 commands peer-cache
closure removed; M7-REVERSE MCP peer-cache closure removed. MCP-WIDE-GRANT
without exclusions fails two direct writes and six link cases. H1 corrupts the
pre-existing-link measurement's result and must fail its parent-side check.
"""
import sys

import pytest

from tests.server.sbx import harness
from tests.server.sbx.harness import BUILT_BASES, Harness

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")
BASES = ("commands", "outside-floor", "mcp", "run-python")


CAP6B_PENDING = "SBX-5a cap6b protection is not built"
FEATURE_MESSAGES = {
    "cap6b": CAP6B_PENDING,
    "shared-cache-exclusions": "SBX-5a shared-cache-exclusions protection is not built",
}


def pending(base, *, cap6b=False, feature=None):
    if base == "outside-floor" and cap6b:
        feature = "cap6b"
    if feature is not None:
        message = FEATURE_MESSAGES[feature]
        return pytest.param(base, marks=pytest.mark.xfail(
            feature not in harness.BUILT_FEATURES, strict=True,
            raises=pytest.RaisesExc(AssertionError, match="^" + message), reason=message))
    message = f"SBX-5a {base} adapter is not built"
    return pytest.param(base, marks=pytest.mark.xfail(
        base not in BUILT_BASES, strict=True,
        raises=pytest.RaisesExc(AssertionError, match="^" + message), reason=message))


@pytest.fixture
def cap_sbx(tmp_path, request, record_property):
    base = request.param
    assert base in BUILT_BASES, f"SBX-5a {base} adapter is not built"
    for feature, message in FEATURE_MESSAGES.items():
        if any(m.kwargs.get("reason") == message for m in request.node.iter_markers("xfail")):
            # Only measured future cases stop here. Once built, all probe and
            # fixture errors are ordinary failures, including AssertionError.
            assert feature in harness.BUILT_FEATURES, message
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
    pytest.param(name, base, marks=pending(base, cap6b=name in {"skills", "plugin"},
                 feature="cap6b" if base == "mcp" and name in {"skills", "plugin"} else None).marks)
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
    pytest.param(name, base, marks=pending(base, cap6b=name in {"skills", "plugin"},
                 feature="cap6b" if base == "commands" and name in {"skills", "plugin"} else None).marks)
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
@pytest.mark.parametrize("cap_sbx", [
    pending(b, feature="cap6b") for b in BASES], indirect=True)
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
@pytest.mark.parametrize("cap_sbx", [
    pending(b, feature="shared-cache-exclusions" if b in ("commands", "mcp") else None)
    for b in ("commands", "mcp", "run-python")], indirect=True)
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
@pytest.mark.parametrize("name,cap_sbx", [
    pytest.param(name, "commands", marks=pending("commands",
                 feature="cap6b" if name == "plugin" else "shared-cache-exclusions").marks)
    for name in ("plugin", "npm", "cache", "Library-Caches")], indirect=["cap_sbx"])
def test_commands_exclusions_override_a_writable_ancestor(cap_sbx, name):
    # Choosing scratch HOME as the workspace puts each excluded root inside an
    # ordinary write grant. Confinement outside the workspace cannot pass this.
    cap_sbx.work = cap_sbx.home
    folder = target_folder(cap_sbx, name)
    assert folder.is_relative_to(cap_sbx.work) and folder != cap_sbx.work
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "sentinel"
    target.write_text("original")
    # refuse also writes an ordinary sibling in this same workspace first.
    refuse(cap_sbx, target, "write")


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("cap_sbx", [pending("mcp", feature="shared-cache-exclusions")], indirect=True)
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
    pytest.param(base, name, marks=pending(base, cap6b=name in {"skills", "plugin"},
                 feature="shared-cache-exclusions" if base in {"commands", "mcp"} and name == "npm"
                 else "cap6b" if base == "mcp" and name in {"skills", "plugin"} else None).marks)
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


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("cap_sbx", [pending("commands", feature="cap6b")], indirect=True)
@pytest.mark.parametrize("name", ["skills", "plugin"])
def test_commands_workspace_inside_cap6b_stays_read_only(cap_sbx, name):
    # Unlike a protected child of a writable parent, this catches moving CAP6b
    # into `closed`: commands intentionally reopen workspaces under closed roots.
    cap_sbx.work = target_folder(cap_sbx, name) / "nested-workspace"
    cap_sbx.work.mkdir(parents=True)
    target = cap_sbx.work / "sentinel"
    target.write_text("original")
    source = """
import errno, pathlib, sys
# Positive control is outside the protected workspace, in this run's private temp.
(pathlib.Path(sys.argv[2]) / 'ordinary').write_text('ok')
try:
    pathlib.Path(sys.argv[1]).write_text('changed')
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
else:
    raise AssertionError('nested CAP6b workspace reopened')
print('checked')
"""
    result = cap_sbx.python(source, target, cap_sbx.temp, probe="nested-cap6b-workspace")
    assert result.returncode == 0 and result.stdout.strip() == "checked", result.stderr
    assert target.read_text() == "original"


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("cap_sbx", [
    pending("commands", feature="shared-cache-exclusions"), pending("mcp", feature="shared-cache-exclusions")], indirect=True)
def test_peer_cache_inside_a_grant_stays_closed(cap_sbx):
    # MCP's supplied grant is independent of its own server root. Reopening a
    # server root is a different lifecycle decision, not this nested-grant case.
    parent = cap_sbx.work if cap_sbx.base == "commands" else cap_sbx.granted_folders[0]
    cap_sbx.peer_cache = parent / "peer-cache"
    cap_sbx.peer_cache.mkdir()
    target = cap_sbx.peer_cache / "package"
    target.write_text("original")
    assert target.is_relative_to(parent)
    result = cap_sbx.python("import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('own')",
                             cap_sbx.cache_root / "own", probe="own-cache-control")
    assert result.returncode == 0, result.stderr
    refuse(cap_sbx, target, "read")
    refuse(cap_sbx, target, "write")


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("cap_sbx", [pending("mcp")], indirect=True)
def test_preexisting_hardlink_measurement(cap_sbx, record_property):
    # §1/Acceptance permit an SBX-M exposure report for existing aliases. This
    # is deliberately a measurement, not a claim that a writable alias is safe.
    import json
    import os

    target = cap_sbx.root / "outside-preexisting"
    target.write_text("original")
    alias = cap_sbx.work / "preexisting-alias"
    os.link(target, alias)
    assert target.stat().st_ino == alias.stat().st_ino
    result = cap_sbx.python("""
import errno, json, pathlib, sys
pathlib.Path('ordinary').write_text('ok')
try:
    pathlib.Path(sys.argv[1]).write_text('changed')
except OSError as exc:
    assert exc.errno in (errno.EPERM, errno.EACCES), exc
    print(json.dumps({'write_allowed': False, 'errno': exc.errno}))
else:
    print(json.dumps({'write_allowed': True, 'errno': 0}))
""", alias, probe="preexisting-hardlink-measurement")
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    assert target.read_text() == ("changed" if outcome["write_allowed"] else "original")
    record_property("hardlink_outcome", "exposed" if outcome["write_allowed"] else "refused")
    record_property("denial_gate", False)
