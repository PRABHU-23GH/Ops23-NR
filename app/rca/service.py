"""Core Amazon Bedrock Root Cause Analysis (RCA) Service.

Phase 7: Modular Service Architecture, Diagnostic Evidence Provider,
Amazon Bedrock Runtime Client, and Deterministic Safety Boundary.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from app.config import Settings, get_settings
from app.rca.models import (
    BedrockRawRCAOutput,
    RCARequest,
    RCAResponse,
    RecommendationDecision,
    TelemetryEvidence,
)
from app.rca.prompts import SYSTEM_PROMPT, build_analysis_prompt

logger = logging.getLogger("ops23.rca")
logger.setLevel(logging.INFO)

# Strict Remediation Allowlist Constants
ALLOWED_ACTION = "RESTART_OPS23_SERVICE"
ALLOWED_TARGET = "i-066478e6fd6dc22af"
ALLOWED_SERVICE = "ops23-nr.service"


class EvidenceProvider(ABC):
    """Abstract provider interface for collecting diagnostic telemetry evidence."""

    @abstractmethod
    def collect_evidence(self, incident_id: str) -> TelemetryEvidence:
        """Retrieve telemetry evidence associated with the given incident identifier."""
        raise NotImplementedError


class StructuredEvidenceProvider(EvidenceProvider):
    """Default provider returning pre-collected or caller-supplied evidence."""

    def __init__(self, evidence: Optional[TelemetryEvidence] = None):
        self._evidence = evidence or TelemetryEvidence()

    def collect_evidence(self, incident_id: str) -> TelemetryEvidence:
        self._evidence.incident_id = incident_id
        return self._evidence


def validate_recommendation_safety(
    raw_output: BedrockRawRCAOutput,
) -> Tuple[RecommendationDecision, str]:
    """
    Enforces a strict deterministic safety boundary between AI output and remediation.

    Rules:
    1. If action is NONE -> NO_ACTION_REQUIRED
    2. If action == RESTART_OPS23_SERVICE AND target == i-066478e6fd6dc22af AND service == ops23-nr.service
       -> ALLOWLISTED_RECOMMENDATION
    3. Any other action, arbitrary target, shell command, or script -> REJECTED_RECOMMENDATION
    """
    action = raw_output.recommended_action.strip()
    target = raw_output.recommended_target.strip()
    service = raw_output.recommended_service.strip()

    # Case 1: No action needed or insufficient evidence
    if action.upper() in ("NONE", "NO_ACTION", "INSUFFICIENT_EVIDENCE"):
        return (
            RecommendationDecision.NO_ACTION_REQUIRED,
            "No automated remediation action recommended.",
        )

    # Detect arbitrary command injections or shell metacharacters
    dangerous_tokens = [";", "&&", "||", "|", "`", "$", "rm ", "sh", "bash", "systemctl", "curl", "wget"]
    for field in (action, target, service):
        if any(token in field.lower() for token in dangerous_tokens):
            return (
                RecommendationDecision.REJECTED_RECOMMENDATION,
                "Rejected: Proposed recommendation contains prohibited shell metacharacters or command strings.",
            )

    # Case 2: Strict match against approved remediation contract
    if (
        action == ALLOWED_ACTION
        and target == ALLOWED_TARGET
        and service == ALLOWED_SERVICE
    ):
        return (
            RecommendationDecision.ALLOWLISTED_RECOMMENDATION,
            f"Validated: Recommendation matches allowlisted action '{ALLOWED_ACTION}' for target '{ALLOWED_TARGET}'.",
        )

    # Case 3: Rejection for non-allowlisted targets or actions
    reasons = []
    if action != ALLOWED_ACTION:
        reasons.append(f"Action '{action}' is not allowlisted (expected '{ALLOWED_ACTION}')")
    if target != ALLOWED_TARGET:
        reasons.append(f"Target '{target}' is unauthorized (expected '{ALLOWED_TARGET}')")
    if service != ALLOWED_SERVICE:
        reasons.append(f"Service '{service}' is unauthorized (expected '{ALLOWED_SERVICE}')")

    return (
        RecommendationDecision.REJECTED_RECOMMENDATION,
        f"Rejected: {', '.join(reasons)}.",
    )


def extract_json_payload(text: str) -> str:
    """Strips Markdown fences or leading/trailing commentary if present."""
    clean = text.strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    return clean.strip()


class RCAService:
    """Service orchestrating diagnostic evidence collection, Bedrock inference, and safety validation."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        bedrock_client: Any = None,
        evidence_provider: Optional[EvidenceProvider] = None,
    ):
        self.settings = settings or get_settings()
        self.model_id = self.settings.BEDROCK_MODEL_ID
        self.region = self.settings.BEDROCK_REGION
        self.evidence_provider = evidence_provider or StructuredEvidenceProvider()

        # Initialize or inject Bedrock runtime client
        if bedrock_client is not None:
            self._bedrock_client = bedrock_client
        elif self.settings.BEDROCK_ENABLED:
            try:
                self._bedrock_client = boto3.client(
                    "bedrock-runtime",
                    region_name=self.region,
                )
            except Exception as e:
                logger.warning(
                    json.dumps({
                        "event": "bedrock_client_init_failed",
                        "error": str(e),
                    })
                )
                self._bedrock_client = None
        else:
            self._bedrock_client = None

    def analyze_incident(self, request: RCARequest) -> RCAResponse:
        """Executes the end-to-end Root Cause Analysis workflow."""
        start_time = datetime.now(timezone.utc)
        incident_id = request.incident_id

        # 1. Structured audit log: RCA Started
        logger.info(
            json.dumps({
                "event": "rca_analysis_started",
                "incident_id": incident_id,
                "model_id": self.model_id,
                "timestamp": start_time.isoformat(),
            })
        )

        # 2. Check if Bedrock is explicitly enabled
        if not self.settings.BEDROCK_ENABLED:
            logger.info(
                json.dumps({
                    "event": "bedrock_disabled_fallback",
                    "incident_id": incident_id,
                })
            )
            return RCAResponse(
                incident_id=incident_id,
                service="Ops23-NR",
                severity="INFO",
                root_cause="BEDROCK_DISABLED: Amazon Bedrock RCA is disabled in platform configuration.",
                evidence=["BEDROCK_ENABLED is set to False in application settings."],
                confidence=0.0,
                recommended_action="NONE",
                recommended_target="NONE",
                recommended_service="NONE",
                reasoning_summary="Bedrock AI analysis skipped because BEDROCK_ENABLED=False for safety.",
                decision=RecommendationDecision.NO_ACTION_REQUIRED,
                execution_allowed=False,
                model_id=self.model_id,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                safety_validation_message="Analysis bypassed: Bedrock disabled. No action taken.",
            )

        # 3. Verify client availability
        if self._bedrock_client is None:
            logger.warning(
                json.dumps({
                    "event": "bedrock_unavailable",
                    "incident_id": incident_id,
                    "message": "Bedrock runtime client is not available.",
                })
            )
            return RCAResponse(
                incident_id=incident_id,
                service="Ops23-NR",
                severity="WARNING",
                root_cause="BEDROCK_UNAVAILABLE: AWS Bedrock runtime client is unavailable.",
                evidence=["Client initialization failed or credentials not present."],
                confidence=0.0,
                recommended_action="NONE",
                recommended_target="NONE",
                recommended_service="NONE",
                reasoning_summary="Cannot invoke Bedrock due to missing runtime client or credentials.",
                decision=RecommendationDecision.REJECTED_RECOMMENDATION,
                execution_allowed=False,
                model_id=self.model_id,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                safety_validation_message="Analysis aborted: Bedrock runtime client unavailable.",
            )

        # 4. Construct Prompt
        user_prompt = build_analysis_prompt(incident_id, request.evidence)
        request_body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
        })

        # 5. Invoke Bedrock Model with Graceful Error Handling
        try:
            response = self._bedrock_client.invoke_model(
                modelId=self.model_id,
                body=request_body,
                contentType="application/json",
                accept="application/json",
            )
            response_body_bytes = response["body"].read()
            response_data = json.loads(response_body_bytes.decode("utf-8"))
            raw_text = response_data.get("content", [{}])[0].get("text", "")
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "ClientError")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                json.dumps({
                    "event": "bedrock_invocation_client_error",
                    "incident_id": incident_id,
                    "error_code": error_code,
                    "error_message": error_message,
                })
            )
            return RCAResponse(
                incident_id=incident_id,
                service="Ops23-NR",
                severity="HIGH",
                root_cause=f"BEDROCK_INVOCATION_ERROR: AWS Bedrock invocation error ({error_code}).",
                evidence=[f"AWS error code: {error_code}", f"AWS error message: {error_message}"],
                confidence=0.0,
                recommended_action="NONE",
                recommended_target="NONE",
                recommended_service="NONE",
                reasoning_summary=f"Model invocation failed via AWS Bedrock: {error_code}.",
                decision=RecommendationDecision.REJECTED_RECOMMENDATION,
                execution_allowed=False,
                model_id=self.model_id,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                safety_validation_message=f"Model call failed: {error_code}. No remediation permitted.",
            )
        except Exception as ex:
            logger.error(
                json.dumps({
                    "event": "bedrock_invocation_unexpected_error",
                    "incident_id": incident_id,
                    "error": str(ex),
                })
            )
            return RCAResponse(
                incident_id=incident_id,
                service="Ops23-NR",
                severity="HIGH",
                root_cause="BEDROCK_INVOCATION_FAILED: Unexpected error during Bedrock call.",
                evidence=[str(ex)],
                confidence=0.0,
                recommended_action="NONE",
                recommended_target="NONE",
                recommended_service="NONE",
                reasoning_summary="Exception encountered while contacting Bedrock.",
                decision=RecommendationDecision.REJECTED_RECOMMENDATION,
                execution_allowed=False,
                model_id=self.model_id,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                safety_validation_message="Bedrock call failed. No remediation permitted.",
            )

        # 6. Parse and Validate Model JSON
        cleaned_json = extract_json_payload(raw_text)
        try:
            parsed_json = json.loads(cleaned_json)
        except json.JSONDecodeError as err:
            logger.error(
                json.dumps({
                    "event": "bedrock_invalid_json_output",
                    "incident_id": incident_id,
                    "error": str(err),
                })
            )
            return RCAResponse(
                incident_id=incident_id,
                service="Ops23-NR",
                severity="MEDIUM",
                root_cause="INVALID_MODEL_OUTPUT: Bedrock response was not valid JSON.",
                evidence=["Model generated malformed output that could not be parsed as JSON."],
                confidence=0.0,
                recommended_action="NONE",
                recommended_target="NONE",
                recommended_service="NONE",
                reasoning_summary="Model output was malformed. Rejection enforced by safety boundary.",
                decision=RecommendationDecision.REJECTED_RECOMMENDATION,
                execution_allowed=False,
                model_id=self.model_id,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                safety_validation_message="JSON decode error: Output rejected by safety boundary.",
            )

        # 7. Validate strict Pydantic schema
        try:
            raw_rca = BedrockRawRCAOutput(**parsed_json)
        except Exception as val_err:
            logger.error(
                json.dumps({
                    "event": "bedrock_schema_validation_failed",
                    "incident_id": incident_id,
                    "error": str(val_err),
                })
            )
            return RCAResponse(
                incident_id=incident_id,
                service="Ops23-NR",
                severity="MEDIUM",
                root_cause="SCHEMA_VALIDATION_FAILED: Model output failed strict Pydantic validation.",
                evidence=[str(val_err)],
                confidence=0.0,
                recommended_action="NONE",
                recommended_target="NONE",
                recommended_service="NONE",
                reasoning_summary="Model output violated expected schema structure.",
                decision=RecommendationDecision.REJECTED_RECOMMENDATION,
                execution_allowed=False,
                model_id=self.model_id,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                safety_validation_message="Schema validation error: Output rejected.",
            )

        # 8. Apply Deterministic Safety Boundary Validation
        decision, safety_message = validate_recommendation_safety(raw_rca)

        # 9. Structured audit log: RCA Completed
        logger.info(
            json.dumps({
                "event": "rca_analysis_completed",
                "incident_id": raw_rca.incident_id,
                "root_cause": raw_rca.root_cause,
                "confidence": raw_rca.confidence,
                "recommended_action": raw_rca.recommended_action,
                "decision": decision.value,
                "execution_allowed": False,
            })
        )

        return RCAResponse(
            incident_id=incident_id,
            service=raw_rca.service,
            severity=raw_rca.severity,
            root_cause=raw_rca.root_cause,
            evidence=raw_rca.evidence,
            confidence=raw_rca.confidence,
            recommended_action=raw_rca.recommended_action,
            recommended_target=raw_rca.recommended_target,
            recommended_service=raw_rca.recommended_service,
            reasoning_summary=raw_rca.reasoning_summary,
            decision=decision,
            execution_allowed=False,  # Phase 7 is analysis only
            model_id=self.model_id,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            safety_validation_message=safety_message,
        )
