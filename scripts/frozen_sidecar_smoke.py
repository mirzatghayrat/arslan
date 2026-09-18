"""Exercise an unsigned temporary frozen sidecar, never an installed app.

Only loopback APIs, generated document bytes, and disposable application data.
The generated access token and subprocess output are never printed.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

import httpx


def stop(process):
    if process.stdin:
        process.stdin.close()
    try:
        return process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise RuntimeError("Frozen sidecar ignored parent-pipe closure") from None
    finally:
        if process.stdout:
            process.stdout.close()


def start(binary, home):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home),
           "ARSLAN_SECRET_KEY": "frozen-smoke-synthetic-only", "ARSLAN_SECRET_KEY_FILE": "",
           "ARSLAN_PORT": str(port), "ARSLAN_LIVE_LLM": "0"}
    process = subprocess.Popen([str(binary)], cwd=home, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5, trust_env=False)
    try:
        if not select.select([process.stdout], [], [], 45)[0]:
            raise RuntimeError("Frozen sidecar did not announce a port")
        assert process.stdout.readline().decode().strip() == f"ARSLAN_PORT={port}"
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Frozen sidecar exited before serving")
            try:
                response = client.get("/api/v1/settings")
                if response.status_code == 401:
                    break
                raise RuntimeError(f"Packaged API auth failed: status {response.status_code}")
            except httpx.ConnectError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Frozen sidecar startup deadline")
        token_file = home / "Library/Application Support/Arslan/api_token"
        assert token_file.stat().st_mode & 0o777 == 0o600
        token = token_file.read_text().strip()
        assert token
        client.headers["Authorization"] = f"Bearer {token}"
        assert client.get("/api/v1/settings").status_code == 200
        return process, client, token
    except BaseException:
        client.close()
        stop(process)
        raise


def main():
    binary = Path(sys.argv[1]).resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    assert binary.is_relative_to(temp) and any(part.startswith(("arslan-candidate-build.", "arslan-native-candidate.")) for part in binary.parts)
    assert binary.name == "arslan-server" and binary.is_file()
    with tempfile.TemporaryDirectory(prefix="arslan-frozen-smoke-") as folder:
        home = Path(folder)
        process, client, token = start(binary, home)
        try:
            root = client.get("/")
            assert root.status_code == 200 and '<div id="root">' in root.text
            assert client.get("/api/v1/settings").json()["first_run_seen"] is False
            assert client.put("/api/v1/settings", json={"first_run_seen": True}).json()["first_run_seen"] is True
            formats = client.get("/api/v1/input-formats").json()
            assert "docx" in formats["document"] and "pdf" in formats["document"]
            assert "xlsx" in formats["spreadsheet"] and "mp4" in formats["video"]
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as archive:
                archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Synthetic body</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Synthetic table</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
            response = client.post("/api/v1/extract", files={"file": ("fixture.docx", data.getvalue())}, data={"compress": "true"})
            assert response.status_code == 200
            assert "[word/document.xml#paragraph=2] Synthetic table" in response.json()["text"]
            assert not response.json()["truncated"]
            for filename, members, expected in (
                ("fixture.xlsx", {"xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Packaged sheet</t></is></c><c r="B1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>'}, "[xl/worksheets/sheet1.xml!A1] Packaged sheet"),
                ("fixture.pptx", {"ppt/slides/slide1.xml": '<p:sld xmlns:p="urn:p" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:r><a:t>Packaged slide</a:t></a:r></a:p></p:sld>'}, "[ppt/slides/slide1.xml#paragraph=1] Packaged slide"),
            ):
                package = io.BytesIO()
                with zipfile.ZipFile(package, "w") as archive:
                    for member, body in members.items():
                        archive.writestr(member, body)
                response = client.post("/api/v1/extract", files={"file": (filename, package.getvalue())},
                                       data={"compress": "true"})
                assert response.status_code == 200
                assert expected in response.json()["text"] and not response.json()["truncated"]
                if filename.endswith("xlsx"):
                    assert '"formula": "1+1"' in response.json()["text"]
                    assert '"cached_value_unverified": "2"' in response.json()["text"]
            source = 'const original = "原文";\n// Keep source inert and exact.\n'
            response = client.post("/api/v1/extract", files={"file": ("fixture.tsx", source.encode())},
                                   data={"compress": "true"})
            assert response.status_code == 200 and response.json()["text"] == source
            browser = client.post("/api/v1/browser/sessions", json={"conversation_id": "frozen-smoke"})
            assert browser.status_code == 409
            assert browser.json()["detail"]["code"] in {"browser.setup_required", "browser.node_required", "browser.macos_required"}
            assert formats["video_transcription"] is False and formats["video_visual_understanding"] is False
            if not formats["video_metadata_available"]:
                video = client.post("/api/v1/extract", files={"file": ("fixture.mp4", b"synthetic-invalid-video")})
                assert video.status_code == 400 and video.json()["detail"]["code"] == "inputs.videoToolMissing"
            from pypdf import PdfWriter
            from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
            writer = PdfWriter()
            for text in ("Synthetic readable PDF source text.", "", "Third source page."):
                page = writer.add_blank_page(width=300, height=300)
                if not text:
                    continue
                page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
                    NameObject("/F1"): DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})})})
                content = DecodedStreamObject()
                content.set_data(f"BT /F1 12 Tf 20 250 Td ({text}) Tj ET".encode("ascii"))
                page[NameObject("/Contents")] = content
            pdf = io.BytesIO()
            writer.write(pdf)
            response = client.post("/api/v1/extract", files={"file": ("fixture.pdf", pdf.getvalue())}, data={"compress": "true"})
            assert response.status_code == 200
            assert "[page 3]\nThird source page." in response.json()["text"]
            for language in ("en", "zh", "ja", "es", "de", "fr"):
                assert client.put("/api/v1/settings", json={"language": language}).status_code == 200
                assert client.get("/api/v1/settings").json()["language"] == language
                hint = home / "Library/Application Support/Arslan/ui_language"
                assert hint.read_text() == language + "\n"
                assert hint.stat().st_mode & 0o777 == 0o600
        finally:
            client.close()
            assert stop(process) == 0
        hint.unlink()  # Disposable cache loss must not lose the saved preference.
        process, client, restored_token = start(binary, home)
        try:
            assert restored_token == token
            assert client.get("/api/v1/settings").json()["language"] == "fr"
            assert client.get("/api/v1/settings").json()["first_run_seen"] is True
            assert hint.read_text() == "fr\n"
        finally:
            client.close()
            assert stop(process) == 0
    print(json.dumps({"frozen": True, "authenticated_api": True, "fresh_boot_and_restart": True,
                      "word_table_locator": True, "pdf_page_locator": True, "six_saved_languages": True,
                      "spreadsheet_formula_and_cell_locators": True, "slide_locators": True,
                      "inert_code_preserved": True, "fresh_browser_gate": True,
                      "video_capability_limits_explicit": True,
                      "token_and_language_retained": True, "parent_pipe_shutdown": True,
                      "native_locale_cache_repaired": True,
                      "onboarding_seen_retained": True,
                      "real_model": False, "installed_app": False}))


if __name__ == "__main__":
    main()
