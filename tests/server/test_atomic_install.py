import errno

import pytest

from server.services import atomic_install


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "dangling_symlink"])
def test_existing_target_is_never_replaced(tmp_path, kind):
    source, target = tmp_path / "staged", tmp_path / "target"
    source.mkdir()
    (source / "payload").write_text("synthetic")
    if kind == "directory":
        target.mkdir()
    elif kind == "file":
        target.write_text("keep")
    else:
        target.symlink_to(source if kind == "symlink" else tmp_path / "absent")
    before = target.lstat()
    with pytest.raises(ValueError, match="restore destination appeared"):
        atomic_install.install_directory(source, target)
    assert target.lstat().st_ino == before.st_ino
    assert (source / "payload").read_text() == "synthetic"
    if kind == "file":
        assert target.read_text() == "keep"


def test_new_target_installs_complete_directory(tmp_path):
    source, target = tmp_path / "staged", tmp_path / "target"
    source.mkdir()
    (source / "payload").write_text("synthetic")
    atomic_install.install_directory(source, target)
    assert not source.exists()
    assert (target / "payload").read_text() == "synthetic"


def test_concurrent_installers_have_exactly_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    target = tmp_path / "target"
    barrier = Barrier(8)
    sources = [tmp_path / f"staged-{index}" for index in range(8)]
    for index, source in enumerate(sources):
        source.mkdir()
        (source / "payload").write_text(str(index))

    def install(index):
        barrier.wait(timeout=10)
        try:
            atomic_install.install_directory(sources[index], target)
            return index
        except ValueError as error:
            assert str(error) == "restore destination appeared during validation"
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(install, range(8)))
    winners = [index for index in results if index is not None]
    assert len(winners) == 1
    assert (target / "payload").read_text() == str(winners[0])
    for index, source in enumerate(sources):
        if index == winners[0]:
            assert not source.exists()
        else:
            assert (source / "payload").read_text() == str(index)


@pytest.mark.parametrize("failure", ["platform", "symbol", "filesystem"])
def test_unsupported_install_never_falls_back(tmp_path, monkeypatch, failure):
    source, target = tmp_path / "staged", tmp_path / "target"
    source.mkdir()
    if failure == "platform":
        monkeypatch.setattr(atomic_install.sys, "platform", "unsupported")
    elif failure == "symbol":
        monkeypatch.setattr(atomic_install.ctypes, "CDLL", lambda *a, **kw: object())
    else:
        class Refusal:
            def __call__(self, *args):
                atomic_install.ctypes.set_errno(errno.ENOTSUP)
                return -1

        class Library:
            renamex_np = Refusal()
            renameat2 = Refusal()

        monkeypatch.setattr(atomic_install.ctypes, "CDLL", lambda *a, **kw: Library())
    with pytest.raises(OSError) as error:
        atomic_install.install_directory(source, target)
    assert error.value.errno == errno.ENOTSUP
    assert source.is_dir() and not target.exists()


@pytest.mark.parametrize("platform,symbol,flags", [
    ("darwin", "renamex_np", 4), ("linux", "renameat2", 1),
])
def test_platform_binding_uses_exclusive_flags(tmp_path, monkeypatch, platform, symbol, flags):
    calls = []

    class Capture:
        def __call__(self, *args):
            calls.append(args)
            return 0

    class Library:
        pass

    library = Library()
    function = Capture()
    setattr(library, symbol, function)
    monkeypatch.setattr(atomic_install.sys, "platform", platform)
    monkeypatch.setattr(atomic_install.ctypes, "CDLL", lambda *a, **kw: library)
    source, target = tmp_path / "staged", tmp_path / "target"
    atomic_install.install_directory(source, target)
    import os
    old, new = os.fsencode(source), os.fsencode(target)
    assert calls == ([(old, new, flags)] if platform == "darwin"
                     else [(-100, old, -100, new, flags)])
    assert len(function.argtypes) == len(calls[0])
    assert function.restype is atomic_install.ctypes.c_int
