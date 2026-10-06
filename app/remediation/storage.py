"""Storage abstraction for Remediation Approvals in DynamoDB.

Phase 8: Atomic conditional writes, state consistency, and replay protection.
"""

from decimal import Decimal
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from app.config import get_settings
from app.remediation.models import ApprovalRecord, ApprovalStatus, ExecutionStatus

logger = logging.getLogger("ops23.remediation.storage")


def _to_dynamodb_dict(record: ApprovalRecord) -> Dict[str, Any]:
    """Converts ApprovalRecord into DynamoDB-compatible dictionary, converting floats to Decimal."""
    data = record.model_dump()
    if "confidence" in data and isinstance(data["confidence"], (float, int)):
        data["confidence"] = Decimal(str(data["confidence"]))
    return data


def _from_dynamodb_dict(item: Dict[str, Any]) -> ApprovalRecord:
    """Converts DynamoDB item back into ApprovalRecord, casting Decimals to float/int."""
    parsed = {}
    for k, v in item.items():
        if isinstance(v, Decimal):
            if v % 1 == 0:
                parsed[k] = int(v)
            else:
                parsed[k] = float(v)
        else:
            parsed[k] = v
    return ApprovalRecord.model_validate(parsed)


class ApprovalStorage:
    """DynamoDB repository for persistent remediation approval state."""

    def __init__(
        self,
        table_name: Optional[str] = None,
        region_name: Optional[str] = None,
        dynamodb_resource: Any = None,
    ):
        settings = get_settings()
        self.table_name = table_name or settings.REMEDIATION_APPROVAL_TABLE_NAME
        self.region_name = region_name or getattr(settings, "AWS_REGION", "ap-south-1")
        self._dynamodb_resource = dynamodb_resource
        self._table = None

    @property
    def table(self) -> Any:
        if self._table is None:
            if self._dynamodb_resource is None:
                self._dynamodb_resource = boto3.resource("dynamodb", region_name=self.region_name)
            self._table = self._dynamodb_resource.Table(self.table_name)
        return self._table

    def save_approval(self, record: ApprovalRecord) -> bool:
        """Atomically saves a new approval record with condition attribute_not_exists(approval_id)."""
        item = _to_dynamodb_dict(record)
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(approval_id)",
            )
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.warning(f"Approval ID {record.approval_id} already exists.")
                return False
            logger.error(f"Failed to save approval record {record.approval_id}: {e}")
            raise

    def get_approval(self, approval_id: str) -> Optional[ApprovalRecord]:
        """Retrieves an approval record by its ID."""
        try:
            response = self.table.get_item(Key={"approval_id": approval_id})
            item = response.get("Item")
            if not item:
                return None
            return _from_dynamodb_dict(item)
        except ClientError as e:
            logger.error(f"Failed to get approval {approval_id}: {e}")
            raise

    def transition_to_approved(
        self,
        approval_id: str,
        approved_by: str,
        approved_at: str,
    ) -> Tuple[bool, Optional[ApprovalRecord], Optional[str]]:
        """Atomically transitions status from PENDING to APPROVED."""
        try:
            response = self.table.update_item(
                Key={"approval_id": approval_id},
                UpdateExpression="SET approval_status = :approved, approved_by = :approver, approved_at = :approved_at",
                ConditionExpression="attribute_exists(approval_id) AND approval_status = :pending",
                ExpressionAttributeValues={
                    ":approved": ApprovalStatus.APPROVED.value,
                    ":approver": approved_by,
                    ":approved_at": approved_at,
                    ":pending": ApprovalStatus.PENDING.value,
                },
                ReturnValues="ALL_NEW",
            )
            updated_record = _from_dynamodb_dict(response["Attributes"])
            return True, updated_record, None
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ConditionalCheckFailedException":
                # Check current state to see if already approved (idempotency) or in illegal state
                current = self.get_approval(approval_id)
                if not current:
                    return False, None, f"Approval '{approval_id}' not found."
                if current.approval_status == ApprovalStatus.APPROVED:
                    return True, current, "Already approved"
                return False, current, f"Cannot approve: Current state is {current.approval_status.value}."
            return False, None, str(e)

    def transition_to_rejected(
        self,
        approval_id: str,
        rejected_by: str,
        rejected_at: str,
        reason: str,
    ) -> Tuple[bool, Optional[ApprovalRecord], Optional[str]]:
        """Atomically transitions status from PENDING to REJECTED."""
        try:
            response = self.table.update_item(
                Key={"approval_id": approval_id},
                UpdateExpression="SET approval_status = :rejected, rejected_by = :rejector, rejected_at = :rejected_at, rejection_reason = :reason",
                ConditionExpression="attribute_exists(approval_id) AND approval_status = :pending",
                ExpressionAttributeValues={
                    ":rejected": ApprovalStatus.REJECTED.value,
                    ":rejector": rejected_by,
                    ":rejected_at": rejected_at,
                    ":reason": reason,
                    ":pending": ApprovalStatus.PENDING.value,
                },
                ReturnValues="ALL_NEW",
            )
            updated_record = _from_dynamodb_dict(response["Attributes"])
            return True, updated_record, None
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ConditionalCheckFailedException":
                current = self.get_approval(approval_id)
                if not current:
                    return False, None, f"Approval '{approval_id}' not found."
                return False, current, f"Cannot reject: Current state is {current.approval_status.value}."
            return False, None, str(e)

    def transition_to_executing(
        self,
        approval_id: str,
        execution_started_at: Optional[str] = None,
    ) -> Tuple[bool, Optional[ApprovalRecord], Optional[str]]:
        """Atomically locks the approval record from APPROVED to EXECUTING to prevent concurrent execution."""
        started_iso = execution_started_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            response = self.table.update_item(
                Key={"approval_id": approval_id},
                UpdateExpression="SET approval_status = :executing, execution_status = :executing_status, execution_started_at = :started_at",
                ConditionExpression="attribute_exists(approval_id) AND approval_status = :approved",
                ExpressionAttributeValues={
                    ":executing": ApprovalStatus.EXECUTING.value,
                    ":executing_status": ExecutionStatus.EXECUTING.value,
                    ":started_at": started_iso,
                    ":approved": ApprovalStatus.APPROVED.value,
                },
                ReturnValues="ALL_NEW",
            )
            updated_record = _from_dynamodb_dict(response["Attributes"])
            return True, updated_record, None
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ConditionalCheckFailedException":
                current = self.get_approval(approval_id)
                if not current:
                    return False, None, f"Approval '{approval_id}' not found."
                return False, current, f"Cannot execute: Approval status is {current.approval_status.value} (expected APPROVED)."
            return False, None, str(e)

    def transition_to_executed(
        self,
        approval_id: str,
        execution_result: Dict[str, Any],
        ssm_command_id: Optional[str] = None,
        execution_completed_at: Optional[str] = None,
    ) -> Tuple[bool, Optional[ApprovalRecord], Optional[str]]:
        """Transitions state from EXECUTING to EXECUTED upon Lambda success."""
        completed_iso = execution_completed_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            response = self.table.update_item(
                Key={"approval_id": approval_id},
                UpdateExpression="SET approval_status = :executed, execution_status = :executed_status, execution_result = :res, ssm_command_id = :cmd_id, execution_completed_at = :completed_at",
                ConditionExpression="attribute_exists(approval_id) AND approval_status = :executing",
                ExpressionAttributeValues={
                    ":executed": ApprovalStatus.EXECUTED.value,
                    ":executed_status": ExecutionStatus.EXECUTED.value,
                    ":res": execution_result,
                    ":cmd_id": ssm_command_id or "NONE",
                    ":completed_at": completed_iso,
                    ":executing": ApprovalStatus.EXECUTING.value,
                },
                ReturnValues="ALL_NEW",
            )
            updated_record = _from_dynamodb_dict(response["Attributes"])
            return True, updated_record, None
        except ClientError as e:
            logger.error(f"Failed to record executed status for {approval_id}: {e}")
            return False, None, str(e)

    def transition_to_execution_failed(
        self,
        approval_id: str,
        error_message: str,
        execution_result: Optional[Dict[str, Any]] = None,
        execution_completed_at: Optional[str] = None,
    ) -> Tuple[bool, Optional[ApprovalRecord], Optional[str]]:
        """Transitions state from EXECUTING to EXECUTION_FAILED upon Lambda or SSM failure."""
        completed_iso = execution_completed_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            response = self.table.update_item(
                Key={"approval_id": approval_id},
                UpdateExpression="SET approval_status = :failed, execution_status = :failed_status, error_message = :err, execution_result = :res, execution_completed_at = :completed_at",
                ConditionExpression="attribute_exists(approval_id) AND approval_status = :executing",
                ExpressionAttributeValues={
                    ":failed": ApprovalStatus.EXECUTION_FAILED.value,
                    ":failed_status": ExecutionStatus.EXECUTION_FAILED.value,
                    ":err": error_message,
                    ":res": execution_result or {},
                    ":completed_at": completed_iso,
                    ":executing": ApprovalStatus.EXECUTING.value,
                },
                ReturnValues="ALL_NEW",
            )
            updated_record = _from_dynamodb_dict(response["Attributes"])
            return True, updated_record, None
        except ClientError as e:
            logger.error(f"Failed to record execution failure for {approval_id}: {e}")
            return False, None, str(e)

    def transition_to_reconciled_executed(
        self,
        approval_id: str,
        ssm_command_id: str,
        execution_result: Dict[str, Any],
        reconciled_by: str,
        reconciled_at: str,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[ApprovalRecord], Optional[str]]:
        """Atomically transitions state from EXECUTING to EXECUTED via post-remediation reconciliation."""
        try:
            response = self.table.update_item(
                Key={"approval_id": approval_id},
                UpdateExpression=(
                    "SET approval_status = :executed, execution_status = :executed_status, "
                    "ssm_command_id = :cmd_id, execution_result = :res, "
                    "execution_completed_at = :completed_at, reconciled_at = :rec_at, "
                    "reconciled_by = :rec_by, reconciliation_evidence = :ev"
                ),
                ConditionExpression="attribute_exists(approval_id) AND approval_status = :executing",
                ExpressionAttributeValues={
                    ":executed": ApprovalStatus.EXECUTED.value,
                    ":executed_status": ExecutionStatus.EXECUTED.value,
                    ":cmd_id": ssm_command_id,
                    ":res": execution_result,
                    ":completed_at": reconciled_at,
                    ":rec_at": reconciled_at,
                    ":rec_by": reconciled_by,
                    ":ev": evidence or {},
                    ":executing": ApprovalStatus.EXECUTING.value,
                },
                ReturnValues="ALL_NEW",
            )
            updated_record = _from_dynamodb_dict(response["Attributes"])
            return True, updated_record, None
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ConditionalCheckFailedException":
                current = self.get_approval(approval_id)
                if not current:
                    return False, None, f"Approval '{approval_id}' not found."
                if current.approval_status == ApprovalStatus.EXECUTED:
                    return True, current, "Already reconciled as EXECUTED"
                return False, current, f"Cannot reconcile: Current state is {current.approval_status.value}."
            logger.error(f"Failed to record reconciled executed status for {approval_id}: {e}")
            return False, None, str(e)

    def transition_to_reconciled_failed(
        self,
        approval_id: str,
        error_message: str,
        reconciled_by: str,
        reconciled_at: str,
        ssm_command_id: Optional[str] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[ApprovalRecord], Optional[str]]:
        """Atomically transitions state from EXECUTING to EXECUTION_FAILED via post-remediation reconciliation."""
        try:
            response = self.table.update_item(
                Key={"approval_id": approval_id},
                UpdateExpression=(
                    "SET approval_status = :failed, execution_status = :failed_status, "
                    "error_message = :err, ssm_command_id = :cmd_id, "
                    "reconciled_at = :rec_at, reconciled_by = :rec_by, "
                    "reconciliation_evidence = :ev, execution_completed_at = :completed_at"
                ),
                ConditionExpression="attribute_exists(approval_id) AND approval_status = :executing",
                ExpressionAttributeValues={
                    ":failed": ApprovalStatus.EXECUTION_FAILED.value,
                    ":failed_status": ExecutionStatus.EXECUTION_FAILED.value,
                    ":err": error_message,
                    ":cmd_id": ssm_command_id or "NONE",
                    ":completed_at": reconciled_at,
                    ":rec_at": reconciled_at,
                    ":rec_by": reconciled_by,
                    ":ev": evidence or {},
                    ":executing": ApprovalStatus.EXECUTING.value,
                },
                ReturnValues="ALL_NEW",
            )
            updated_record = _from_dynamodb_dict(response["Attributes"])
            return True, updated_record, None
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ConditionalCheckFailedException":
                current = self.get_approval(approval_id)
                if not current:
                    return False, None, f"Approval '{approval_id}' not found."
                if current.approval_status == ApprovalStatus.EXECUTION_FAILED:
                    return True, current, "Already reconciled as EXECUTION_FAILED"
                return False, current, f"Cannot reconcile: Current state is {current.approval_status.value}."
            logger.error(f"Failed to record reconciled failure for {approval_id}: {e}")
            return False, None, str(e)

    def transition_to_expired(
        self,
        approval_id: str,
    ) -> Tuple[bool, Optional[ApprovalRecord], Optional[str]]:
        """Marks a PENDING or APPROVED record as EXPIRED if time has elapsed."""
        try:
            response = self.table.update_item(
                Key={"approval_id": approval_id},
                UpdateExpression="SET approval_status = :expired",
                ConditionExpression="attribute_exists(approval_id) AND (approval_status = :pending OR approval_status = :approved)",
                ExpressionAttributeValues={
                    ":expired": ApprovalStatus.EXPIRED.value,
                    ":pending": ApprovalStatus.PENDING.value,
                    ":approved": ApprovalStatus.APPROVED.value,
                },
                ReturnValues="ALL_NEW",
            )
            updated_record = _from_dynamodb_dict(response["Attributes"])
            return True, updated_record, None
        except ClientError as e:
            return False, None, str(e)
