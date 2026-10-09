"""Reading files in Arslan's own window (0.1.58 §2–§3): the right panel's folder browser,
the reader, and clickable paths in replies.

The boundary is the same one Arslan's read tools use (workspace_paths.read_roots — the
workspace, plus Desktop/Documents/Downloads when "default read" is on), plus each active
project's folder and Arslan's own artifacts. Inside it:

* a path is resolved (symlinks followed) before it is judged, so a link cannot lead out;
* dot-files and dot-folders are neither listed nor read, nor are credential-shaped names
  (workspace_paths.is_secret_name);
* bytes go to the page only through an authenticated fetch, never as a page served from
  Arslan's own origin (the API sends them as an attachment, see server/api/files.py).

Outside it Arslan does not read the file; the window can only reveal it in Finder.
"""
from __future__ import annotations

import asyncio
import csv
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from server.services.workspace_paths import _contained, is_secret_name, read_roots

MAX_BYTES = 50 * 1024 * 1024        # the reader's cap (as the artifact preview's)
LIST_LIMIT = 500                    # entries per folder, then "显示更多"
TABLE_ROWS = 1000                   # rows shown for csv/xlsx
STAT_LIMIT = 50                     # paths per batch stat (one message's worth)
PDF_PAGES = 30                      # pages rendered as images when WebKit cannot show a PDF


