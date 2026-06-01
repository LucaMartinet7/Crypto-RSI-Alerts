"""
A tiny durable state store: load/save one JSON object to a file, atomically.

Split out from the monitor so the "how do we persist" details (JSON, atomic
writes, error handling) live in one place, and the monitor can stay focused on
orchestration. You could swap this for a different backend (Redis, a database)
without touching the monitor.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("alerter.state")


class JsonStateStore:
    """Reads/writes one JSON object to a file.

    Writes are atomic: we write to a temp file and rename it over the target, so
    a crash mid-write can never leave a half-written (corrupt) file behind.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict:
        """Return the saved dict, or an empty dict if the file is missing or
        unreadable — so a corrupt file means 'start fresh', not a crash."""
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except Exception as e:
            log.warning("Could not read state file %s (%s) — starting fresh.",
                        self.path, e)
            return {}

    def save(self, data: dict) -> None:
        """Write the dict to disk atomically (temp file + rename)."""
        try:
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            os.replace(tmp, self.path)   # atomic on POSIX
        except Exception as e:
            log.error("Could not write state file %s: %s", self.path, e)
