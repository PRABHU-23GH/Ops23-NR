# Remediation: AWS Lambda & SSM Handlers (Phase 4 - Planned)

> **Status:** NOT IMPLEMENTED (Phase 1 Application Foundation)

This directory is reserved for serverless remediation handlers and automation scripts in Phase 4.

Planned capabilities:
- Python Lambda function receiving New Relic incident alert webhooks
- Event parsing and validation of incident payload
- Dispatch of AWS Systems Manager (SSM) Run Command to EC2 instances
- Controlled service restart scripts (`systemctl restart ops23-nr`)
- Post-remediation health verification checking `GET /health`
- Escalation / Bedrock AI root cause analysis trigger if health verification fails
