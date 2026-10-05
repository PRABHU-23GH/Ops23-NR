"""
Ops23-NR — Autonomous Remediation Lambda Handler
Phase 6B / 6C / 6D

Security Guarantees:
1. Strictly allowlisted action: RESTART_OPS23_SERVICE
2. Strictly allowlisted target: i-066478e6fd6dc22af
3. Strictly allowlisted service: ops23-nr.service
4. Fixed, immutable shell command: systemctl restart ops23-nr.service
5. No arbitrary command execution (event['command'] is rejected)
6. Idempotency enforced via DynamoDB to prevent duplicate restarts
7. Structured audit logging without secret exposure
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

# Setup structured logger
logger = logging.getLogger("ops23.remediation")
logger.setLevel(logging.INFO)

# Strict Allowlist Constants
ALLOWED_ACTION = "RESTART_OPS23_SERVICE"
ALLOWED_TARGET = "i-066478e6fd6dc22af"
ALLOWED_SERVICE = "ops23-nr.service"
FIXED_SSM_DOCUMENT = "AWS-RunShellScript"
FIXED_COMMAND = ["systemctl restart ops23-nr.service"]
DEFAULT_REGION = "ap-south-1"
IDEMPOTENCY_TTL_SECONDS = 86400  # 24 hours


def get_environment_config() -> Dict[str, str]:
    return {
        "region": os.environ.get("AWS_REGION", DEFAULT_REGION),
        "table_name": os.environ.get(
            "IDEMPOTENCY_TABLE_NAME", "Ops23-NR-dev-remediation-idempotency"
        ),
        "auth_token": os.environ.get("WEBHOOK_AUTH_TOKEN", ""),
    }


def parse_event(event: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Parses event payload whether received via API Gateway HTTP proxy or direct Lambda invoke.
    Returns (payload_dict, auth_token_provided).
    """
    auth_header = None
    if "headers" in event and isinstance(event["headers"], dict):
        headers = {k.lower(): v for k, v in event["headers"].items()}
        auth_header = headers.get("x-webhook-token") or headers.get("authorization")

    # If invoked via API Gateway, body is typically a JSON string
    if "body" in event:
        body = event["body"]
        if isinstance(body, str):
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return {}, auth_header
        elif isinstance(body, dict):
            payload = body
        else:
            return {}, auth_header
    else:
        payload = event

    return payload, auth_header


def validate_request(payload: Dict[str, Any]) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """
    Validates that the payload conforms exactly to the remediation contract.
    Disallows arbitrary command execution.
    """
    if not isinstance(payload, dict) or not payload:
        return False, "Payload must be a non-empty JSON object", {}

    # Reject any attempt to supply arbitrary commands
    if "command" in payload or "commands" in payload:
        return False, "Arbitrary command execution is strictly forbidden", {}

    action = payload.get("action")
    target = payload.get("target")
    service = payload.get("service")

    # Identifiers (event_id and/or incident_id)
    event_id = payload.get("event_id") or payload.get("incident_id")
    incident_id = payload.get("incident_id") or payload.get("event_id")

    if not event_id or not str(event_id).strip():
        return False, "Missing required identifier: event_id or incident_id", {}

    event_id_str = str(event_id).strip()
    incident_id_str = str(incident_id).strip()

    if action != ALLOWED_ACTION:
        return False, f"Unsupported action: '{action}'. Allowed: '{ALLOWED_ACTION}'", {}

    if target != ALLOWED_TARGET:
        return False, f"Unauthorized target: '{target}'. Allowed: '{ALLOWED_TARGET}'", {}

    if service != ALLOWED_SERVICE:
        return False, f"Unauthorized service: '{service}'. Allowed: '{ALLOWED_SERVICE}'", {}

    contract = {
        "action": ALLOWED_ACTION,
        "target": ALLOWED_TARGET,
        "service": ALLOWED_SERVICE,
        "event_id": event_id_str,
        "incident_id": incident_id_str,
        "condition_name": payload.get("condition_name", "UnknownCondition"),
    }
    return True, None, contract


