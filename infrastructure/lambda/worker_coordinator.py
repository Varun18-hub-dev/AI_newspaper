"""AWS Lambda Worker Coordinator.

Triggered by EventBridge Scheduler daily at 06:00 IST (Asia/Kolkata).
Idempotently starts the dedicated EC2 GPU worker and provides watchdog safety monitoring.
"""

import json
import logging
import os
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

EC2_INSTANCE_ID = os.environ.get("EC2_INSTANCE_ID")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
NOTIFICATION_SNS_ARN = os.environ.get("NOTIFICATION_SNS_ARN")


def lambda_handler(event, context):
    """EventBridge trigger entry point."""
    logger.info(f"Received EventBridge trigger event: {json.dumps(event)}")

    if not EC2_INSTANCE_ID:
        err_msg = "EC2_INSTANCE_ID environment variable is missing."
        logger.error(err_msg)
        return {"statusCode": 500, "body": json.dumps({"error": err_msg})}

    ec2 = boto3.client("ec2", region_name=AWS_REGION)

    try:
        # 1. Query current instance state
        resp = ec2.describe_instances(InstanceIds=[EC2_INSTANCE_ID])
        reservations = resp.get("Reservations", [])
        if not reservations or not reservations[0].get("Instances"):
            err_msg = f"EC2 instance '{EC2_INSTANCE_ID}' not found."
            logger.error(err_msg)
            return {"statusCode": 404, "body": json.dumps({"error": err_msg})}

        state = reservations[0]["Instances"][0]["State"]["Name"]
        logger.info(f"Current worker state: {state}")

        # 2. Idempotent check
        if state in ("running", "pending"):
            logger.info(f"Worker '{EC2_INSTANCE_ID}' is already {state}. Ignoring duplicate trigger.")
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "status": "ALREADY_ACTIVE",
                    "instance_id": EC2_INSTANCE_ID,
                    "state": state,
                }),
            }

        if state == "stopping":
            logger.warning(f"Worker '{EC2_INSTANCE_ID}' is currently stopping. Delaying restart.")
            return {
                "statusCode": 409,
                "body": json.dumps({
                    "status": "STOPPING_WAIT",
                    "instance_id": EC2_INSTANCE_ID,
                }),
            }

        # 3. Start worker instance
        ec2.start_instances(InstanceIds=[EC2_INSTANCE_ID])
        logger.info(f"Successfully initiated start for worker '{EC2_INSTANCE_ID}'.")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "START_INITIATED",
                "instance_id": EC2_INSTANCE_ID,
            }),
        }

    except Exception as err:
        logger.error(f"Failed to coordinate EC2 startup: {err}", exc_info=True)
        if NOTIFICATION_SNS_ARN:
            try:
                sns = boto3.client("sns", region_name=AWS_REGION)
                sns.publish(
                    TopicArn=NOTIFICATION_SNS_ARN,
                    Subject="[ALERT] AI Newspaper GPU Worker Startup Failed",
                    Message=f"Failed to start EC2 worker {EC2_INSTANCE_ID}: {str(err)}",
                )
            except Exception as notify_err:
                logger.error(f"Failed to send SNS alert: {notify_err}")

        return {"statusCode": 500, "body": json.dumps({"error": str(err)})}
