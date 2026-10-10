"""EC2 control plane manager for automated startup, idempotency, and controlled shutdown."""

import logging
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.core.logging import setup_logger

logger = setup_logger("ec2_controller")


class EC2WorkerController:
    """Coordinates start, stop, and status querying of the dedicated GPU worker instance."""

    def __init__(
        self,
        instance_id: Optional[str] = None,
        region: Optional[str] = None,
        ec2_client: Optional[Any] = None,
    ):
        """Initializes controller.

        Args:
            instance_id: Target EC2 instance ID (defaults to settings.ec2_instance_id).
            region: AWS Region (defaults to settings.aws_region or 'ap-south-1').
            ec2_client: Optional injected boto3 EC2 client or mock.
        """
        self.instance_id = instance_id or getattr(settings, "ec2_instance_id", None)
        self.region = region or getattr(settings, "aws_region", "ap-south-1")
        self._client = ec2_client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        import boto3
        self._client = boto3.client("ec2", region_name=self.region)
        return self._client

    def get_instance_state(self, instance_id: Optional[str] = None) -> str:
        """Retrieves current EC2 lifecycle state (e.g. 'stopped', 'running', 'pending', 'stopping')."""
        target_id = instance_id or self.instance_id
        if not target_id:
            return "unknown"

        try:
            client = self._get_client()
            resp = client.describe_instances(InstanceIds=[target_id])
            reservations = resp.get("Reservations", [])
            if not reservations or not reservations[0].get("Instances"):
                return "not_found"
            state = reservations[0]["Instances"][0]["State"]["Name"]
            return state.lower()
        except Exception as err:
            logger.error(f"Failed to query EC2 state for '{target_id}': {err}")
            return "error"

    def start_worker(self, instance_id: Optional[str] = None) -> Tuple[bool, str]:
        """Starts worker instance idempotently.

        Guarantees:
        - If instance is 'stopped', triggers start.
        - If instance is already 'running' or 'pending', returns success immediately without duplicate start.
        - If instance is 'stopping', returns failure/wait notice.

        Returns:
            Tuple[bool, str]: (success, status_description)
        """
        target_id = instance_id or self.instance_id
        if not target_id:
            return False, "No EC2 instance ID configured."

        current_state = self.get_instance_state(target_id)
        logger.info(f"EC2 Worker '{target_id}' state before start: {current_state}")

        if current_state in ("running", "pending"):
            return True, f"Worker '{target_id}' is already {current_state} (idempotent)."

        if current_state == "stopping":
            return False, f"Worker '{target_id}' is currently stopping. Wait before restarting."

        try:
            client = self._get_client()
            client.start_instances(InstanceIds=[target_id])
            logger.info(f"Triggered start for EC2 worker '{target_id}'.")
            return True, f"Worker '{target_id}' start initiated."
        except Exception as err:
            err_msg = f"Failed to start EC2 worker '{target_id}': {err}"
            logger.error(err_msg)
            return False, err_msg

    def stop_worker(
        self,
        instance_id: Optional[str] = None,
        hibernate: bool = False,
    ) -> Tuple[bool, str]:
        """Initiates controlled shutdown of the worker instance.

        Returns:
            Tuple[bool, str]: (success, message)
        """
        target_id = instance_id or self.instance_id
        if not target_id:
            return False, "No EC2 instance ID configured."

        current_state = self.get_instance_state(target_id)
        if current_state in ("stopped", "stopping"):
            return True, f"Worker '{target_id}' is already {current_state}."

        try:
            client = self._get_client()
            client.stop_instances(InstanceIds=[target_id], Hibernate=hibernate)
            logger.info(f"Triggered controlled shutdown for EC2 worker '{target_id}'.")
            return True, f"Worker '{target_id}' stop initiated."
        except Exception as err:
            err_msg = f"Failed to stop EC2 worker '{target_id}': {err}"
            logger.error(err_msg)
            return False, err_msg
