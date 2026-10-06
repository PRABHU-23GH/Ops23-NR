# -----------------------------------------------------------------------------
# Phase 8: Human-in-the-Loop AI Remediation Approvals
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# DynamoDB Table: Remediation Approvals & Audit Trail
# -----------------------------------------------------------------------------
resource "aws_dynamodb_table" "remediation_approvals" {
  name         = "${var.project_name}-${var.environment}-remediation-approvals"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "approval_id"

  attribute {
    name = "approval_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-remediation-approvals"
    Environment = var.environment
    Project     = var.project_name
    Phase       = "Phase-8"
  }
}

# -----------------------------------------------------------------------------
# IAM Policy: Approval Storage Access & Controlled Lambda Handoff
# -----------------------------------------------------------------------------
# Grants FastAPI service on EC2 least-privilege permissions to:
# 1. Read, write, and update records in the approvals DynamoDB table
# 2. Invoke ONLY the Phase 6 remediation Lambda handler upon explicit human approval
resource "aws_iam_policy" "remediation_approval_policy" {
  name        = "${var.project_name}-${var.environment}-remediation-approval-policy"
  description = "Allows Ops23-NR service to manage remediation approvals and invoke remediation Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowApprovalsTableAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:DescribeTable"
        ]
        Resource = aws_dynamodb_table.remediation_approvals.arn
      },
      {
        Sid    = "AllowInvokeRemediationLambdaOnly"
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = aws_lambda_function.remediation_lambda.arn
      },
      {
        Sid    = "AllowSSMCommandStatusObservationOnly"
        Effect = "Allow"
        Action = [
          "ssm:GetCommandInvocation",
          "ssm:ListCommands",
          "ssm:ListCommandInvocations",
          "ssm:DescribeInstanceInformation"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ec2_approval_policy_attach" {
  role       = aws_iam_role.ec2_ssm_role.name
  policy_arn = aws_iam_policy.remediation_approval_policy.arn
}
