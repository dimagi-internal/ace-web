terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

provider "aws" {
  region = var.region
}

data "aws_caller_identity" "current" {}

# Default VPC + subnet are fine for a single, outbound-only emulator host.
# Override `vpc_id` / `subnet_id` in tfvars if running in a custom VPC.
data "aws_vpc" "selected" {
  id = var.vpc_id != "" ? var.vpc_id : data.aws_vpcs.default.ids[0]
}

data "aws_vpcs" "default" {
  filter {
    name   = "is-default"
    values = ["true"]
  }
}

data "aws_subnets" "selected" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.selected.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # Tags applied to every resource. Keep `auto-stop` and `owner` exact —
  # the IAM add-on policy gates ec2/ssm actions on the `owner` value.
  common_tags = merge(
    {
      "owner"      = "ace-web-mobile-poc"
      "auto-stop"  = "true"
      "managed-by" = "terraform"
      "env"        = var.env_suffix
    },
    var.extra_tags,
  )

  subnet_id = var.subnet_id != "" ? var.subnet_id : tolist(data.aws_subnets.selected.ids)[0]
}
