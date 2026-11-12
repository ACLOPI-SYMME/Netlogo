terraform {
  # >= 1.10: S3 backend with native locking (use_lockfile), no DynamoDB lock table.
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.75"
    }
  }

  # Values in backend.hcl (copy backend.hcl.example): terraform init -backend-config=backend.hcl
  backend "s3" {}
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
    }
  }
}

# CloudFront and AWS Budgets live in us-east-1 for some resources; only the managed policies are read here.
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
