# Ops23-NR AWS Infrastructure Architecture (Terraform)

**Phase 3A: Cloud Infrastructure Preparation**  
**Phase 3B: Infrastructure Deployment (ACTIVE & VALIDATED)**

---

## 1. Live Deployment Summary (Phase 3B)

The Ops23-NR host infrastructure was provisioned via Terraform on **2026-10-05** in the `ap-south-1` AWS region:

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Deployment Status** | **ACTIVE / RUNNING** | Successfully deployed via Terraform. |
| **AWS Region** | `ap-south-1` | Configured via `var.aws_region`. |
| **EC2 Instance ID** | `i-066478e6fd6dc22af` | Low-cost `t3.micro` instance. |
| **Operating System** | Amazon Linux 2023 | AMI: `ami-03054015e26069645` (dynamically discovered). |
| **Public IPv4** | `13.201.166.154` | Dynamic public IPv4 allocated by EC2. |
| **Private IPv4** | `172.31.12.150` | VPC CIDR internal IP. |
| **Security Group ID** | `sg-04b2572ddfd55a77d` | Inbound TCP 8000 only; SSH port 22 is blocked. |
| **IAM Role Name** | `Ops23-NR-dev-ec2-ssm-role` | Managed SSM core access (`AmazonSSMManagedInstanceCore`). |
| **SSM Status** | **Online** | Agent version `3.3.5226.0` actively communicating. |
| **Application Target URL** | `http://13.201.166.154:8000` | Target endpoint for FastAPI in Phase 3C. |

> **Note on Application Deployment:** In Phase 3B, only the cloud infrastructure and operating system prerequisites were provisioned. The application code, virtual environment, and systemd service will be deployed in subsequent phases.

---

## 2. Architecture Overview

Ops23-NR deploys a dedicated host environment for the FastAPI runtime on Amazon Linux 2023 EC2, architected around security best practices, zero static credentials, and remote automation via AWS Systems Manager (SSM).

```
                      [ Internet Traffic ]
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │                 AWS Cloud                    │
        │               (ap-south-1)                   │
        │                                              │
        │   ┌──────────────────────────────────────┐   │
        │   │          Security Group              │   │
        │   │   Ingress: TCP 8000 (FastAPI API)    │   │
        │   │   Ingress: SSH Port 22 (BLOCKED)     │   │
        │   │   Egress:  All Outbound (0.0.0.0/0)  │   │
        │   └──────────────────┬───────────────────┘   │
        │                      │                       │
        │                      ▼                       │
        │   ┌──────────────────────────────────────┐   │
        │   │         EC2 Instance (t3.micro)      │   │
        │   │        Amazon Linux 2023 AMI         │   │
        │   │   ┌──────────────────────────────┐   │   │
        │   │   │      FastAPI Application     │   │   │
        │   │   │  OpenTelemetry Tracing       │   │   │
        │   │   │  Structured JSON Logging     │   │   │
        │   │   └──────────────────────────────┘   │   │
        │   │   ┌──────────────────────────────┐   │   │
        │   │   │      amazon-ssm-agent        │   │   │
        │   │   │   Status: Online (Active)    │   │   │
        │   │   └──────────────▲───────────────┘   │   │
        │   │                  │                   │   │
        │   │   Root Storage: 20GB gp3 (Encrypted) │   │
        │   └──────────────────┼───────────────────┘   │
        │                      │                       │
        │                      │ Instance Profile      │
        │                      │                       │
        │   ┌──────────────────┴───────────────────┐   │
        │   │               IAM Role               │   │
        │   │  Policy: AmazonSSMManagedInstanceCore│   │
        │   │  (No Admin / Overly Broad Access)   │   │
        │   └──────────────────────────────────────┘   │
        └──────────────────────────────────────────────┘
                               ▲
                               │ Outbound HTTPS (TLS 443)
                               │
               [ AWS Systems Manager Service ]
            (Session Manager / Run Command / Automation)
```

---

## 3. Resources Created in AWS

