"""Shared format declaration and bounded, non-executing text/OOXML readers."""
from __future__ import annotations

import io
import json
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree as ET

_SERVER = Path(__file__).resolve().parent.parent
_REGISTRY_PATH = _SERVER / "resources/input_formats.json"
if not _REGISTRY_PATH.exists():
    _REGISTRY_PATH = _SERVER.parent / "web/src/lib/input_formats.json"
REGISTRY = json.loads(_REGISTRY_PATH.read_text())
MAX_TEXT = 200_000
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


class InputError(ValueError):
    """Message is a stable localization code, never parser output or file content."""


def kind(filename: str) -> str | None:
    extension = Path(filename).suffix.lower().lstrip(".")
    return next((key for key, values in REGISTRY.items() if isinstance(values, list) and extension in values), None)


def _xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        info = archive.getinfo(name)
        if info.file_size > 8 * 1024 * 1024:
            raise InputError("inputs.limit")
        raw = archive.read(info).decode("utf-8-sig")
        if "<!DOCTYPE" in raw.upper() or "<!ENTITY" in raw.upper():
            raise InputError("inputs.invalid")
        return ET.fromstring(raw)
    except (KeyError, ET.ParseError, RuntimeError, UnicodeDecodeError) as exc:
        raise InputError("inputs.invalid") from exc


def read_structured(filename: str, data: bytes) -> tuple[str, bool]:
    """Extract source-addressed values without opening links or evaluating formulas."""
    if len(data) > REGISTRY["max_bytes"]:
        raise InputError("inputs.limit")
    category = kind(filename)
    if category == "text":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InputError("inputs.encoding") from exc
        if "\x00" in text:
            raise InputError("inputs.encoding")
        return text[:MAX_TEXT], len(text) > MAX_TEXT
    if category not in {"spreadsheet", "presentation"}:
        raise InputError("inputs.unsupported")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        with archive:
            entries = archive.infolist()
            if len(entries) > 3000 or sum(item.file_size for item in entries) > 64 * 1024 * 1024:
                raise InputError("inputs.limit")
            if len({item.filename for item in entries}) != len(entries) or any(item.flag_bits & 1 for item in entries):
                raise InputError("inputs.invalid")
            lines: list[str] = []
            total = 0
            truncated = False

            def add(locator: str, value: str):
                nonlocal total, truncated
                line = f"[{locator}] {value}"
                if total + len(line) + 1 > MAX_TEXT or len(lines) >= 50_000:
                    truncated = True
                    return
                lines.append(line)
                total += len(line) + 1

            if category == "spreadsheet":
                strings: list[str] = []
                if "xl/sharedStrings.xml" in archive.namelist():
                    strings = ["".join(node.itertext()) for node in _xml(archive, "xl/sharedStrings.xml").findall("s:si", NS)]
                sheets = sorted(name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
                if not sheets or len(sheets) > 100:
                    raise InputError("inputs.limit" if sheets else "inputs.invalid")
                for name in sheets:
                    for cell in _xml(archive, name).findall(".//s:sheetData/s:row/s:c", NS):
                        address = cell.get("r", "?")
                        if not re.fullmatch(r"[A-Z]{1,3}[1-9]\d{0,6}", address):
                            raise InputError("inputs.invalid")
                        value = cell.findtext("s:v", "", NS)
                        if cell.get("t") == "s":
                            try:
                                index = int(value)
                                if index < 0:
                                    raise ValueError
                                value = strings[index]
                            except (ValueError, IndexError) as exc:
                                raise InputError("inputs.invalid") from exc
                        elif cell.get("t") == "inlineStr":
                            value = "".join(cell.find("s:is", NS).itertext()) if cell.find("s:is", NS) is not None else ""
                        formula = cell.findtext("s:f", default=None, namespaces=NS)
                        # Cached values may be stale. The model gets this distinction explicitly.
                        if formula is not None:
                            value = json.dumps({"formula": formula, "cached_value_unverified": value}, ensure_ascii=False)
                        if value:
                            add(f"{name}!{address}", value)
                        if truncated:
                            break
                    if truncated:
                        break
            else:
                slides = sorted((name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)), key=lambda name: int(re.search(r"(\d+)\.xml", name)[1]))
                if not slides or len(slides) > 500:
                    raise InputError("inputs.limit" if slides else "inputs.invalid")
                for name in slides:
                    for index, paragraph in enumerate(_xml(archive, name).findall(".//a:p", NS), 1):
                        value = "".join(node.text or "" for node in paragraph.findall(".//a:t", NS))
                        if value:
                            add(f"{name}#paragraph={index}", value)
                        if truncated:
                            break
                    if truncated:
                        break
            return "\n".join(lines), truncated
    except (zipfile.BadZipFile, OSError, EOFError) as exc:
        raise InputError("inputs.invalid") from exc


def video_metadata(filename: str, data: bytes) -> dict:
    """Optional local codec probe. No network protocols, model, or transcript."""
    import os
    import shutil
    import subprocess
    import tempfile

    executable = shutil.which("ffprobe")
    if not executable:
        raise InputError("inputs.videoToolMissing")
    if len(data) > REGISTRY["max_bytes"]:
        raise InputError("inputs.limit")
    with tempfile.TemporaryDirectory(prefix="arslan-media-") as folder:
        source = Path(folder) / ("input" + Path(filename).suffix.lower())
        source.write_bytes(data)
        output = Path(folder) / "probe.json"
        try:
            with output.open("wb") as stream:
                result = subprocess.run([executable, "-v", "error", "-protocol_whitelist", "file,pipe",
                    "-format_whitelist", "mov,matroska,webm", "-show_entries",
                    "format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,duration,avg_frame_rate,sample_rate,channels",
                    "-of", "json", str(source)], stdout=stream, stderr=subprocess.DEVNULL,
                    timeout=20, cwd=folder, env={"PATH": "/usr/bin:/bin", "HOME": folder, "TMPDIR": folder})
            if result.returncode or os.path.getsize(output) > 1_000_000:
                raise InputError("inputs.invalid")
            metadata = json.loads(output.read_text())
            if not isinstance(metadata.get("streams"), list) or len(metadata["streams"]) > 32:
                raise InputError("inputs.limit")
            if not any(stream.get("codec_type") == "video" for stream in metadata["streams"]):
                raise InputError("inputs.invalid")
            return {"metadata": metadata, "frames": "not_extracted", "transcript": "not_generated",
                    "visual_understanding": "not_run", "editing": "not_run"}
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            raise InputError("inputs.invalid") from exc
