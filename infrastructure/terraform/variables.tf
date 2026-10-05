variable "aws_region" {
  description = "AWS region for provisioning Ops23-NR infrastructure"
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Project identifier used in resource names and tags"
  type        = string
  default     = "Ops23-NR"
}

variable "environment" {
  description = "Deployment environment name (e.g. dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "instance_type" {
  description = "EC2 instance type suitable for low-cost / free-tier development"
  type        = string
  default     = "t3.micro"
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks permitted to access FastAPI on port 8000 (restrict in production)"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "root_volume_size" {
  description = "Size of the encrypted gp3 EBS root volume in gigabytes"
  type        = number
  default     = 20
}
