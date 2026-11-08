# One small always-on Lightsail VM that runs the staging compose stack
# (infra/staging/docker-compose.yml). Postgres is Neon, so the VM holds no data worth backing up.
#
#   cd infra/terraform/staging-vm
#   terraform init
#   terraform apply -var 'ssh_public_keys=["ssh-ed25519 AAAA... you@laptop", "ssh-ed25519 AAAA... github-deploy"]'
#
# Needs AWS credentials in your shell with Lightsail permissions (AWS_PROFILE or env vars).
# State is LOCAL and gitignored: keep terraform.tfstate or `terraform import` after losing it.
# Setup after apply: docs/ops/staging.md.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.90"
    }
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "availability_zone" {
  type    = string
  default = "us-east-1a"
}

variable "instance_name" {
  type    = string
  default = "smokesense-staging"
}

variable "bundle_id" {
  description = "Lightsail plan. small_3_0 should be the 2 GB / 2 vCPU plan (~$10/mo); confirm with `aws lightsail get-bundles` before applying."
  type        = string
  default     = "small_3_0"
}

variable "ssh_public_keys" {
  description = "Public keys allowed to log in as the `deploy` user: yours, plus the one whose private half is the GitHub secret STAGING_SSH_KEY."
  type        = list(string)

  validation {
    condition     = length(var.ssh_public_keys) > 0
    error_message = "Provide at least one SSH public key, or nobody can log in."
  }
}

variable "ssh_allowed_cidrs" {
  description = "Who may reach port 22. GitHub-hosted runners have no fixed IPs, so the default is open; the box accepts keys only and runs fail2ban."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "smokesense"
      Env       = "staging"
      ManagedBy = "terraform"
    }
  }
}

resource "aws_lightsail_static_ip" "staging" {
  name = "${var.instance_name}-ip"
}

resource "aws_lightsail_instance" "staging" {
  name              = var.instance_name
  availability_zone = var.availability_zone
  blueprint_id      = "ubuntu_24_04"
  bundle_id         = var.bundle_id

  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    ssh_public_keys = var.ssh_public_keys
  })

  # user_data only runs on first boot; editing it must not replace a working box.
  lifecycle {
    ignore_changes = [user_data]
  }
}

# Both of these point at the instance by NAME, which stays the same when the instance is
# replaced, so Terraform would not notice the new box and the static IP and firewall rules would
# be left on the deleted one. created_at changes on every new instance, which forces them to be
# redone.
resource "aws_lightsail_static_ip_attachment" "staging" {
  static_ip_name = aws_lightsail_static_ip.staging.name
  instance_name  = aws_lightsail_instance.staging.name

  lifecycle {
    replace_triggered_by = [aws_lightsail_instance.staging.created_at]
  }
}

resource "aws_lightsail_instance_public_ports" "staging" {
  instance_name = aws_lightsail_instance.staging.name

  lifecycle {
    replace_triggered_by = [aws_lightsail_instance.staging.created_at]
  }

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = var.ssh_allowed_cidrs
  }

  port_info {
    protocol  = "tcp"
    from_port = 80
    to_port   = 80
  }

  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
  }

  port_info {
    protocol  = "udp"
    from_port = 443
    to_port   = 443
  }
}

output "public_ip" {
  value = aws_lightsail_static_ip.staging.ip_address
}

output "site_address" {
  description = "Free hostname for the box (sslip.io resolves it to the IP). Use it as STAGING_HOST and SITE_ADDRESS."
  value       = "${replace(aws_lightsail_static_ip.staging.ip_address, ".", "-")}.sslip.io"
}

output "ssh_command" {
  value = "ssh deploy@${aws_lightsail_static_ip.staging.ip_address}"
}
