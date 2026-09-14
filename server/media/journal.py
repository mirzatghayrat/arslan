"""Host-only durable media job journal. No HTTP/model entry points.

The host supplies a private application-data path, never a task-controlled path.
Each transition commits before the adapter performs a remote write. Comparing
the full previous snapshot prevents stale prepared jobs from submitting twice,
including across separate processes or after an application restart.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sqlite3

from server.media.contracts import MediaError, MediaJob


class MediaJournal:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self):
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE IF NOT EXISTS media_jobs (id TEXT PRIMARY KEY, snapshot TEXT NOT NULL)")
        return connection

    @staticmethod
    def _snapshot(job: MediaJob) -> str:
        # Revalidate even snapshots supplied through model_copy by a host.
        return MediaJob.model_validate(job.model_dump()).model_dump_json()

    async def persist(self, expected: MediaJob | None, updated: MediaJob) -> None:
        await asyncio.to_thread(self._persist, expected, updated)

    def _persist(self, expected: MediaJob | None, updated: MediaJob):
        value = self._snapshot(updated)
        if expected is not None and (expected.id != updated.id or expected.intent_hash != updated.intent_hash):
            raise MediaError("media_job_pin_changed")
        connection = self._connect()
        try:
            with connection:
                if expected is None:
                    result = connection.execute("INSERT OR IGNORE INTO media_jobs (id, snapshot) VALUES (?, ?)", (updated.id, value))
                else:
                    result = connection.execute("UPDATE media_jobs SET snapshot = ? WHERE id = ? AND snapshot = ?",
                                                (value, updated.id, self._snapshot(expected)))
                if result.rowcount != 1:
                    raise MediaError("media_job_stale")
        finally:
            connection.close()

    async def get(self, job_id: str, *, owner_id: str, task_id: str, run_id: int) -> MediaJob:
        job = await asyncio.to_thread(self._get, job_id)
        if (job.owner_id, job.task_id, job.run_id) != (owner_id, task_id, run_id):
            raise MediaError("media_job_scope_denied")
        return job

    def _get(self, job_id: str) -> MediaJob:
        connection = self._connect()
        try:
            row = connection.execute("SELECT snapshot FROM media_jobs WHERE id = ?", (job_id,)).fetchone()
        finally:
            connection.close()
        if row is None:
            raise MediaError("media_job_unknown")
        return MediaJob.model_validate_json(row[0])
