"""Daily pipeline scheduler with timezone support, restart duplicate prevention, and graceful shutdown."""

from datetime import datetime, time as dt_time, timedelta
import logging
import threading
import time
from typing import Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings
from app.core.logging import setup_logger
from app.scheduler.lock import PipelineRunAlreadyActiveError
from app.scheduler.runner import DailyPipelineRunner
from app.storage.models import PipelineRunRecord
from app.storage.sqlite import SQLiteDatabase

logger = setup_logger("daily_scheduler")


class DailyScheduler:
    """Automates daily execution of news discovery pipeline at configured local time."""

    def __init__(
        self,
        runner: Optional[DailyPipelineRunner] = None,
        db: Optional[SQLiteDatabase] = None,
        schedule_time: Optional[str] = None,
        timezone_str: Optional[str] = None,
        run_on_startup: Optional[bool] = None,
    ):
        """Initializes scheduler.

        Args:
            runner: DailyPipelineRunner instance (or None to instantiate).
            db: SQLiteDatabase instance.
            schedule_time: Target run time in 'HH:MM' 24-hr format (e.g. '06:00').
            timezone_str: IANA timezone name (e.g. 'UTC', 'America/New_York', 'Asia/Kolkata').
            run_on_startup: If True, triggers execution immediately on startup if not already run today.
        """
        self.runner = runner or DailyPipelineRunner(db=db)
        self.db = db or (self.runner.db if self.runner else SQLiteDatabase())
        self.schedule_time_str = schedule_time or settings.schedule_time
        self.timezone_str = timezone_str or settings.schedule_timezone
        self.run_on_startup = (
            run_on_startup if run_on_startup is not None else settings.schedule_run_on_startup
        )

        self.tz = self._load_timezone(self.timezone_str)
        self.hour, self.minute = self._parse_schedule_time(self.schedule_time_str)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_running = False

    def _load_timezone(self, tz_name: str) -> ZoneInfo:
        """Loads ZoneInfo strictly, raising ValueError on invalid or empty timezone names."""
        if not tz_name or not isinstance(tz_name, str) or not tz_name.strip():
            raise ValueError(
                "Timezone cannot be empty. Must be a valid IANA timezone name (e.g. 'Asia/Kolkata', 'UTC')."
            )
        try:
            return ZoneInfo(tz_name.strip())
        except (ZoneInfoNotFoundError, Exception) as err:
            raise ValueError(
                f"Invalid timezone '{tz_name}'. Must be a valid IANA timezone name (e.g. 'Asia/Kolkata', 'UTC', 'America/New_York'). Error: {err}"
            )

    def _parse_schedule_time(self, time_str: str) -> Tuple[int, int]:
        """Parses 'HH:MM' string strictly into hour and minute integers."""
        if not time_str or not isinstance(time_str, str):
            raise ValueError(
                "Schedule time must be a non-empty string in 'HH:MM' format."
            )
        parts = time_str.strip().split(":")
        if len(parts) == 2:
            try:
                h = int(parts[0])
                m = int(parts[1])
                if 0 <= h <= 23 and 0 <= m <= 59:
                    return h, m
            except ValueError:
                pass
        raise ValueError(
            f"Invalid schedule_time '{time_str}'. Must be in 'HH:MM' 24-hour format between 00:00 and 23:59."
        )

    def get_current_time(self) -> datetime:
        """Returns the current timezone-aware datetime."""
        return datetime.now(self.tz)

    def has_run_completed_today(self, current_dt: Optional[datetime] = None) -> bool:
        """Checks if a scheduled pipeline run has already succeeded today in this timezone.

        Args:
            current_dt: Reference datetime (defaults to current time in scheduler timezone).

        Returns:
            bool: True if a run succeeded today, preventing duplicate execution.
        """
        now = current_dt or self.get_current_time()
        last_run = self.db.get_last_successful_run(trigger_type="SCHEDULED")
        if not last_run or not last_run.started_at:
            return False

        # Convert naive UTC started_at from DB into target timezone
        started_utc = last_run.started_at.replace(tzinfo=ZoneInfo("UTC"))
        started_local = started_utc.astimezone(self.tz)

        return started_local.date() == now.date()

    def calculate_next_run(
        self, now_dt: Optional[datetime] = None
    ) -> Tuple[datetime, float]:
        """Calculates the next target execution datetime and the delay in seconds.

        Preserves exact local wall-clock time (e.g. 06:00) across standard days and
        daylight-saving time (DST) transitions.

        Guarantees:
        - If today's target time has not yet passed and today's run has NOT completed, runs today at target time.
        - If today's run already completed (e.g. before app restart), schedules for tomorrow at target time.
        - If today's target time has already passed, schedules for tomorrow at target time.

        Args:
            now_dt: Optional reference datetime for deterministic testing.

        Returns:
            Tuple[datetime, float]: (next_run_datetime, delay_seconds)
        """
        now = now_dt or self.get_current_time()
        if now.tzinfo is None:
            now = now.replace(tzinfo=self.tz)

        # Exact calendar date representation to preserve wall-clock time across DST transitions
        target_today = datetime(
            now.year,
            now.month,
            now.day,
            self.hour,
            self.minute,
            0,
            0,
            tzinfo=self.tz,
        )

        today_already_ran = self.has_run_completed_today(now)

        if now < target_today and not today_already_ran:
            # Target time is later today and we haven't run today yet
            next_run = target_today
        else:
            # Target time today has passed, or we already ran today: schedule for tomorrow
            tomorrow_date = now.date() + timedelta(days=1)
            next_run = datetime(
                tomorrow_date.year,
                tomorrow_date.month,
                tomorrow_date.day,
                self.hour,
                self.minute,
                0,
                0,
                tzinfo=self.tz,
            )

        # Convert both to UTC to compute true physical elapsed seconds across DST changes
        utc_tz = ZoneInfo("UTC")
        delay = max(0.0, (next_run.astimezone(utc_tz) - now.astimezone(utc_tz)).total_seconds())
        return next_run, delay

    def trigger_now(self, trigger_type: str = "MANUAL") -> PipelineRunRecord:
        """Executes a single pipeline run immediately.

        Args:
            trigger_type: Execution trigger ('MANUAL' or 'SCHEDULED').

        Returns:
            PipelineRunRecord: Resulting run record.
        """
        logger.info(f"Triggering immediate pipeline run (type={trigger_type})...")
        return self.runner.run_pipeline(trigger_type=trigger_type)

    def start(self) -> None:
        """Starts the scheduler background daemon thread."""
        if self._is_running:
            logger.warning("Scheduler is already running.")
            return

        self._stop_event.clear()
        self._is_running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="DailySchedulerThread")
        self._thread.start()
        logger.info(
            f"DailyScheduler started in background (target time: {self.schedule_time_str} {self.timezone_str})."
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signals the scheduler thread to stop and waits for completion.

        Args:
            timeout: Maximum seconds to wait for background thread to exit.
        """
        if not self._is_running:
            return

        logger.info("Stopping DailyScheduler...")
        self._stop_event.set()
        self._is_running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("DailyScheduler thread did not terminate within timeout.")
            else:
                logger.info("DailyScheduler background thread stopped gracefully.")

    @property
    def is_running(self) -> bool:
        """Whether scheduler background loop is active."""
        return self._is_running

    def _run_loop(self) -> None:
        """Background thread loop calculating wait times and triggering runs."""
        # Clean up any orphaned RUNNING records from prior process crashes
        stale_count = self.db.cleanup_interrupted_runs()
        if stale_count > 0:
            logger.warning(f"Scheduler startup: marked {stale_count} orphaned RUNNING records as FAILED.")

        # Check run on startup option if configured
        if self.run_on_startup:
            if not self.has_run_completed_today():
                logger.info("Startup run configured and today's run not completed. Executing now...")
                try:
                    self.runner.run_pipeline(trigger_type="SCHEDULED", raise_on_overlap=False)
                except Exception as err:
                    logger.error(f"Error during startup run: {err}")
            else:
                logger.info("Startup run skipped: today's scheduled run already completed.")

        while not self._stop_event.is_set():
            next_run, delay = self.calculate_next_run()
            logger.info(
                f"Next scheduled pipeline run at {next_run.isoformat()} (in {delay:.1f}s / {delay/3600:.2f}h)"
            )

            # Wait in chunks or until stop event
            # Wake up every 60s or when stop_event is set
            stopped = self._stop_event.wait(timeout=delay)
            if stopped:
                logger.info("Scheduler loop received stop signal.")
                break

            # Trigger scheduled pipeline run
            logger.info(f"Triggering scheduled daily pipeline execution at {self.get_current_time().isoformat()}...")
            try:
                self.runner.run_pipeline(trigger_type="SCHEDULED", raise_on_overlap=False)
            except PipelineRunAlreadyActiveError as lock_err:
                logger.warning(f"Scheduled run skipped because another run is already active: {lock_err}")
            except Exception as err:
                logger.critical(f"Unhandled error in scheduled run: {err}", exc_info=True)

            # Brief pause to prevent immediate re-trigger if execution took under a second
            self._stop_event.wait(timeout=2.0)

        logger.info("Scheduler loop exited.")
