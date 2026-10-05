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