class NotReadable(Exception):
    """Outside the readable roots, hidden, credential-shaped, missing or too big."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def roots() -> list[Path]:
    from server.db import session as db_session
    from server.db.companion_models import Project
    from server.services import artifact_store, settings_service
    from sqlalchemy import select
    async with db_session.AsyncSessionLocal() as db:
        ws = await settings_service.workspace_dir(db)
        default_read = await settings_service.default_read_enabled(db)
        folders = (await db.execute(select(Project.workspace_ref).where(
            Project.status == "active", Project.workspace_ref.is_not(None)))).scalars().all()
    out = read_roots(ws, default_read=default_read)
    for raw in [*folders, str(artifact_store.root())]:
        try:
            p = Path(str(raw).strip()).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if str(raw).strip() and p.is_dir() and p not in out:
            out.append(p)
    return out


def _hidden(path: Path, root: Path) -> bool:
    rel = path.relative_to(root) if path != root else Path()
    return any(part.startswith(".") for part in rel.parts) or is_secret_name(path.name)


def resolve(raw: str, readable: list[Path]) -> tuple[Path, Path]:
    """(path, its root) for a readable path, or NotReadable."""
    text = (raw or "").strip()
    if not text or "\x00" in text:
        raise NotReadable("invalid_path")
    p = Path(text).expanduser()
    if not p.is_absolute():
        raise NotReadable("invalid_path")
    try:
        resolved = p.resolve()
    except (OSError, RuntimeError):
        raise NotReadable("invalid_path") from None
    root = next((r for r in readable if _contained(resolved, r)), None)
    if root is None:
        raise NotReadable("outside")
    if _hidden(resolved, root):
        raise NotReadable("hidden")
    if not resolved.exists():
        raise NotReadable("missing")
    return resolved, root


def _home(path: Path) -> str:
    home = Path.home()
    return "~/" + str(path.relative_to(home)) if path != home and path.is_relative_to(home) else str(path)


def listing(raw: str, readable: list[Path], *, offset: int = 0) -> dict:
    path, root = resolve(raw, readable)
    if not path.is_dir():
        raise NotReadable("not_a_folder")
    children = []
    for child in path.iterdir():
        if child.name.startswith(".") or is_secret_name(child.name):
            continue
        try:
            st = child.stat()
            is_dir = child.is_dir()
        except OSError:
            continue
        children.append({"name": child.name, "path": _home(child), "is_dir": is_dir,
                         "bytes": None if is_dir else st.st_size,
                         "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()})
    children.sort(key=lambda c: (not c["is_dir"], c["name"].lower()))
    page = children[offset:offset + LIST_LIMIT]
    crumbs = []
    cur = path
    while True:
        crumbs.append({"name": cur.name or _home(cur), "path": _home(cur)})
        if cur == root or cur.parent == cur:
            break
        cur = cur.parent
    return {"path": _home(path), "root": _home(root), "crumbs": list(reversed(crumbs)), "entries": page,
            "total": len(children), "more": offset + LIST_LIMIT < len(children)}


def read_bytes(raw: str, readable: list[Path]) -> tuple[Path, bytes]:
    path, _ = resolve(raw, readable)
    if not path.is_file():
        raise NotReadable("not_a_file")
    if path.stat().st_size > MAX_BYTES:
        raise NotReadable("too_big")
    return path, path.read_bytes()


def stat(paths: list[str], readable: list[Path]) -> list[dict]:
    out = []
    for raw in paths[:STAT_LIMIT]:
        item = {"path": raw, "exists": False, "readable": False, "is_dir": False}
        try:
            p = Path((raw or "").strip()).expanduser()
            if p.is_absolute() and p.exists():
                item["exists"] = True
                item["is_dir"] = p.is_dir()
                try:
                    resolve(raw, readable)
                    item["readable"] = True
                except NotReadable:
                    pass
        except (OSError, RuntimeError, ValueError):
            pass
        out.append(item)
    return out


def table(name: str, data: bytes) -> dict:
    """csv / tsv / xlsx as rows: {"sheets": [{"name", "rows", "truncated"}]}."""
    ext = name.rsplit(".", 1)[-1].lower()
    if ext in ("csv", "tsv"):
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text), delimiter="\t" if ext == "tsv" else ",")
        rows = []
        for row in reader:
            if len(rows) >= TABLE_ROWS:
                return {"sheets": [{"name": name, "rows": rows, "truncated": True}]}
            rows.append([c[:500] for c in row[:100]])
        return {"sheets": [{"name": name, "rows": rows, "truncated": False}]}
    if ext == "xlsx":
        return _xlsx(data)
    raise NotReadable("not_a_table")


def _col(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _xlsx(data: bytes) -> dict:
    from server.services.input_formats import NS, InputError, _xml
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            strings = (["".join(n.itertext()) for n in _xml(archive, "xl/sharedStrings.xml").findall("s:si", NS)]
                       if "xl/sharedStrings.xml" in names else [])
            titles: list[str] = []
            if "xl/workbook.xml" in names:
                titles = [s.get("name", "") for s in _xml(archive, "xl/workbook.xml").findall(".//s:sheets/s:sheet", NS)]
            sheets_xml = sorted((n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                                key=lambda n: int(re.search(r"(\d+)\.xml", n)[1]))[:20]
            sheets = []
            for i, sheet in enumerate(sheets_xml):
                grid: dict[int, dict[int, str]] = {}
                truncated = False
                for cell in _xml(archive, sheet).findall(".//s:sheetData/s:row/s:c", NS):
                    m = re.fullmatch(r"([A-Z]{1,3})([1-9]\d{0,6})", cell.get("r", ""))
                    if not m:
                        continue
                    r, c = int(m[2]) - 1, _col(m[1])
                    if r >= TABLE_ROWS:
                        truncated = True
                        continue
                    if c >= 100:
                        continue
                    value = cell.findtext("s:v", "", NS)
                    if cell.get("t") == "s":
                        try:
                            value = strings[int(value)]
                        except (ValueError, IndexError):
                            value = ""
                    elif cell.get("t") == "inlineStr":
                        node = cell.find("s:is", NS)
                        value = "".join(node.itertext()) if node is not None else ""
                    grid.setdefault(r, {})[c] = value[:500]
                width = max((max(row) + 1 for row in grid.values() if row), default=0)
                rows = [[grid.get(r, {}).get(c, "") for c in range(width)] for r in range(max(grid, default=-1) + 1)]
                sheets.append({"name": titles[i] if i < len(titles) and titles[i] else f"Sheet{i + 1}",
                               "rows": rows, "truncated": truncated})
            return {"sheets": sheets}
    except (zipfile.BadZipFile, InputError, OSError, KeyError):
        raise NotReadable("unreadable") from None


async def as_html(path: Path) -> str:
    """docx / doc / rtf / odt → HTML with macOS's own textutil (shown sandboxed, no scripts)."""
    if path.suffix.lower() not in (".docx", ".doc", ".rtf", ".rtfd", ".odt", ".wordml", ".webarchive"):
        raise NotReadable("not_a_document")
    proc = await asyncio.create_subprocess_exec(
        "/usr/bin/textutil", "-convert", "html", "-stdout", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 20)
    except asyncio.TimeoutError:
        proc.kill()
        raise NotReadable("unreadable") from None
    if proc.returncode != 0:
        raise NotReadable("unreadable")
    return out.decode("utf-8", errors="replace")


def pdf_page(data: bytes, page: int) -> tuple[bytes, int]:
    """One PDF page as PNG (the fallback when WebKit cannot show the PDF itself)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(data)
    try:
        count = len(doc)
        if not 0 <= page < min(count, PDF_PAGES):
            raise NotReadable("no_page")
        image = doc[page].render(scale=1.6).to_pil()
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue(), count
    finally:
        doc.close()
