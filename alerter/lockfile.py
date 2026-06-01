"""
A single-instance guard.

Two monitors running at once would clobber the same state file and double-send
alerts. This context manager takes an exclusive OS-level lock on a file; if
another process already holds it, we refuse to start. The lock is released
automatically when the process exits (the kernel drops it), so a crash can't
leave us permanently locked out.

Uses fcntl.flock, which works on Linux and macOS (the deploy target and dev box).
"""

from __future__ import annotations

import errno
import fcntl
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("alerter.lockfile")


class AlreadyRunning(RuntimeError):
    """Raised when another instance already holds the lock."""


@contextmanager
def single_instance(path: str | Path, wait_seconds: float = 5.0) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` for the duration of the block.

    Retries for up to ``wait_seconds`` first — this smooths over a deploy
    restart, where the old process may take a moment to release the lock before
    the new one starts. Raises AlreadyRunning if the lock can't be acquired.
    """
    lock_path = Path(path)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)

    # --- acquire (closing the fd ourselves on any failure path) ---
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.EACCES):
                os.close(fd)
                raise
            if time.monotonic() >= deadline:
                os.close(fd)
                raise AlreadyRunning(
                    f"another instance already holds {lock_path}"
                ) from e
            time.sleep(0.5)

    # --- hold it for the duration of the block, release on exit ---
    try:
        # Record our PID for humans debugging the box; not used for the lock.
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        log.debug("acquired single-instance lock %s", lock_path)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
