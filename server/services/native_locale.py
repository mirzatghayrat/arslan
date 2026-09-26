"""Non-secret, fixed-name language hint for dialogs shown before the sidecar boots.

The database remains authoritative. This disposable cache grants no capability,
contains only a normalized language code, and never reads provider settings.
"""
from __future__ import annotations

import logging
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server import config
from server.db.models import Setting
from server.locale_codes import normalize

logger = logging.getLogger(__name__)
FILENAME = "ui_language"


def write_hint(language: str | None) -> None:
    root = config.data_dir()
    temporary: Path | None = None
    try:
        root.mkdir(parents=True, exist_ok=True)
        # mkstemp is exclusive and mode 0600; replace does not follow a target
        # symlink and readers see either complete old or complete new content.
        fd, name = tempfile.mkstemp(prefix=".ui_language-", dir=root)
        temporary = Path(name)
        with os.fdopen(fd, "w", encoding="ascii") as output:
            output.write(normalize(language) + "\n")
        os.replace(temporary, root / FILENAME)
    except OSError:
        # A cache failure must not roll back a committed setting or stop boot.
        logger.warning("Native language hint could not be refreshed")
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


async def sync(session: AsyncSession) -> None:
    language = await session.scalar(select(Setting.value).where(Setting.key == "language"))
    write_hint(language)
