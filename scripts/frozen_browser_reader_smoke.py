"""Packaged reader API smoke with a disposable profile and existing test runtime.

Seeds runtime metadata only in that profile; does not test installation/download.
Contacts public example.com, never an account, user profile or installed app.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from scripts.frozen_sidecar_smoke import start, stop


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def descendants(parent: int) -> list[int]:
    # Do not import server configuration in this driver: even validation before
    # the disposable launch must not bootstrap the invoking user's key/profile.
    result = subprocess.run(["/bin/ps", "-axo", "pid=,ppid="], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, check=True, timeout=2)
    pairs = [tuple(map(int, line.split())) for line in result.stdout.splitlines()]
    found, frontier = set(), {parent}
    for _ in range(20):
        children = {pid for pid, ppid in pairs if ppid in frontier and pid not in found and pid != parent}
        if not children:
            break
        found.update(children)
        frontier = children
    return sorted(found)


def run(binary: Path, runtime: Path):
    binary, runtime = binary.resolve(), runtime.resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if not binary.is_relative_to(temp) or not any(part.startswith(
        ("arslan-candidate-build.", "arslan-native-candidate.")
    ) for part in binary.parts) or binary.name != "arslan-server":
        raise ValueError("Use a temporary frozen candidate")
    if not runtime.is_relative_to(temp) or not runtime.name.startswith("arslan-reader-runtime."):
        raise ValueError("Use an existing isolated reader test runtime")
    resources = binary.parent / "_internal/server/resources"
    source = Path(__file__).resolve().parent.parent / "server/resources"
    for filename in ("browser_reader.cjs", "browser_reader_policy.cjs"):
        assert digest(resources / filename) == digest(source / filename)
    pinned = digest(source / "browser_runtime/package-lock.json")
    assert digest(runtime / "package-lock.json") == pinned
    assert digest(resources / "browser_runtime/package-lock.json") == pinned
    assert (runtime / "node_modules/@playwright/mcp/cli.js").is_file()
    version = json.loads((source / "browser_runtime/package.json").read_text())["dependencies"]["@playwright/mcp"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)

    with tempfile.TemporaryDirectory(prefix="arslan-frozen-reader-") as folder:
        home = Path(folder).resolve()
        root = home / "Library/Application Support/Arslan/browser_runtime" / version
        root.mkdir(parents=True)
        # Reuse only the already provisioned temporary assets; no real profile,
        # package manager, setup endpoint or download is involved.
        (root / "node_modules").symlink_to(runtime / "node_modules", target_is_directory=True)
        (root / "browsers").symlink_to(runtime / "browsers", target_is_directory=True)
        browsers = json.loads((root / "node_modules/playwright-core/browsers.json").read_text())["browsers"]
        revision = next(item["revision"] for item in browsers if item["name"] == "chromium-headless-shell")
        matches = list((root / "browsers" / f"chromium_headless_shell-{revision}").rglob("chrome-headless-shell"))
        assert len(matches) == 1 and matches[0].is_file()
        browser = matches[0]
        (root / ".ready.json").write_text(json.dumps({"browser": str(browser), "lock_sha256": pinned}))
        process, client, _ = start(binary, home)
        session_id = None
        try:
            response = client.get("/api/v1/browser/status")
            response.raise_for_status()
            assert response.json()["ready"] is True, response.json()
            before = set(Path("/tmp").glob("arslan-reader-*"))
            created = client.post("/api/v1/browser/sessions", json={"conversation_id": "frozen-reader-smoke"}, timeout=30)
            assert created.status_code == 201, created.status_code
            session_id = created.json()["session_id"]
            profiles = set(Path("/tmp").glob("arslan-reader-*")) - before
            assert profiles
            children = descendants(process.pid)
            assert children

            def act(body):
                return client.post(f"/api/v1/browser/sessions/{session_id}/actions", json=body, timeout=35)

            response = act({"action": "navigate", "url": "https://example.com"})
            response.raise_for_status()
            first = response.json()
            assert "Example Domain" in first["text"] and first["screenshot"]
            assert first["mode"] == "isolated_read_only" and first["revision"] == 1
            assert first["conversation_id"] == "frozen-reader-smoke" and first["task_id"] is None
            refreshed = act({"action": "refresh"})
            refreshed.raise_for_status()
            assert refreshed.json()["revision"] == 2
            assert first["links"]
            stale = act({"action": "link", "link_id": first["links"][0]["id"], "revision": 1})
            assert stale.status_code == 409 and stale.json()["detail"]["code"] == "browser.stale_view"
            second_url = first["url"] + "#arslan-smoke"
            assert act({"action": "navigate", "url": second_url}).json()["url"] == second_url
            assert act({"action": "back"}).json()["url"] == first["url"]
            assert act({"action": "forward"}).json()["url"] == second_url
            assert act({"action": "type", "text": "synthetic-not-sent"}).status_code == 422
            assert act({"action": "navigate", "url": "file:///etc/passwd"}).status_code == 422
            assert client.delete(f"/api/v1/browser/sessions/{session_id}", timeout=15).status_code == 204
            assert act({"action": "refresh"}).status_code == 404
            session_id = None
            deadline = time.monotonic() + 5
            remaining = children
            while remaining and time.monotonic() < deadline:
                alive = []
                for pid in remaining:
                    try:
                        os.kill(pid, 0)
                        alive.append(pid)
                    except ProcessLookupError:
                        pass
                remaining = alive
                if remaining:
                    time.sleep(0.05)
            assert not remaining, "Owned browser children survived session close"
            assert all(not profile.exists() for profile in profiles)
            print(json.dumps({"frozen_reader_api": "passed", "resource_hashes_match_source": True,
                              "navigation_history_refresh": "passed", "stale_link_rejected": True,
                              "typing_and_file_urls_rejected": True, "owned_children_remaining": 0,
                              "reader_profiles_removed": True, "runtime_installation": "not_tested"}))
        finally:
            if session_id:
                try:
                    client.delete(f"/api/v1/browser/sessions/{session_id}", timeout=15)
                except Exception:
                    pass
            client.close()
            assert stop(process) == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("runtime", type=Path)
    args = parser.parse_args()
    run(args.binary, args.runtime)