All Terraform manifests reside in [infrastructure/terraform/](file:///d:/Ops23-NR/infrastructure/terraform/):

| Resource Type | Resource Name | ID / ARN | Purpose |
| :--- | :--- | :--- | :--- |
| `aws_instance` | `app_server` | `i-066478e6fd6dc22af` | Single `t3.micro` EC2 instance hosting the Ops23-NR FastAPI runtime. |
| `data.aws_ami` | `amazon_linux_2023` | `ami-03054015e26069645` | Latest Amazon Linux 2023 HVM x86_64 AMI (no hardcoded AMI IDs). |
| `aws_security_group` | `app_sg` | `sg-04b2572ddfd55a77d` | Security perimeter: allows TCP port 8000 inbound, denies SSH port 22, allows all outbound. |
| `aws_iam_role` | `ec2_ssm_role` | `Ops23-NR-dev-ec2-ssm-role` | Service role assumed by EC2 with trust policy for `ec2.amazonaws.com`. |
| `aws_iam_role_policy_attachment` | `ssm_managed_instance_core` | Managed policy | Attaches `arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore` for SSM management. |
| `aws_iam_instance_profile` | `ec2_ssm_instance_profile` | `Ops23-NR-dev-ec2-ssm-profile` | Binds the SSM IAM role to the EC2 instance. |

---

## 4. Why AWS Systems Manager (SSM) is Used Instead of SSH

Traditional EC2 deployments open TCP port 22 to the public internet and require managing static `.pem` key pairs, creating significant security attack surfaces and key rotation burdens.

Ops23-NR uses **AWS Systems Manager (SSM)**:
1. **Zero Open Inbound Management Ports**: The security group completely omits SSH port 22.
2. **Encrypted Outbound Control Channel**: The pre-installed `amazon-ssm-agent` initiates outbound HTTPS connections to AWS SSM endpoints.
3. **Session Manager & Run Command**: Remote shell access and automated commands are executed via AWS SSM Session Manager (`aws ssm start-session`) or automated Lambda workflows (Phase 5).
4. **Auditability**: All session commands and actions are logged to AWS CloudTrail and Amazon CloudWatch Logs.

---

## 5. Security Group Design

The application security group ([main.tf](file:///d:/Ops23-NR/infrastructure/terraform/main.tf)) implements the principle of least privilege:

```hcl
resource "aws_security_group" "app_sg" {
  name        = "Ops23-NR-dev-app-sg"
  description = "Security group for Ops23-NR FastAPI service (SSM managed, no SSH)"

  ingress {
    description = "Allow inbound traffic for Ops23-NR FastAPI application"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks # Defaults to ["0.0.0.0/0"] for dev/demo
  }

  egress {
    description = "Allow all outbound traffic for telemetry export, SSM, and package updates"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

---

## 6. Storage Configuration

- **Volume Type**: `gp3` (General Purpose SSD with 3,000 baseline IOPS and 125 MB/s throughput).
- **Size**: 20 GB (sufficient for OS, Python 3.12 runtime, virtual environment, and systemd journal logs).
- **Encryption**: `encrypted = true` using default AWS managed KMS key (`aws/ebs`).
- **Lifecycle**: `delete_on_termination = true` to prevent orphaned disk costs upon decommissioning.

---

## 7. Minimal OS Bootstrap (`user_data`)

The EC2 user-data script performs minimal initialization without installing New Relic or embedding secrets:

```bash
#!/bin/bash
set -e
# Ops23-NR Phase 3A: Minimal OS bootstrap
dnf update -y
dnf install -y python3.12 python3.12-pip git
systemctl enable amazon-ssm-agent
systemctl start amazon-ssm-agent
```

---

## 8. Input Variables & Outputs

### Configurable Variables ([variables.tf](file:///d:/Ops23-NR/infrastructure/terraform/variables.tf))
- `aws_region`: AWS region (default: `"ap-south-1"`).
- `project_name`: Project tag/prefix (default: `"Ops23-NR"`).
- `environment`: Environment tag (default: `"dev"`).
- `instance_type`: Compute sizing (default: `"t3.micro"`).
- `allowed_cidr_blocks`: Ingress CIDRs for port 8000 (default: `["0.0.0.0/0"]`).
- `root_volume_size`: Root disk size in GB (default: `20`).

### Outputs ([outputs.tf](file:///d:/Ops23-NR/infrastructure/terraform/outputs.tf))
- `instance_id`: `i-066478e6fd6dc22af`
- `public_ip`: `13.201.166.154`
- `private_ip`: `172.31.12.150`
- `security_group_id`: `sg-04b2572ddfd55a77d`
- `iam_role_name`: `Ops23-NR-dev-ec2-ssm-role`
- `application_url`: `http://13.201.166.154:8000`
