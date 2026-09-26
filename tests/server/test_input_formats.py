import io
import json
import struct
import zipfile

import pytest

from server.services.input_formats import InputError, kind, read_structured, video_metadata


def test_csv_record_locators_distinguish_header_blank_and_multiline_cells():
    text, truncated = read_structured("records.csv", b'name,amount\n"quoted, label",-1\nmissing,\n"two\nlines",2\n')
    assert not truncated
    assert "CSV logical records: 4 (includes any header" in text
    assert "Records containing empty fields: 1" in text
    assert '[CSV record 1; lines 1-1] ["name", "amount"]' in text
    assert '[CSV record 2; lines 2-2] ["quoted, label", "-1"]' in text
    assert '[CSV record 3; lines 3-3] ["missing", ""]' in text
    assert '[CSV record 4; lines 4-5] ["two\\nlines", "2"]' in text


def test_csv_malformed_quotes_remain_raw_not_silently_repaired():
    raw = 'name,value\n"unterminated,1'
    assert read_structured("records.csv", raw.encode()) == (raw, False)


def package(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return stream.getvalue()


def test_code_stays_inert_and_binary_text_is_rejected():
    assert kind("EXAMPLE.TSX") == "text"
    text, truncated = read_structured("file.tsx", b"<script>do_not_execute()</script>")
    assert text == "<script>do_not_execute()</script>" and not truncated
    with pytest.raises(InputError, match="encoding"):
        read_structured("data.csv", b"\x00\xff")


def test_xlsx_addresses_formula_and_cached_value():
    data = package({"xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Hello</t></is></c><c r="B1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>'})
    text, truncated = read_structured("file.xlsx", data)
    assert "[xl/worksheets/sheet1.xml!A1] Hello" in text
    assert '"cached_value_unverified": "2"' in text
    assert '"formula": "1+1"' in text and not truncated


def test_pptx_paragraphs_have_slide_locators_and_never_fetch_links():
    data = package({"ppt/slides/slide1.xml": '<p:sld xmlns:p="urn:p" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:r><a:t>Slide text</a:t></a:r></a:p></p:sld>', "ppt/slides/_rels/slide1.xml.rels": '<Relationships><Relationship Target="http://127.0.0.1/private"/></Relationships>'})
    text, _ = read_structured("file.pptx", data)
    assert text == "[ppt/slides/slide1.xml#paragraph=1] Slide text"


@pytest.mark.parametrize("body", [b'<!DOCTYPE x [<!ENTITY y "secret">]><x>&y;</x>', '<!DOCTYPE x [<!ENTITY y "secret">]><x>&y;</x>'.encode("utf-16")])
def test_xml_entities_are_rejected_including_alternate_encoding(body):
    with pytest.raises(InputError, match="invalid"):
        read_structured("file.pptx", package({"ppt/slides/slide1.xml": body}))


def test_zip_and_output_limits_are_explicit(monkeypatch):
    from server.services import input_formats
    monkeypatch.setattr(input_formats, "MAX_TEXT", 5)
    assert read_structured("file.json", b"123456") == ("12345", True)
    with pytest.raises(InputError, match="invalid"):
        read_structured("bad.xlsx", b"not a zip")


@pytest.mark.parametrize("damage", ["unsupported_compression", "invalid_deflate"])
@pytest.mark.parametrize("extension, member", [
    ("pptx", "ppt/slides/slide1.xml"),
    ("xlsx", "xl/worksheets/sheet1.xml"),
    ("docx", "word/document.xml"),
])
def test_damaged_zip_members_return_stable_input_error(damage, extension, member):
    data = bytearray(package({member: "<document/>"}))
    if damage == "unsupported_compression":
        central = data.index(b"PK\x01\x02")
        struct.pack_into("<H", data, 8, 99)
        struct.pack_into("<H", data, central + 10, 99)
    else:
        name_size, extra_size = struct.unpack_from("<HH", data, 26)
        start = 30 + name_size + extra_size
        # BFINAL=1 and reserved BTYPE=3: an invalid DEFLATE block.
        data[start] = 7
    with pytest.raises(InputError, match=r"^inputs\.invalid$"):
        read_structured(f"damaged.{extension}", bytes(data))


def test_missing_video_tool_is_not_a_success(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _, **kwargs: None)
    with pytest.raises(InputError, match="videoToolMissing"):
        video_metadata("file.mp4", b"x")


def test_video_probe_uses_no_network_or_user_environment(monkeypatch):
    import shutil
    import subprocess
    from types import SimpleNamespace
    monkeypatch.setattr(shutil, "which", lambda _: "/trusted/ffprobe")
    def probe(args, **kwargs):
        assert args[args.index("-protocol_whitelist") + 1] == "file,pipe"
        assert set(kwargs["env"]) == {"PATH", "HOME", "TMPDIR"}
        assert kwargs["timeout"] == 20
        assert "stream_disposition=attached_pic" in args[args.index("-show_entries") + 1]
        kwargs["stdout"].write(json.dumps({"streams": [{"index": 0, "codec_type": "video", "width": 640}], "format": {"duration": "1"}}).encode())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", probe)
    result = video_metadata("file.mp4", b"x")
    assert result["visual_understanding"] == "not_run"
    assert result["transcript"] == "not_generated"


@pytest.mark.parametrize("streams", [
    [{"index": 0, "codec_type": "video", "disposition": {"attached_pic": 1}}],
    [{"index": -1, "codec_type": "video"}],
    [{"index": True, "codec_type": "video"}],
    [{"codec_type": "video"}],
    [None],
])
def test_video_probe_rejects_cover_only_or_invalid_streams(monkeypatch, streams):
    import shutil
    import subprocess
    from types import SimpleNamespace
    monkeypatch.setattr(shutil, "which", lambda _: "/trusted/ffprobe")
    def probe(args, **kwargs):
        kwargs["stdout"].write(json.dumps({"streams": streams}).encode())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", probe)
    with pytest.raises(InputError, match="inputs.invalid"):
        video_metadata("cover.mp4", b"x")
