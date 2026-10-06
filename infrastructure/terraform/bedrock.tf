# -----------------------------------------------------------------------------
# Phase 7: Amazon Bedrock AI Root Cause Analysis (Least Privilege)
# -----------------------------------------------------------------------------

# Dedicated IAM policy granting ONLY bedrock:InvokeModel on foundation models.
# Strictly forbids ssm:*, ec2:*, iam:*, lambda:*, dynamodb:*, or broad administration.
resource "aws_iam_policy" "bedrock_rca_policy" {
  name        = "${var.project_name}-${var.environment}-bedrock-rca"
  description = "Strict least-privilege permissions for Amazon Bedrock model inference (RCA only)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowBedrockModelInferenceOnly"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ec2_bedrock_rca_attach" {
  role       = aws_iam_role.ec2_ssm_role.name
  policy_arn = aws_iam_policy.bedrock_rca_policy.arn
}
