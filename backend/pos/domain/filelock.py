"""Cross-process lock around read-modify-write of the local JSON state files.

Two tills (or a till and `sync-pending`) in one store must never read the same
"next invoice number". The lock is a sibling `<file>.lock` created with O_EXCL,
which is atomic on Windows and POSIX. A lock older than STALE_SECS is assumed to be
left by a crashed process and is taken over.
"""

import functools
import os
import time
from contextlib import contextmanager
from pathlib import Path

STALE_SECS = 10.0
WAIT_SECS = 15.0


@contextmanager
def file_lock(path: Path):
    lock = Path(str(path) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + WAIT_SECS
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except (FileExistsError, PermissionError):
            # Windows reports PermissionError (not FileExistsError) while the holder is deleting the lock
            try:
                if time.time() - lock.stat().st_mtime > STALE_SECS:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            except PermissionError:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError(f"Could not lock {path}; another till is holding it")
            time.sleep(0.01)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def locked(method):
    """Decorator for manager methods that mutate `self.file_path` (reload inside the lock)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with file_lock(self.file_path):
            return method(self, *args, **kwargs)
    return wrapper


def _retry_on_sharing_violation(fn, attempts: int = 200, delay: float = 0.01):
    """Windows raises PermissionError when another process has the file open for an instant
    (read vs atomic replace). That is transient, so retry briefly instead of crashing a bill."""
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def read_json(path: Path, default):
    """Read a JSON state file; a missing file gives `default`."""
    import json

    def _read():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default

    return _retry_on_sharing_violation(_read)


def write_json_atomic(path: Path, data) -> None:
    """Write via a per-process temp file, then atomically replace the target."""
    import json

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    _retry_on_sharing_violation(lambda: os.replace(tmp, path))
