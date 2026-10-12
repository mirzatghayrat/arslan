"""0.1.61 §C2: a skill's folder is copied whole and safely — regular files only, every path
inside the folder, size caps, the executable bit, staged then swapped, replaced folders to the
Trash. The archive is untrusted: its shapes are pinned at the end of the file (0.1.61 review)."""
from __future__ import annotations

import errno
import gzip
import io
import json
import os
import stat
import tarfile
import unicodedata
import zlib

import pytest

from server.services import skill_files
from tests.server.skill_archives import COMMIT, case_insensitive, tarball


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "data"))
    trashed = []
    monkeypatch.setattr(skill_files, "_trash", lambda path: trashed.append(path) or path.rename(
        tmp_path / f"trashed-{len(trashed)}"))
    return trashed


def _everything(path: str) -> bool:
    return True


def _staging_left() -> list[str]:
    root = skill_files.skills_root()
    return [p.name for p in root.iterdir() if p.name.startswith(".staging-")] if root.exists() else []


def test_read_archive_names_the_commit_and_keeps_only_what_was_asked():
    archive = skill_files.read_archive(tarball({"skills/a/SKILL.md": "---\nname: a\n---\nx",
                                                "skills/a/big.bin": b"\0" * 10, "README.md": "r"}),
                                       keep=lambda p: p.startswith("skills/a/"))
    assert archive.commit == COMMIT
    assert archive.text("skills/a/SKILL.md").startswith("---")
    assert archive.entries["README.md"].data is None            # listed, not read
    assert archive.skill_mds() == ["skills/a/SKILL.md"]
    assert archive.skill_mds("skills/b") == []


def test_read_archive_refuses_what_is_not_an_archive_or_too_big(monkeypatch):
    with pytest.raises(skill_files.BadArchive):
        skill_files.read_archive(b"not a tarball", keep=_everything)
    monkeypatch.setattr(skill_files, "MAX_UNPACKED_BYTES", 5)
    with pytest.raises(skill_files.BadArchive, match="unpacks"):
        skill_files.read_archive(tarball({"a.txt": "0123456789"}), keep=_everything)


def test_links_devices_and_escaping_paths_are_skipped_and_named(data):
    archive = skill_files.read_archive(tarball({
        "s/SKILL.md": "body", "s/scripts/run.py": ("exec", "print(1)"),
        "s/evil": ("link", "/Users/someone/.ssh/id_rsa"), "s/hard": ("hardlink", "s/SKILL.md"),
        "s/pipe": ("fifo",), "s/../outside.txt": "no", "s/a\\b.txt": "no"}), keep=_everything)
    staged = skill_files.stage(archive, "s")
    assert set(staged.files) == {"SKILL.md", "scripts/run.py"}
    assert {"evil", "hard", "pipe", "../outside.txt", "a\\b.txt"} <= set(staged.skipped)
    assert not (staged.path / "evil").exists() and not (staged.path.parent / "outside.txt").exists()
    skill_files.discard(staged)


def test_the_executable_bit_is_kept_and_nothing_else_of_the_mode(data):
    archive = skill_files.read_archive(tarball({"s/run.sh": ("exec", "#!/bin/sh\necho hi\n"),
                                                "s/notes.md": "n", "s/suid": ("mode", 0o4755, "x")}),
                                       keep=_everything)
    staged = skill_files.stage(archive, "s")
    modes = {name: stat.S_IMODE(os.stat(staged.path / name).st_mode) for name in ("run.sh", "notes.md", "suid")}
    assert modes == {"run.sh": 0o755, "notes.md": 0o644, "suid": 0o755}
    skill_files.discard(staged)


def test_two_names_that_differ_only_by_case_keep_the_first(data, tmp_path):
    archive = skill_files.read_archive(tarball({"s/README.md": "first", "s/readme.md": "second"}),
                                       keep=_everything)
    staged = skill_files.stage(archive, "s")
    assert (staged.path / "README.md").read_text() == "first"
    if case_insensitive(staged.path):
        assert "readme.md" in staged.skipped and "readme.md" not in staged.files
    else:
        assert {"README.md", "readme.md"} <= set(staged.files)
    skill_files.discard(staged)


