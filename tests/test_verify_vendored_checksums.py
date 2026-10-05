import hashlib
import json

from scripts.verify_vendored_checksums import main, problems


def _crate(vendor, name, files):
    crate = vendor / name
    for rel, body in files.items():
        (crate / rel).parent.mkdir(parents=True, exist_ok=True)
        (crate / rel).write_bytes(body)
    sums = {rel: hashlib.sha256(body).hexdigest() for rel, body in files.items()}
    (crate / ".cargo-checksum.json").write_text(json.dumps({"files": sums, "package": "0" * 64}))
    return crate


def test_a_whole_tree_passes(tmp_path):
    _crate(tmp_path, "memchr", {"src/lib.rs": b"//", ".vim/coc-settings.json": b"{}"})
    _crate(tmp_path, "libc", {"Cargo.toml": b"[package]"})
    assert problems(tmp_path) == []
    assert main(["x", str(tmp_path)]) == 0


def test_a_file_git_dropped_is_named(tmp_path):
    """The measured case: a dot-directory kept out of git by an ignore rule."""
    crate = _crate(tmp_path, "memchr", {"src/lib.rs": b"//", ".vim/coc-settings.json": b"{}"})
    (crate / ".vim/coc-settings.json").unlink()
    assert problems(tmp_path) == ["memchr/.vim/coc-settings.json: missing"]
    assert main(["x", str(tmp_path)]) == 1


def test_a_changed_file_is_named(tmp_path):
    crate = _crate(tmp_path, "memchr", {"src/lib.rs": b"//"})
    (crate / "src/lib.rs").write_bytes(b"// edited\r\n")
    assert problems(tmp_path) == ["memchr/src/lib.rs: checksum differs"]


def test_a_crate_without_checksums_or_an_empty_vendor_fails(tmp_path):
    assert problems(tmp_path) == [f"{tmp_path}: no vendored crates"]
    assert problems(tmp_path / "absent") == [f"{tmp_path / 'absent'}: no vendored crates"]
    (tmp_path / "bare").mkdir()
    assert problems(tmp_path) == ["bare: no .cargo-checksum.json"]
