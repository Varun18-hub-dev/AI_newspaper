"""Watchdog monitor enforcing execution time budgets and preventing stuck worker instances."""

from datetime import datetime
import logging
import time
from typing import Optional, Tuple

from app.core.config import settings
from app.core.logging import setup_logger

logger = setup_logger("worker_watchdog")


class WorkerWatchdog:
    """Monitors worker execution duration against soft performance targets and hard safety limits."""

    def __init__(
        self,
        target_runtime_minutes: Optional[float] = None,
        max_runtime_minutes: Optional[float] = None,
        grace_period_seconds: Optional[float] = None,
    ):
        """Initializes the watchdog.

        Args:
            target_runtime_minutes: Soft performance objective (default: 20 min).
            max_runtime_minutes: Hard termination safety limit (default: 30 min).
            grace_period_seconds: Shutdown grace period before forced termination (default: 120s).
        """
        self.target_runtime_seconds = (
            (target_runtime_minutes if target_runtime_minutes is not None else getattr(settings, "target_runtime_minutes", 20.0)) * 60.0
        )
        self.max_runtime_seconds = (
            (max_runtime_minutes if max_runtime_minutes is not None else getattr(settings, "max_worker_runtime_minutes", 30.0)) * 60.0
        )
        self.grace_period_seconds = (
            grace_period_seconds if grace_period_seconds is not None else getattr(settings, "shutdown_grace_period_seconds", 120.0)
        )
        self.start_time: Optional[float] = None
        self._target_warning_logged = False

    def start(self) -> None:
        """Starts the watchdog timer."""
        self.start_time = time.time()
        self._target_warning_logged = False
        logger.info(
            f"Watchdog started: Target={self.target_runtime_seconds / 60:.1f}m, "
            f"Hard Limit={self.max_runtime_seconds / 60:.1f}m, "
            f"Grace Period={self.grace_period_seconds:.0f}s"
        )

    def elapsed_seconds(self) -> float:
        """Returns elapsed wall-clock seconds since start."""
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time

    def check(self) -> Tuple[bool, bool, Optional[str]]:
        """Checks current runtime against limits.

        Returns:
            Tuple[bool, bool, Optional[str]]:
                - is_expired (True if hard limit exceeded)
                - is_warning (True if soft target exceeded)
                - message (Explanation if soft or hard limit exceeded)
        """
        if self.start_time is None:
            return False, False, None

        elapsed = self.elapsed_seconds()

        # 1. Hard safety limit check
        if elapsed >= self.max_runtime_seconds:
            msg = (
                f"Worker exceeded maximum runtime limit of {self.max_runtime_seconds / 60:.1f} minutes "
                f"(elapsed: {elapsed / 60:.1f} minutes). Watchdog triggering emergency termination."
            )
            logger.error(msg)
            return True, True, msg

        # 2. Soft performance target check
        if elapsed >= self.target_runtime_seconds:
            msg = (
                f"Worker exceeded soft performance target of {self.target_runtime_seconds / 60:.1f} minutes "
                f"(elapsed: {elapsed / 60:.1f} minutes). Proceeding within safety budget."
            )
            if not self._target_warning_logged:
                logger.warning(msg)
                self._target_warning_logged = True
            return False, True, msg

        return False, False, None
