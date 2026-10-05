"""
Unit tests for Ops23-NR Lambda Remediation Handler
Phase 6B Test Suite

Tests:
1. Valid remediation request
2. Invalid action
3. Invalid instance
4. Invalid service
5. Missing event ID / incident ID
6. Malformed event payload
7. Arbitrary command rejection
8. SSM failure handling
9. Duplicate event idempotency
10. Webhook authentication token handling
"""

import json
from unittest.mock import MagicMock
import pytest
from botocore.exceptions import ClientError

import importlib

remediation_module = importlib.import_module("remediation.lambda.handler")
ALLOWED_ACTION = remediation_module.ALLOWED_ACTION
ALLOWED_SERVICE = remediation_module.ALLOWED_SERVICE
ALLOWED_TARGET = remediation_module.ALLOWED_TARGET
lambda_handler = remediation_module.lambda_handler
validate_request = remediation_module.validate_request



@pytest.fixture
def mock_ssm():
    client = MagicMock()
    client.send_command.return_value = {
        "Command": {
            "CommandId": "cmd-test-12345678",
            "Status": "InProgress",
        }
    }
    client.get_command_invocation.return_value = {
        "Status": "Success",
        "StatusDetails": "Success",
        "ResponseCode": 0,
    }
    return client


@pytest.fixture
def mock_dynamodb():
    resource = MagicMock()
    table = MagicMock()
    resource.Table.return_value = table
    # Default: first put_item succeeds (new event)
    table.put_item.return_value = {}
    return resource


def test_valid_remediation_request(mock_ssm, mock_dynamodb):
    event = {
        "action": ALLOWED_ACTION,
        "target": ALLOWED_TARGET,
        "service": ALLOWED_SERVICE,
        "event_id": "evt-001",
        "incident_id": "inc-001",
        "condition_name": "Service Availability Degradation",
    }
    response = lambda_handler(event, ssm_client=mock_ssm, dynamodb_resource=mock_dynamodb)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "SUCCESS"
    assert body["action"] == ALLOWED_ACTION
    assert body["target"] == ALLOWED_TARGET
    assert body["service"] == ALLOWED_SERVICE
    assert body["ssm_command_id"] == "cmd-test-12345678"
    assert body["command_status"] == "Success"

    # Verify SSM parameters: verify command is strictly fixed
    mock_ssm.send_command.assert_called_once_with(
        InstanceIds=[ALLOWED_TARGET],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": ["systemctl restart ops23-nr.service"]},
        Comment="Ops23-NR automated self-healing service restart",
        TimeoutSeconds=60,
    )


def test_invalid_action(mock_ssm, mock_dynamodb):
    event = {
        "action": "REBOOT_MACHINE",
        "target": ALLOWED_TARGET,
        "service": ALLOWED_SERVICE,
        "event_id": "evt-002",
    }
    response = lambda_handler(event, ssm_client=mock_ssm, dynamodb_resource=mock_dynamodb)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["status"] == "REJECTED"
    assert "Unsupported action" in body["error"]
    mock_ssm.send_command.assert_not_called()


def test_invalid_instance(mock_ssm, mock_dynamodb):
    event = {
        "action": ALLOWED_ACTION,
        "target": "i-99999999999999999",
        "service": ALLOWED_SERVICE,
        "event_id": "evt-003",
    }
    response = lambda_handler(event, ssm_client=mock_ssm, dynamodb_resource=mock_dynamodb)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["status"] == "REJECTED"
    assert "Unauthorized target" in body["error"]
    mock_ssm.send_command.assert_not_called()


def test_invalid_service(mock_ssm, mock_dynamodb):
    event = {
        "action": ALLOWED_ACTION,
        "target": ALLOWED_TARGET,
        "service": "nginx.service",
        "event_id": "evt-004",
    }
    response = lambda_handler(event, ssm_client=mock_ssm, dynamodb_resource=mock_dynamodb)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["status"] == "REJECTED"
    assert "Unauthorized service" in body["error"]
    mock_ssm.send_command.assert_not_called()


