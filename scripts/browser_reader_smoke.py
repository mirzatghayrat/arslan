"""Real browser/public-example smoke; isolated runtime only, no app data or keys."""
import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path

from server.services import browser_reader, managed_browser


async def main(runtime: Path):
    runtime = runtime.resolve()
    if not runtime.is_relative_to(Path("/tmp").resolve()) or not runtime.name.startswith("arslan-reader-runtime."):
        raise ValueError("Use an isolated temporary reader runtime")
    if hashlib.sha256((runtime / "package-lock.json").read_bytes()).hexdigest() != managed_browser._digest():
        raise ValueError("Runtime lockfile mismatch")
    # Only this process gets the temporary runtime. No ready marker or settings
    # are written to the user's installed app.
    managed_browser.runtime_root = lambda: runtime
    managed_browser.status = lambda: {"ready": True}
    session = browser_reader.ReaderSession("synthetic-reader-smoke", None)
    try:
        await session.start()
        process_id = session.process.pid
        first = await session.act(browser_reader.ReaderAction(action="navigate", url="https://example.com"))
        assert "Example Domain" in first["text"] and first["revision"] == 1
        (runtime / "reader-first.jpg").write_bytes(base64.b64decode(first["screenshot"]))
        scrolled = await session.act(browser_reader.ReaderAction(action="scroll", direction=1))
        assert scrolled["revision"] == 2
        if first["links"]:
            try:
                await session.act(browser_reader.ReaderAction(action="link", link_id=first["links"][0]["id"], revision=1))
            except browser_reader.ReaderError as exc:
                assert exc.code == "browser.stale_view"
            else:
                raise AssertionError("Stale frame was accepted")
        refreshed = await session.act(browser_reader.ReaderAction(action="refresh"))
        assert refreshed["revision"] == 3
        children = await browser_reader._descendants(process_id)
        print(json.dumps({"real_browser": True, "url": refreshed["url"], "navigation": "passed",
                          "scroll_request": "passed", "stale_link": "passed", "refresh": "passed",
                          "blocked_connections": refreshed["blocked_connections"],
                          "screenshot": str(runtime / "reader-first.jpg"), "node_pid": process_id}))
    finally:
        temp = session.temp.name if session.temp else None
        await session.close()
        assert session.process is None or session.process.returncode is not None
        assert temp is None or not Path(temp).exists()
        remaining = []
        for pid in locals().get("children", []):
            try:
                os.kill(pid, 0)
                remaining.append(pid)
            except ProcessLookupError:
                pass
        assert not remaining, "Browser descendants survived closing"
        print(json.dumps({"session_closed": True, "temporary_profile_removed": True, "remaining_browser_children": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    asyncio.run(main(parser.parse_args().runtime))
