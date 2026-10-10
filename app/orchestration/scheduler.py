"""AWS EventBridge Scheduler and Lambda trigger coordination models."""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from app.core.config import settings


class EventBridgeScheduleConfig(BaseModel):
    """Configuration for AWS EventBridge Scheduler daily trigger."""

    schedule_name: str = Field(default="ai-newspaper-daily-publication", description="EventBridge schedule name")
    cron_expression: str = Field(default="cron(0 6 * * ? *)", description="Cron expression (06:00 AM daily)")
    timezone: str = Field(default="Asia/Kolkata", description="Target execution timezone")
    target_arn: str = Field(default="arn:aws:lambda:ap-south-1:123456789012:function:WorkerCoordinator", description="Target Lambda ARN")
    role_arn: str = Field(default="arn:aws:iam::123456789012:role/EventBridgeSchedulerRole", description="IAM execution role ARN")
    flexible_time_window_minutes: int = Field(default=15, description="Flexible time window in minutes")
    state: str = Field(default="ENABLED", description="Schedule state (ENABLED, DISABLED)")

    def to_boto3_params(self) -> Dict[str, Any]:
        """Converts config into boto3 create_schedule parameters."""
        return {
            "Name": self.schedule_name,
            "ScheduleExpression": self.cron_expression,
            "ScheduleExpressionTimezone": self.timezone,
            "FlexibleTimeWindow": {
                "Mode": "FLEXIBLE",
                "MaximumWindowInMinutes": self.flexible_time_window_minutes,
            },
            "Target": {
                "Arn": self.target_arn,
                "RoleArn": self.role_arn,
                "Input": "{\"action\": \"START_DAILY_WORKER\"}",
                "RetryPolicy": {
                    "MaximumRetryAttempts": 2,
                    "MaximumEventAgeInSeconds": 3600,
                },
            },
            "State": self.state,
        }