def check_and_record_idempotency(
    event_id: str,
    dynamodb_table: Any,
) -> bool:
    """
    Checks if event_id has already been processed.
    If not, atomically records it with a TTL.
    Returns True if event is NEW (safe to remediate).
    Returns False if event is a DUPLICATE (skip remediation).
    """
    now = int(time.time())
    ttl = now + IDEMPOTENCY_TTL_SECONDS

    try:
        # Atomic conditional write: put item only if event_id does NOT already exist
        dynamodb_table.put_item(
            Item={
                "event_id": event_id,
                "processed_at": now,
                "ttl": ttl,
                "status": "PROCESSING",
            },
            ConditionExpression="attribute_not_exists(event_id)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        # If DynamoDB fails for other reasons, log error and re-raise to prevent unverified execution
        logger.error(json.dumps({"error": "DynamoDB error", "code": e.response["Error"]["Code"]}))
        raise


def invoke_ssm_restart(
    target_instance: str,
    ssm_client: Any,
    wait_for_completion: bool = True,
    poll_timeout_seconds: int = 15,
) -> Dict[str, Any]:
    """
    Dispatches AWS-RunShellScript strictly to the allowlisted instance.
    Runs only the fixed command: systemctl restart ops23-nr.service.
    """
    response = ssm_client.send_command(
        InstanceIds=[target_instance],
        DocumentName=FIXED_SSM_DOCUMENT,
        Parameters={"commands": FIXED_COMMAND},
        Comment="Ops23-NR automated self-healing service restart",
        TimeoutSeconds=60,
    )

    command_id = response["Command"]["CommandId"]

    if not wait_for_completion:
        return {"command_id": command_id, "status": "Sent"}

    # Poll status
    deadline = time.time() + poll_timeout_seconds
    status = "Pending"
    status_details = ""
    exit_code = None

    while time.time() < deadline:
        try:
            invocation = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=target_instance,
            )
            status = invocation.get("Status", "Pending")
            status_details = invocation.get("StatusDetails", "")
            exit_code = invocation.get("ResponseCode", None)

            if status in ["Success", "Failed", "Cancelled", "TimedOut"]:
                break
        except ClientError as err:
            logger.warning(json.dumps({"warning": "SSM polling error", "detail": str(err)}))

        time.sleep(1)

    return {
        "command_id": command_id,
        "status": status,
        "status_details": status_details,
        "exit_code": exit_code,
    }


def lambda_handler(
    event: Dict[str, Any],
    context: Any = None,
    ssm_client: Any = None,
    dynamodb_resource: Any = None,
) -> Dict[str, Any]:
    """
    AWS Lambda handler entry point.
    """
    start_time = time.time()
    config = get_environment_config()

    # 1. Parse Event & Auth
    payload, provided_token = parse_event(event)

    # Validate Auth Token if configured
    expected_token = config["auth_token"]
    if expected_token and provided_token != expected_token:
        audit_log = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "UNAUTHORIZED",
            "message": "Invalid or missing webhook authentication token",
        }
        logger.warning(json.dumps(audit_log))
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Unauthorized"}),
        }

    # 2. Validate Request Contract
    is_valid, error_msg, contract = validate_request(payload)
    if not is_valid:
        audit_log = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "REJECTED",
            "reason": error_msg,
            "raw_payload_keys": list(payload.keys()) if isinstance(payload, dict) else [],
        }
        logger.warning(json.dumps(audit_log))
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": error_msg, "status": "REJECTED"}),
        }

    event_id = contract["event_id"]
    incident_id = contract["incident_id"]

    # 3. Idempotency Check
    if dynamodb_resource is None:
        dynamodb_resource = boto3.resource("dynamodb", region_name=config["region"])

    table = dynamodb_resource.Table(config["table_name"])

    try:
        is_new_event = check_and_record_idempotency(event_id, table)
    except Exception as e:
        logger.error(json.dumps({"error": "Idempotency store unavailable", "detail": str(e)}))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Internal state error", "status": "FAILED"}),
        }

    if not is_new_event:
        audit_log = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "incident_id": incident_id,
            "event_id": event_id,
            "action": contract["action"],
            "target": contract["target"],
            "service": contract["service"],
            "status": "SKIPPED",
            "reason": "DUPLICATE_EVENT_IGNORED",
        }
        logger.info(json.dumps(audit_log))
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "status": "SKIPPED",
                "reason": "DUPLICATE_EVENT_IGNORED",
                "event_id": event_id,
                "incident_id": incident_id,
            }),
        }

    # 4. Invoke SSM Run Command
    if ssm_client is None:
        ssm_client = boto3.client("ssm", region_name=config["region"])

    try:
        ssm_result = invoke_ssm_restart(
            target_instance=contract["target"],
            ssm_client=ssm_client,
            wait_for_completion=True,
            poll_timeout_seconds=20,
        )
    except Exception as e:
        audit_log = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "incident_id": incident_id,
            "event_id": event_id,
            "action": contract["action"],
            "target": contract["target"],
            "service": contract["service"],
            "status": "SSM_DISPATCH_FAILED",
            "error": str(e),
        }
        logger.error(json.dumps(audit_log))
        return {
            "statusCode": 502,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Failed to dispatch SSM command", "status": "FAILED"}),
        }

    duration_ms = round((time.time() - start_time) * 1000, 2)

    # 5. Audit Logging
    audit_log = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "incident_id": incident_id,
        "event_id": event_id,
        "condition_name": contract["condition_name"],
        "action": contract["action"],
        "target": contract["target"],
        "service": contract["service"],
        "ssm_command_id": ssm_result["command_id"],
        "ssm_result": ssm_result["status"],
        "exit_code": ssm_result.get("exit_code"),
        "duration_ms": duration_ms,
        "status": "REMEDIATION_EXECUTED",
    }
    logger.info(json.dumps(audit_log))

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "status": "SUCCESS",
            "action": contract["action"],
            "target": contract["target"],
            "service": contract["service"],
            "event_id": event_id,
            "incident_id": incident_id,
            "ssm_command_id": ssm_result["command_id"],
            "command_status": ssm_result["status"],
        }),
    }
