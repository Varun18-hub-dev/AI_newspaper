"""Worker lifecycle states and execution tracking for daily GPU compute orchestration."""

from datetime import datetime
from enum import Enum
import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.logging import setup_logger

logger = setup_logger("worker_lifecycle")


class WorkerState(str, Enum):
    """Explicit lifecycle states for the daily GPU worker."""

    STARTING = "STARTING"
    READY = "READY"
    RUNNING = "RUNNING"
    PUBLISHING = "PUBLISHING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class LifecycleTransition(BaseModel):
    """Individual state transition event with timestamp and context."""

    from_state: WorkerState
    to_state: WorkerState
    timestamp: str
    message: Optional[str] = None


class WorkerRunContext(BaseModel):
    """Context and telemetry of an active or completed daily worker run."""

    run_id: str
    edition_id: str
    current_state: WorkerState = WorkerState.STARTING
    started_at: str
    ready_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    transitions: List[LifecycleTransition] = Field(default_factory=list)
    error_message: Optional[str] = None
    telemetry: Dict[str, Any] = Field(default_factory=dict)


class LifecycleManager:
    """Manages worker state transitions, validates state machine rules, and logs telemetry."""

    # Valid state transition graph
    VALID_TRANSITIONS = {
        WorkerState.STARTING: {WorkerState.READY, WorkerState.FAILED, WorkerState.STOPPING},
        WorkerState.READY: {WorkerState.RUNNING, WorkerState.FAILED, WorkerState.STOPPING},
        WorkerState.RUNNING: {WorkerState.PUBLISHING, WorkerState.PARTIAL_SUCCESS, WorkerState.FAILED, WorkerState.STOPPING},
        WorkerState.PUBLISHING: {WorkerState.SUCCESS, WorkerState.PARTIAL_SUCCESS, WorkerState.FAILED},
        WorkerState.SUCCESS: {WorkerState.STOPPING},
        WorkerState.PARTIAL_SUCCESS: {WorkerState.STOPPING},
        WorkerState.FAILED: {WorkerState.STOPPING},
        WorkerState.STOPPING: {WorkerState.STOPPED},
        WorkerState.STOPPED: set(),
    }

    def __init__(self, run_id: str, edition_id: str):
        now_iso = datetime.utcnow().isoformat()
        self.context = WorkerRunContext(
            run_id=run_id,
            edition_id=edition_id,
            current_state=WorkerState.STARTING,
            started_at=now_iso,
        )

    def transition_to(
        self,
        new_state: WorkerState,
        message: Optional[str] = None,
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Transitions worker to a new lifecycle state.

        Args:
            new_state: Target WorkerState.
            message: Optional status or error message.
            telemetry: Optional telemetry dictionary to merge.

        Returns:
            bool: True if transition succeeded, False if disallowed.
        """
        current = self.context.current_state
        allowed = self.VALID_TRANSITIONS.get(current, set())

        if new_state not in allowed:
            logger.warning(
                f"Invalid lifecycle transition attempted: {current.value} -> {new_state.value}"
            )
            return False

        now = datetime.utcnow()
        now_iso = now.isoformat()

        # Record transition
        self.context.transitions.append(
            LifecycleTransition(
                from_state=current,
                to_state=new_state,
                timestamp=now_iso,
                message=message,
            )
        )

        self.context.current_state = new_state

        if new_state == WorkerState.READY:
            self.context.ready_at = now_iso
        elif new_state in (WorkerState.SUCCESS, WorkerState.PARTIAL_SUCCESS, WorkerState.FAILED):
            self.context.completed_at = now_iso
            started_dt = datetime.fromisoformat(self.context.started_at)
            self.context.duration_seconds = round((now - started_dt).total_seconds(), 2)

        if message and new_state == WorkerState.FAILED:
            self.context.error_message = message

        if telemetry:
            self.context.telemetry.update(telemetry)

        logger.info(
            f"Worker [{self.context.run_id}] state transition: "
            f"{current.value} -> {new_state.value} ({message or ''})"
        )
        return True

    def is_terminal(self) -> bool:
        """Checks if current state is terminal (SUCCESS, PARTIAL_SUCCESS, or FAILED)."""
        return self.context.current_state in (
            WorkerState.SUCCESS,
            WorkerState.PARTIAL_SUCCESS,
            WorkerState.FAILED,
            WorkerState.STOPPED,
        )