def test_over_the_caps_nothing_is_copied(data, monkeypatch):
    archive = skill_files.read_archive(tarball({f"s/f{i}.txt": "x" for i in range(4)}), keep=_everything)
    monkeypatch.setattr(skill_files, "MAX_FOLDER_FILES", 3)
    with pytest.raises(skill_files.FolderTooLarge):
        skill_files.stage(archive, "s")
    monkeypatch.setattr(skill_files, "MAX_FOLDER_FILES", 2000)
    monkeypatch.setattr(skill_files, "MAX_FOLDER_BYTES", 3)
    with pytest.raises(skill_files.FolderTooLarge):
        skill_files.stage(archive, "s")
    assert _staging_left() == []


def _staged_with(text):
    return skill_files.stage(skill_files.read_archive(tarball({"s/SKILL.md": text}), keep=_everything), "s")


def _leftovers() -> list[str]:
    return sorted(p.name for p in skill_files.skills_root().iterdir() if p.name.startswith("."))


def test_swap_in_replaces_and_swap_back_restores(data):
    assert skill_files.swap_in(_staged_with("one"), "handoff") is None
    aside = skill_files.swap_in(_staged_with("two"), "handoff")
    assert (skill_files.folder_for("handoff") / "SKILL.md").read_text() == "two"
    assert aside is not None and aside.name.startswith(".old-handoff-") and (aside / "SKILL.md").read_text() == "one"
    skill_files.swap_back("handoff", aside)                   # the database write failed
    assert (skill_files.folder_for("handoff") / "SKILL.md").read_text() == "one"
    assert data == [] and _leftovers() == []                  # the new copy was Arslan's own: deleted
    skill_files.retire(None)
    assert data == []


def test_swap_back_never_needs_the_trash(data, monkeypatch):
    skill_files.swap_in(_staged_with("one"), "handoff")
    aside = skill_files.swap_in(_staged_with("two"), "handoff")

    def unreachable(path):
        raise PermissionError("the Trash cannot be reached")
    monkeypatch.setattr(skill_files, "_trash", unreachable)
    skill_files.swap_back("handoff", aside)
    assert (skill_files.folder_for("handoff") / "SKILL.md").read_text() == "one" and _leftovers() == []


def test_a_trash_that_cannot_be_reached_leaves_the_folder(data, monkeypatch, tmp_path):
    folder = tmp_path / "data" / "skills" / ".old-handoff-1a2b3c4d"
    folder.mkdir(parents=True)

    def unreachable(path):
        raise PermissionError("the Trash cannot be reached")
    monkeypatch.setattr(skill_files, "_trash", unreachable)
    skill_files.retire(folder)                                # logged, never raised
    assert folder.is_dir()


