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
        finally:
            client.close()
            assert stop(process) == 0
        process, client, restored_token = start(binary, home)
        try:
            assert restored_token == token
            assert client.get("/api/v1/settings").json()["language"] == "fr"
        finally:
            client.close()
            assert stop(process) == 0
    print(json.dumps({"frozen": True, "authenticated_api": True, "fresh_boot_and_restart": True,
                      "word_table_locator": True, "pdf_page_locator": True, "six_saved_languages": True,
                      "token_and_language_retained": True, "parent_pipe_shutdown": True,
                      "real_model": False, "installed_app": False}))


if __name__ == "__main__":
    main()