def test_missing_event_id(mock_ssm, mock_dynamodb):
    event = {
        "action": ALLOWED_ACTION,
        "target": ALLOWED_TARGET,
        "service": ALLOWED_SERVICE,
    }
    response = lambda_handler(event, ssm_client=mock_ssm, dynamodb_resource=mock_dynamodb)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["status"] == "REJECTED"
    assert "Missing required identifier" in body["error"]
    mock_ssm.send_command.assert_not_called()


def test_malformed_event_json(mock_ssm, mock_dynamodb):
    event = {
        "body": "not-valid-json{"
    }
    response = lambda_handler(event, ssm_client=mock_ssm, dynamodb_resource=mock_dynamodb)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["status"] == "REJECTED"
    mock_ssm.send_command.assert_not_called()


def test_arbitrary_command_rejected(mock_ssm, mock_dynamodb):
    event = {
        "action": ALLOWED_ACTION,
        "target": ALLOWED_TARGET,
        "service": ALLOWED_SERVICE,
        "event_id": "evt-exploit",
        "command": "rm -rf /",
    }
    response = lambda_handler(event, ssm_client=mock_ssm, dynamodb_resource=mock_dynamodb)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["status"] == "REJECTED"
    assert "Arbitrary command execution is strictly forbidden" in body["error"]
    mock_ssm.send_command.assert_not_called()


def test_duplicate_event_idempotency(mock_ssm, mock_dynamodb):
    # Simulate conditional check failure in DynamoDB
    table = mock_dynamodb.Table.return_value
    table.put_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "The conditional request failed"}},
        "PutItem",
    )

    event = {
        "action": ALLOWED_ACTION,
        "target": ALLOWED_TARGET,
        "service": ALLOWED_SERVICE,
        "event_id": "evt-dup-001",
        "incident_id": "inc-dup-001",
    }
    response = lambda_handler(event, ssm_client=mock_ssm, dynamodb_resource=mock_dynamodb)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "SKIPPED"
    assert body["reason"] == "DUPLICATE_EVENT_IGNORED"
    mock_ssm.send_command.assert_not_called()


def test_ssm_failure_handling(mock_ssm, mock_dynamodb):
    mock_ssm.send_command.side_effect = RuntimeError("SSM service throttled")
    event = {
        "action": ALLOWED_ACTION,
        "target": ALLOWED_TARGET,
        "service": ALLOWED_SERVICE,
        "event_id": "evt-ssm-fail",
        "incident_id": "inc-ssm-fail",
    }
    response = lambda_handler(event, ssm_client=mock_ssm, dynamodb_resource=mock_dynamodb)
    assert response["statusCode"] == 502
    body = json.loads(response["body"])
    assert body["status"] == "FAILED"


def test_api_gateway_payload_wrapper(mock_ssm, mock_dynamodb):
    inner_payload = {
        "action": ALLOWED_ACTION,
        "target": ALLOWED_TARGET,
        "service": ALLOWED_SERVICE,
        "event_id": "evt-apigw-01",
        "incident_id": "inc-apigw-01",
    }
    event = {
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(inner_payload),
    }
    response = lambda_handler(event, ssm_client=mock_ssm, dynamodb_resource=mock_dynamodb)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "SUCCESS"
    assert body["ssm_command_id"] == "cmd-test-12345678"


def test_unauthorized_token_rejection(monkeypatch, mock_ssm, mock_dynamodb):
    monkeypatch.setenv("WEBHOOK_AUTH_TOKEN", "super-secret-token")
    event = {
        "headers": {"x-webhook-token": "wrong-token"},
        "body": json.dumps({
            "action": ALLOWED_ACTION,
            "target": ALLOWED_TARGET,
            "service": ALLOWED_SERVICE,
            "event_id": "evt-auth-fail",
        }),
    }
    response = lambda_handler(event, ssm_client=mock_ssm, dynamodb_resource=mock_dynamodb)
    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["error"] == "Unauthorized"
    mock_ssm.send_command.assert_not_called()