def test_the_trash_shows_a_visible_name(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    folder = tmp_path / ".old-handoff-1a2b3c4d"
    folder.mkdir()
    skill_files._trash(folder)
    assert (tmp_path / "home" / ".Trash" / "Arslan capability skill handoff (replaced)").is_dir()


def test_a_file_where_a_folder_is_needed_is_skipped(data):
    archive = skill_files.read_archive(tarball({"s/a": "x", "s/a/b/c.md": "y", "s/SKILL.md": "m"}), keep=_everything)
    staged = skill_files.stage(archive, "s")
    assert set(staged.files) == {"SKILL.md", "a"} and "a/b/c.md" in staged.skipped
    skill_files.discard(staged)


def test_folder_for_refuses_what_is_not_a_key(data):
    for bad in ("", "../x", ".staging-1", "Has Caps", "a/b"):
        with pytest.raises(ValueError):
            skill_files.folder_for(bad)


def test_listing_checksums_scripts_and_reading_stay_inside_the_folder(data, tmp_path):
    folder = tmp_path / "skill"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text("body")
    (folder / "scripts" / "run.py").write_text("print(1)")
    (folder / ".DS_Store").write_text("x")
    (tmp_path / "secret").mkdir()
    (tmp_path / "secret" / "id.txt").write_text("hush")
    (folder / "out").symlink_to(tmp_path / "secret")      # a link that leads out of the folder
    shown, total = skill_files.list_files(folder)
    assert shown == ["SKILL.md", "scripts/run.py"] and total == 2
    assert set(skill_files.checksums(folder)) == {"SKILL.md", "scripts/run.py"}
    assert skill_files.has_scripts(folder) and not skill_files.has_scripts(tmp_path / "none")
    assert skill_files.read_text(folder, "scripts/run.py", limit=100) == "print(1)"
    for escape in ("../skill/SKILL.md", "/etc/hosts", "out/id.txt", ""):
        assert skill_files.read_text(folder, escape, limit=100) is None, escape


def test_placeholders_become_the_folder(tmp_path):
    body = "python3 ${CLAUDE_SKILL_DIR}/a.py; ${SKILL_DIR}/b; {baseDir}/c"
    folder = tmp_path / "App Support" / "k"
    assert skill_files.substitute(body, folder) == f"python3 {folder}/a.py; {folder}/b; {folder}/c"


def test_stage_texts_writes_skill_md_and_makes_a_shebang_script_executable(data):
    staged = skill_files.stage_texts({"scripts/run.sh": "#!/bin/sh\necho hi\n", "notes.md": "n"},
                                     skill_md="---\nname: x\ndescription: d\n---\nbody")
    assert set(staged.files) == {"SKILL.md", "scripts/run.sh", "notes.md"}
    assert stat.S_IMODE(os.stat(staged.path / "scripts" / "run.sh").st_mode) == 0o755
    skill_files.discard(staged)
    with pytest.raises(ValueError):
        skill_files.stage_texts({"../x.sh": "no"}, skill_md="b")
    assert _staging_left() == []


def test_stage_tree_copies_regular_files_and_skips_links(data, tmp_path):
    src = tmp_path / "seed"
    (src / "scripts").mkdir(parents=True)
    (src / "SKILL.md").write_text("b")
    (src / "scripts" / "cli.py").write_text("print(1)")
    os.chmod(src / "scripts" / "cli.py", 0o755)
    (src / "scripts" / "link").symlink_to(src / "SKILL.md")
    staged = skill_files.stage_tree(src)
    assert set(staged.files) == {"SKILL.md", "scripts/cli.py"} and "scripts/link" in staged.skipped
    assert stat.S_IMODE(os.stat(staged.path / "scripts" / "cli.py").st_mode) == 0o755
    skill_files.discard(staged)


def test_changes_count_files_and_show_the_skill_md_diff():
    out = skill_files.changes({"SKILL.md": "a", "old.py": "o", "same.md": "s"},
                              {"SKILL.md": "b", "new.py": "n", "same.md": "s"}, "line one\n", "line two\n")
    assert (out["added"], out["removed"], out["changed"], out["files_changed"]) == (
        ["new.py"], ["old.py"], ["SKILL.md"], 3)
    assert "-line one" in out["skill_md_diff"] and "+line two" in out["skill_md_diff"]


# ── the archive is untrusted (0.1.61 review) ──────────────────────────────────

TOP = "example-org-example-skills-0123456"                 # tarball()'s top folder
GZIP_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"


def _member(name: str, payload: bytes | None = None, **attrs):
    info = tarfile.TarInfo(name)
    for key, value in attrs.items():
        setattr(info, key, value)
    if payload is not None:
        info.size = len(payload)
    return info, payload


def _raw(*members, fmt=tarfile.PAX_FORMAT) -> bytes:
    """A tar.gz of exactly these members: the shapes `tarball` cannot make."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=fmt) as tar:
        for info, payload in members:
            tar.addfile(info, io.BytesIO(payload) if payload is not None else None)
    return buf.getvalue()


def _gzip(raw: bytes, *, crc_of: bytes | None = None, broken_at: int | None = None) -> bytes:
    """`raw` deflated by hand: the trailer computed over `crc_of`, or the stream made invalid (a
    reserved block type) once `broken_at` bytes of `raw` are out. Built, not sampled, so it does
    not depend on which zlib compressed it."""
    deflate = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    if broken_at is not None:
        return GZIP_HEADER + deflate.compress(raw[:broken_at]) + deflate.flush(zlib.Z_FULL_FLUSH) + b"\x07\0"
    ref = raw if crc_of is None else crc_of
    return (GZIP_HEADER + deflate.compress(raw) + deflate.flush()
            + zlib.crc32(ref).to_bytes(4, "little") + (len(ref) % 2**32).to_bytes(4, "little"))


def _cut_at_the_end_marker(raw: bytes) -> bytes:
    """`raw` up to its end-of-archive block: nothing follows the members for the final read of the
    stream to count, so only the count kept while the members are read can refuse it."""
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        tar.getmembers()
        return raw[:tar.offset + 512]


# Shapes the copy already refuses or reads right: pinned.

def test_long_names_in_pax_headers_are_read(data):
    long_dir = "d" * 150
    staged = skill_files.stage(skill_files.read_archive(
        tarball({"s/SKILL.md": "m", f"s/{long_dir}/f.txt": "x"}), keep=_everything), "s")
    assert f"{long_dir}/f.txt" in staged.files
    skill_files.discard(staged)


def test_long_names_in_gnu_headers_are_read(data):
    long_dir = "g" * 150
    archive = skill_files.read_archive(_raw(_member(f"{TOP}/s/SKILL.md", b"m"),
                                            _member(f"{TOP}/s/{long_dir}/f.txt", b"x"),
                                            fmt=tarfile.GNU_FORMAT), keep=_everything)
    staged = skill_files.stage(archive, "s")
    assert f"{long_dir}/f.txt" in staged.files
    skill_files.discard(staged)


def test_a_nul_inside_a_pax_path_is_skipped_and_named(data):
    name = f"{TOP}/s/" + "n" * 120 + "\x00evil/x.txt"            # over 100 bytes: a pax path record
    archive = skill_files.read_archive(_raw(_member(f"{TOP}/s/SKILL.md", b"m"), _member(name, b"x")),
                                       keep=_everything)
    staged = skill_files.stage(archive, "s")
    assert set(staged.files) == {"SKILL.md"} and any("\x00" in p for p in staged.skipped)
    skill_files.discard(staged)


@pytest.mark.parametrize("rel", ["./../x.txt", "a/./../../x.txt", "/../x.txt", "a/b/../../../x.txt",
                                 "a//../../x.txt", "/etc/x.txt"])
def test_dot_dot_and_absolute_paths_after_normalising_are_skipped(data, tmp_path, rel):
    staged = skill_files.stage(skill_files.read_archive(
        tarball({"s/SKILL.md": "m", f"s/{rel}": "no"}), keep=_everything), "s")
    assert set(staged.files) == {"SKILL.md"} and rel in staged.skipped
    assert list(tmp_path.rglob("x.txt")) == []
    skill_files.discard(staged)


def test_a_file_under_a_link_name_lands_in_a_real_folder(data, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    archive = skill_files.read_archive(_raw(
        _member(f"{TOP}/s/SKILL.md", b"m"),
        _member(f"{TOP}/s/lib", type=tarfile.SYMTYPE, linkname=str(elsewhere)),
        _member(f"{TOP}/s/lib/x.txt", b"x")), keep=_everything)
    staged = skill_files.stage(archive, "s")
    assert "lib/x.txt" in staged.files and "lib" in staged.skipped
    assert not (staged.path / "lib").is_symlink() and list(elsewhere.iterdir()) == []
    skill_files.discard(staged)


def test_hard_links_devices_and_unknown_types_are_skipped_and_named(data):
    archive = skill_files.read_archive(_raw(
        _member(f"{TOP}/s/SKILL.md", b"m"),
        _member(f"{TOP}/s/h", type=tarfile.LNKTYPE, linkname="../../../etc/passwd"),
        _member(f"{TOP}/s/c", type=tarfile.CHRTYPE, devmajor=1, devminor=3),
        _member(f"{TOP}/s/b", type=tarfile.BLKTYPE),
        _member(f"{TOP}/s/z", type=b"Z")), keep=_everything)
    staged = skill_files.stage(archive, "s")
    assert set(staged.files) == {"SKILL.md"} and {"h", "c", "b", "z"} <= set(staged.skipped)
    skill_files.discard(staged)


def test_two_names_that_differ_only_by_normalisation_keep_the_first(data):
    nfc, nfd = unicodedata.normalize("NFC", "café.md"), unicodedata.normalize("NFD", "café.md")
    staged = skill_files.stage(skill_files.read_archive(
        tarball({"s/SKILL.md": "m", f"s/{nfc}": "composed", f"s/{nfd}": "decomposed"}),
        keep=_everything), "s")
    first = min(nfc, nfd)                                     # a Mac's disk holds one of the two
    assert (staged.path / first).read_text() == ("composed" if first == nfc else "decomposed")
    skill_files.discard(staged)


# Hardening: what a broken or hostile archive must not get past.

def test_a_corrupted_download_is_refused(data):
    raw = gzip.decompress(tarball({"s/SKILL.md": "the real text"}))
    forged = raw.replace(b"the real text", b"the evil text")
    assert skill_files.read_archive(_gzip(raw), keep=_everything).text("s/SKILL.md") == "the real text"
    with pytest.raises(skill_files.BadArchive):             # a valid stream; its CRC-32 is the real one's
        skill_files.read_archive(_gzip(forged, crc_of=raw), keep=_everything)


@pytest.mark.parametrize("keep", [_everything, lambda path: False], ids=["read", "skipped"])
def test_a_broken_deflate_stream_is_a_bad_archive(data, keep):
    raw = gzip.decompress(tarball({"s/SKILL.md": "m", "s/ref.md": "r" * 300_000, "s/z.md": "end"}))
    broken = _gzip(raw, broken_at=raw.index(b"r" * 1000) + 200_000)       # inside ref.md's data
    with pytest.raises(skill_files.BadArchive):
        skill_files.read_archive(broken, keep=keep)


def test_the_unpacked_cap_counts_headers_too(data, monkeypatch):
    monkeypatch.setattr(skill_files, "MAX_UNPACKED_BYTES", 256 * 1024)
    empty = gzip.decompress(tarball({f"s/f{i:05}.txt": "" for i in range(2000)}))   # 1 MB of headers
    with pytest.raises(skill_files.BadArchive, match="unpacks"):
        skill_files.read_archive(_gzip(_cut_at_the_end_marker(empty)), keep=lambda path: False)


def test_a_member_of_an_unknown_type_counts_toward_the_cap(data, monkeypatch):
    monkeypatch.setattr(skill_files, "MAX_UNPACKED_BYTES", 256 * 1024)
    odd = _member(f"{TOP}/s/z", b"\0" * (1024 * 1024), type=b"Z")      # tarfile inflates it to skip it
    raw = _cut_at_the_end_marker(gzip.decompress(_raw(odd)))
    with pytest.raises(skill_files.BadArchive, match="unpacks"):
        skill_files.read_archive(_gzip(raw), keep=_everything)


def test_what_follows_the_last_member_counts_toward_the_cap(data, monkeypatch):
    monkeypatch.setattr(skill_files, "MAX_UNPACKED_BYTES", 256 * 1024)
    raw = gzip.decompress(tarball({"s/SKILL.md": "m"}))
    with pytest.raises(skill_files.BadArchive, match="unpacks"):
        skill_files.read_archive(_gzip(raw + b"\0" * (1024 * 1024)), keep=_everything)


def test_too_many_entries_is_a_bad_archive(data, monkeypatch):
    monkeypatch.setattr(skill_files, "MAX_ENTRIES", 50)
    with pytest.raises(skill_files.BadArchive, match="entries"):
        skill_files.read_archive(tarball({f"s/f{i}.txt": "" for i in range(60)}), keep=_everything)


@pytest.mark.parametrize("kind", [tarfile.XHDTYPE, tarfile.GNUTYPE_LONGNAME], ids=["pax", "gnu"])
def test_a_chain_of_extended_headers_is_a_bad_archive(data, kind):
    """tarfile reads a pax or GNU long-name header by recursing into the header after it."""
    record = b"13 comment=y\n" if kind == tarfile.XHDTYPE else b"long-name.txt\0"
    head = tarfile.TarInfo("././@LongLink")
    head.type, head.size = kind, len(record)
    one = head.tobuf(tarfile.USTAR_FORMAT) + record.ljust(512, b"\0")
    with pytest.raises(skill_files.BadArchive):
        skill_files.read_archive(_gzip(one * 1100 + gzip.decompress(tarball({"s/a.txt": "x"}))),
                                 keep=_everything)


def test_a_name_that_was_not_utf8_is_skipped_not_fatal(data):
    """git allows any bytes but NUL and "/" in a name; tarfile decodes them with surrogateescape."""
    assert skill_files.safe_relpath("bad\udcff.txt") is None
    staged = skill_files.stage(skill_files.read_archive(
        tarball({"s/SKILL.md": "m", "s/bad\udcff.txt": "x"}), keep=_everything), "s")
    assert set(staged.files) == {"SKILL.md"} and staged.skipped == ["bad\\udcff.txt"]
    skill_files.discard(staged)


def test_read_text_refuses_a_name_that_was_not_utf8(tmp_path):
    assert skill_files.read_text(tmp_path, "x\udcff.md", limit=10) is None


def test_skipped_names_can_be_sent_as_json(data):
    staged = skill_files.stage(skill_files.read_archive(
        tarball({"s/SKILL.md": "m", "s/l\udcff": ("link", "x")}), keep=_everything), "s")
    skill_files.discard(staged)
    assert staged.skipped == ["l\\udcff"]
    json.dumps(staged.skipped, ensure_ascii=False).encode("utf-8")        # what the API sends


def test_skill_mds_lists_only_folders_a_copy_can_take(data):
    archive = skill_files.read_archive(tarball({"ok/SKILL.md": "m", "bad\udcff/SKILL.md": "m",
                                                "a\\b/SKILL.md": "m"}), keep=_everything)
    assert archive.skill_mds() == ["ok/SKILL.md"]


def test_a_path_too_long_for_the_disk_is_skipped_and_named(data):
    deep = "/".join(["p" * 200] * 23) + "/f.txt"             # every part fits; the whole path does not
    staged = skill_files.stage(skill_files.read_archive(
        tarball({"s/SKILL.md": "m", f"s/{deep}": "x"}), keep=_everything), "s")
    assert set(staged.files) == {"SKILL.md"} and deep in staged.skipped
    skill_files.discard(staged)


def test_a_name_the_disk_refuses_is_skipped_and_other_errors_still_fail(data, monkeypatch):
    real = skill_files._write

    def disk(code):
        def write(staging, rel, payload, executable):
            if rel == "odd.md":
                raise OSError(code, os.strerror(code), rel)
            return real(staging, rel, payload, executable)
        return write
    archive = skill_files.read_archive(tarball({"s/SKILL.md": "m", "s/odd.md": "x"}), keep=_everything)
    monkeypatch.setattr(skill_files, "_write", disk(errno.EILSEQ))       # not a name the disk takes
    staged = skill_files.stage(archive, "s")
    assert set(staged.files) == {"SKILL.md"} and "odd.md" in staged.skipped
    skill_files.discard(staged)
    monkeypatch.setattr(skill_files, "_write", disk(errno.ENOSPC))       # a full disk is not a name
    with pytest.raises(OSError):
        skill_files.stage(archive, "s")
    assert _staging_left() == []


def test_the_files_staged_are_named_as_on_disk(data):
    """Importing the very same commit again changes nothing: on a Mac's disk a folder named in
    another case is the first one, and a committed __pycache__ is never copied."""
    archive = skill_files.read_archive(tarball({"s/SKILL.md": "m", "s/Docs/a.md": "a", "s/docs/b.md": "b",
                                                "s/__pycache__/m.pyc": b"\0"}), keep=_everything)
    skill_files.swap_in(skill_files.stage(archive, "s"), "same")
    again = skill_files.stage(archive, "s")
    skill_files.discard(again)
    out = skill_files.changes(skill_files.checksums(skill_files.folder_for("same")), again.files, "m", "m")
    assert out["files_changed"] == 0, out
    assert "__pycache__/m.pyc" in again.skipped
    assert not (skill_files.folder_for("same") / "__pycache__").exists()
    if case_insensitive(skill_files.skills_root()):
        assert "Docs/b.md" in again.files and "docs/b.md" not in again.files


def test_stage_texts_says_which_name_clashes(data):
    root = skill_files.skills_root()
    root.mkdir(parents=True, exist_ok=True)
    drafts = [{"scripts": "x", "scripts/run.sh": "#!/bin/sh\n"}, {"a": "x", "a/b/c.md": "y"}]
    if case_insensitive(root):
        drafts.append({"Notes.md": "a", "notes.md": "b"})
    for files in drafts:
        with pytest.raises(ValueError, match="clashes"):
            skill_files.stage_texts(files, skill_md="---\nname: x\ndescription: d\n---\nbody")
    assert _staging_left() == []


def test_a_scan_over_its_read_limit_names_its_own_limit(data, monkeypatch):
    big = tarball({"a.bin": b"\0" * (3 * 1024 * 1024)})
    with pytest.raises(skill_files.FolderTooLarge, match="larger than 1 MB"):
        skill_files.read_archive(big, keep=_everything, keep_limit=1024 * 1024)
    monkeypatch.setattr(skill_files, "MAX_FOLDER_BYTES", 0)              # one skill's budget: 2 MB
    with pytest.raises(skill_files.FolderTooLarge, match="skill's folder is larger than 20 MB"):
        skill_files.read_archive(big, keep=_everything)
