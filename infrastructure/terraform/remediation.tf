# -----------------------------------------------------------------------------
# Phase 6A: Remediation Foundation & IAM Architecture
# -----------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

# -----------------------------------------------------------------------------
# DynamoDB Table: Remediation Event Idempotency & Duplicate Prevention
# -----------------------------------------------------------------------------
resource "aws_dynamodb_table" "remediation_idempotency" {
  name         = "${var.project_name}-${var.environment}-remediation-idempotency"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "event_id"

  attribute {
    name = "event_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-remediation-idempotency"
  }
}

# -----------------------------------------------------------------------------
# Dedicated Lambda Execution IAM Role (Least Privilege)
# -----------------------------------------------------------------------------
resource "aws_iam_role" "remediation_lambda_role" {
  name = "${var.project_name}-${var.environment}-remediation-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.project_name}-${var.environment}-remediation-lambda-role"
  }
}

# -----------------------------------------------------------------------------
# IAM Policy: CloudWatch Logs for Structured Audit Logging
# -----------------------------------------------------------------------------
resource "aws_iam_policy" "lambda_logging_policy" {
  name        = "${var.project_name}-${var.environment}-lambda-logging"
  description = "Allows Lambda to write structured audit logs to CloudWatch"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logging_attach" {
  role       = aws_iam_role.remediation_lambda_role.name
  policy_arn = aws_iam_policy.lambda_logging_policy.arn
}

# -----------------------------------------------------------------------------
# IAM Policy: Restrictive SSM SendCommand and GetCommandInvocation
# -----------------------------------------------------------------------------
# Specifically restricted to:
# - Target instance: ONLY i-066478e6fd6dc22af
# - Document: ONLY AWS-RunShellScript
# No arbitrary instances or arbitrary documents allowed.
resource "aws_iam_policy" "remediation_ssm_policy" {
  name        = "${var.project_name}-${var.environment}-remediation-ssm"
  description = "Strict least-privilege SSM permissions for Ops23-NR service restart"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowRunShellScriptOnTargetInstance"
        Effect = "Allow"
        Action = [
          "ssm:SendCommand"
        ]
        Resource = [
          "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/${aws_instance.app_server.id}",
          "arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript"
        ]
      },
      {
        Sid    = "AllowGetCommandInvocationStatus"
        Effect = "Allow"
        Action = [
          "ssm:GetCommandInvocation"
        ]
        Resource = [
          "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "remediation_ssm_attach" {
  role       = aws_iam_role.remediation_lambda_role.name
  policy_arn = aws_iam_policy.remediation_ssm_policy.arn
}

# -----------------------------------------------------------------------------
# IAM Policy: DynamoDB Access for Idempotency Tracking
# -----------------------------------------------------------------------------
resource "aws_iam_policy" "remediation_dynamodb_policy" {
  name        = "${var.project_name}-${var.environment}-remediation-dynamodb"
  description = "Allows reading and writing idempotency records in DynamoDB"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowIdempotencyRecordAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem"
        ]
        Resource = aws_dynamodb_table.remediation_idempotency.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "remediation_dynamodb_attach" {
  role       = aws_iam_role.remediation_lambda_role.name
  policy_arn = aws_iam_policy.remediation_dynamodb_policy.arn
}

# -----------------------------------------------------------------------------
# Lambda Remediation Function
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "remediation_lambda" {
  filename         = "${path.module}/../../remediation/dist/lambda.zip"
  function_name    = "${var.project_name}-${var.environment}-remediation-handler"
  role             = aws_iam_role.remediation_lambda_role.arn
  handler          = "handler.lambda_handler"
  source_code_hash = filebase64sha256("${path.module}/../../remediation/dist/lambda.zip")
  runtime          = "python3.12"
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      IDEMPOTENCY_TABLE_NAME = aws_dynamodb_table.remediation_idempotency.name
      AWS_REGION_NAME        = var.aws_region
    }
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-remediation-handler"
  }
}

# -----------------------------------------------------------------------------
# API Gateway HTTP API (Webhook Ingress)
# -----------------------------------------------------------------------------
resource "aws_apigatewayv2_api" "remediation_api" {
  name          = "${var.project_name}-${var.environment}-remediation-api"
  protocol_type = "HTTP"
  description   = "Secure webhook ingestion gateway for Ops23-NR automated self-healing"

  tags = {
    Name = "${var.project_name}-${var.environment}-remediation-api"
  }
}

resource "aws_apigatewayv2_stage" "default_stage" {
  api_id      = aws_apigatewayv2_api.remediation_api.id
  name        = "$default"
  auto_deploy = true

  tags = {
    Name = "${var.project_name}-${var.environment}-remediation-default-stage"
  }
}

resource "aws_apigatewayv2_integration" "lambda_integration" {
  api_id                 = aws_apigatewayv2_api.remediation_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.remediation_lambda.arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "remediate_route" {
  api_id    = aws_apigatewayv2_api.remediation_api.id
  route_key = "POST /remediate"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

resource "aws_lambda_permission" "apigw_lambda_permission" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.remediation_lambda.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.remediation_api.execution_arn}/*/*"
}

