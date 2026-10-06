output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.app_server.id
}

output "public_ip" {
  description = "Public IPv4 address of the Ops23-NR EC2 instance"
  value       = aws_instance.app_server.public_ip
}

output "private_ip" {
  description = "Private IPv4 address of the Ops23-NR EC2 instance"
  value       = aws_instance.app_server.private_ip
}

output "security_group_id" {
  description = "Security group ID assigned to the Ops23-NR EC2 instance"
  value       = aws_security_group.app_sg.id
}

output "iam_role_name" {
  description = "IAM role name granting SSM management access"
  value       = aws_iam_role.ec2_ssm_role.name
}

output "application_url" {
  description = "Target URL for the Ops23-NR FastAPI service"
  value       = "http://${aws_instance.app_server.public_ip}:8000"
}

output "remediation_lambda_role_arn" {
  description = "ARN of the dedicated remediation Lambda execution IAM role"
  value       = aws_iam_role.remediation_lambda_role.arn
}

output "remediation_idempotency_table_name" {
  description = "Name of the DynamoDB table used for remediation idempotency"
  value       = aws_dynamodb_table.remediation_idempotency.name
}

output "remediation_webhook_url" {
  description = "API Gateway endpoint URL for New Relic remediation webhook"
  value       = "${aws_apigatewayv2_api.remediation_api.api_endpoint}/remediate"
}

output "bedrock_rca_policy_arn" {
  description = "ARN of the dedicated Amazon Bedrock RCA IAM policy"
  value       = aws_iam_policy.bedrock_rca_policy.arn
}



