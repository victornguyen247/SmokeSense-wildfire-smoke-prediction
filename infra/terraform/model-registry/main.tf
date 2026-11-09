# S3 bucket for the model registry (backend/mlops/registry.py, docs/mlops/registry.md),
# two IAM users, and a monthly budget alert for the whole AWS account.
#
#   cd infra/terraform/model-registry
#   terraform init
#   terraform apply -var budget_email=you@example.com
#
# Needs AWS credentials in your shell with permission to create S3 buckets, IAM users and
# budgets. State is LOCAL and gitignored: keep terraform.tfstate (or `terraform import` after
# losing it). Access keys are NOT created here so they never land in the state file; see
# docs/ops/model-registry-s3.md.

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

variable "budget_email" {
  description = "Where budget alerts go."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Whole-account monthly limit. Staging VM (~$10-13) plus S3 (cents) needs headroom, so 20."
  type        = number
  default     = 20
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "smokesense"
      Layer     = "model-registry"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  # Bucket names are global across all AWS accounts; the account id keeps this one unique.
  bucket_name = "smokesense-models-${data.aws_caller_identity.current.account_id}"
  prefix      = "models" # matches REGISTRY_S3_PREFIX's default: objects are models/<name>/<version>.tar.gz
}

# ---------------------------------------------------------------- Bucket

resource "aws_s3_bucket" "models" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "models" {
  bucket                  = aws_s3_bucket.models.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "models" {
  bucket = aws_s3_bucket.models.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# SSE-S3 (free). SSE-KMS would add about $1/month per key.
resource "aws_s3_bucket_server_side_encryption_configuration" "models" {
  bucket = aws_s3_bucket.models.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Registry versions are immutable and checksummed, so S3 versioning would only add cost.
data "aws_iam_policy_document" "tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.models.arn, "${aws_s3_bucket.models.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  bucket = aws_s3_bucket.models.id
  policy = data.aws_iam_policy_document.tls_only.json

  depends_on = [aws_s3_bucket_public_access_block.models]
}

# ---------------------------------------------------------------- IAM users
# Least privilege, scoped to models/*. The registry only uploads and downloads whole archives
# (it never lists or deletes), so the policies match docs/mlops/registry.md.

# Your laptop: register, promote and rollback. Read is needed too, because promote and rollback
# download the archive to verify its sha256 before switching anything.
resource "aws_iam_user" "writer" {
  name = "smokesense-registry-writer"
}

data "aws_iam_policy_document" "writer" {
  statement {
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.models.arn}/${local.prefix}/*"]
  }
}

resource "aws_iam_user_policy" "writer" {
  name   = "registry-read-write"
  user   = aws_iam_user.writer.name
  policy = data.aws_iam_policy_document.writer.json
}

# Staging (and any serving host): download only.
resource "aws_iam_user" "reader" {
  name = "smokesense-registry-reader"
}

data "aws_iam_policy_document" "reader" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.models.arn}/${local.prefix}/*"]
  }
}

resource "aws_iam_user_policy" "reader" {
  name   = "registry-read-only"
  user   = aws_iam_user.reader.name
  policy = data.aws_iam_policy_document.reader.json
}

# ---------------------------------------------------------------- Budget
# Covers the WHOLE account (Lightsail VM + S3 + anything else), not just S3.

resource "aws_budgets_budget" "monthly" {
  name         = "smokesense-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}

# ---------------------------------------------------------------- Outputs

output "bucket_name" {
  description = "REGISTRY_S3_BUCKET"
  value       = aws_s3_bucket.models.bucket
}

output "writer_user" {
  value = aws_iam_user.writer.name
}

output "reader_user" {
  value = aws_iam_user.reader.name
}
