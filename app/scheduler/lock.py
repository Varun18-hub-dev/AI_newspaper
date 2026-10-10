"""Concurrency and overlap prevention using cross-process file locks and in-process thread locks."""

from contextlib import contextmanager
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Dict, Generator, Optional

try:
    import portalocker
except ImportError:
    portalocker = None

from app.core.config import settings
from app.core.logging import setup_logger

logger = setup_logger("scheduler_lock")

_IN_PROCESS_LOCK = threading.Lock()


class PipelineRunAlreadyActiveError(Exception):
    """Raised when an automated or manual run cannot start because another run is active."""
    pass


class PipelineRunLock:
    """Manages cross-process and in-process locks to prevent concurrent pipeline runs."""

    def __init__(self, lock_file_path: Optional[str] = None):
        """Initializes the lock manager.

        Args:
            lock_file_path: Path to file lock. Defaults to settings.schedule_lock_file.
        """
        self.lock_file_path = str(
            lock_file_path if lock_file_path is not None else settings.schedule_lock_file
        )
        self._file_lock: Optional[Any] = None
        self._acquired_thread_lock = False
        self._acquired_file_lock = False

    def acquire(self) -> bool:
        """Attempts to acquire both thread and file locks without blocking.

        Returns:
            bool: True if both locks acquired successfully.

        Raises:
            PipelineRunAlreadyActiveError: If another run is already in progress.
        """
        # 1. In-process lock
        if not _IN_PROCESS_LOCK.acquire(blocking=False):
            raise PipelineRunAlreadyActiveError(
                "A pipeline run is already active within this process."
            )
        self._acquired_thread_lock = True

        # 2. Cross-process file lock
        try:
            lock_path = Path(self.lock_file_path)
            lock_path.parent.mkdir(parents=True, exist_ok=True)

            if portalocker is not None:
                self._file_lock = portalocker.Lock(
                    self.lock_file_path,
                    mode="a+",
                    flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
                )
                self._file_lock.acquire()
            else:
                logger.warning("portalocker not available; relying solely on in-process thread lock.")

            self._acquired_file_lock = True
            # Write holder metadata (PID and timestamp) to lock file
            if self._file_lock is not None and hasattr(self._file_lock, "fh") and self._file_lock.fh is not None:
                try:
                    self._file_lock.fh.seek(0)
                    self._file_lock.fh.truncate(0)
                    meta = json.dumps({
                        "pid": os.getpid(),
                        "acquired_at": datetime.utcnow().isoformat(),
                    })
                    self._file_lock.fh.write(meta)
                    self._file_lock.fh.flush()
                except Exception:
                    pass

            logger.debug(f"Acquired pipeline lock on {self.lock_file_path}")
            return True

        except Exception as exc:
            # Clean up thread lock if file lock failed
            self.release()
            raise PipelineRunAlreadyActiveError(
                f"A pipeline run is already active across processes (lockfile: {self.lock_file_path}): {exc}"
            ) from exc

    def release(self) -> None:
        """Releases all acquired locks safely."""
        if self._acquired_file_lock and self._file_lock is not None:
            try:
                # Clear metadata before release
                if hasattr(self._file_lock, "fh") and self._file_lock.fh is not None:
                    try:
                        self._file_lock.fh.seek(0)
                        self._file_lock.fh.truncate(0)
                        self._file_lock.fh.flush()
                    except Exception:
                        pass
                self._file_lock.release()
            except Exception as err:
                logger.warning(f"Error releasing file lock: {err}")
            finally:
                self._acquired_file_lock = False
                self._file_lock = None

        if self._acquired_thread_lock:
            try:
                _IN_PROCESS_LOCK.release()
            except RuntimeError:
                pass
            finally:
                self._acquired_thread_lock = False

        logger.debug(f"Released pipeline lock on {self.lock_file_path}")

    def __enter__(self) -> "PipelineRunLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    def is_locked(self) -> bool:
        """Checks if the lock is currently held by any process."""
        if _IN_PROCESS_LOCK.locked():
            return True
        if portalocker is None:
            return False

        try:
            lock_path = Path(self.lock_file_path)
            if not lock_path.exists():
                return False
            test_lock = portalocker.Lock(
                self.lock_file_path,
                mode="a+",
                flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
            )
            try:
                test_lock.acquire()
                test_lock.release()
                return False
            except Exception:
                return True
        except Exception:
            return False

    def get_lock_holder(self) -> Optional[Dict[str, Any]]:
        """Reads lock holder metadata and verifies whether the holding process is currently alive.

        Returns:
            Optional[Dict[str, Any]]: Metadata dict with 'pid', 'acquired_at', 'is_alive', or None.
        """
        try:
            lock_path = Path(self.lock_file_path)
            if not lock_path.exists():
                return None
            content = lock_path.read_text(encoding="utf-8").strip()
            if not content:
                return None
            data = json.loads(content)
            pid = data.get("pid")
            is_alive = False
            if pid:
                try:
                    import psutil
                    is_alive = psutil.pid_exists(pid)
                except ImportError:
                    is_alive = True
            data["is_alive"] = is_alive
            return data
        except Exception:
            return None

