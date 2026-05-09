variable "region" {
  description = "AWS region. Must match the region the AMI is baked in."
  type        = string
  default     = "us-east-1"
}

variable "env_suffix" {
  description = <<-EOT
    Suffix appended to global resource names so dev/staging/prod can co-exist
    in the same account. Used in the S3 bucket name (`ace-mobile-artifacts-<suffix>`)
    and IAM resource names. Lowercase letters, digits, hyphens.
  EOT
  type        = string
  default     = "labs"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.env_suffix))
    error_message = "env_suffix must be lowercase letters, digits, or hyphens."
  }
}

variable "ami_id" {
  description = <<-EOT
    The AMI ID baked by `infra/mobile-ami/`. Replace the placeholder before
    the first `terraform apply`. Get it from the `packer build` output, e.g.
    `ami-0abc...`. The AMI must live in `var.region`.
  EOT
  type        = string
  default     = "ami-PLACEHOLDER-RUN-PACKER-FIRST"

  validation {
    condition     = can(regex("^ami-[0-9a-f]{8,17}$", var.ami_id)) || var.ami_id == "ami-PLACEHOLDER-RUN-PACKER-FIRST"
    error_message = "ami_id must be a valid AMI ID like `ami-0abc12345...`."
  }
}

variable "ami_version" {
  description = <<-EOT
    Human-readable AMI version (e.g., `v1`, `2026-05-09-1`). Surfaced via
    the `ami_version` output and passed into the ace-web task definition
    as `ACE_MOBILE_AMI_VERSION` so `/api/mobile/status` can show it.
  EOT
  type        = string
  default     = "unset"
}

variable "instance_type" {
  description = <<-EOT
    EC2 instance type. Default `m8i.xlarge` is the smallest m8i that exposes
    nested virt for KVM; `kvm-ok` must succeed during the bake. If KVM ever
    fails, fallbacks (in order of preference) are `c8i.xlarge` (cheaper, also
    nested-virt) or `m7i.metal-24xl` (bare metal — significantly more expensive).
  EOT
  type        = string
  default     = "m8i.xlarge"
}

variable "vpc_id" {
  description = "VPC ID. Empty string uses the account's default VPC."
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = <<-EOT
    Subnet ID for the EC2 instance. Empty string picks an arbitrary
    default-for-az subnet from the selected VPC. Must have outbound
    443 egress to reach SSM and S3.
  EOT
  type        = string
  default     = ""
}

variable "ace_web_task_role_name" {
  description = <<-EOT
    Name (not ARN) of the existing ace-web ECS task role. The Terraform
    creates an IAM policy and outputs its ARN; you (the operator) attach
    that policy to this role manually after `terraform apply`. The default
    matches the role in `deploy/aws/task-definition.json`.
  EOT
  type        = string
  default     = "labs-jj-ecs-task-role"
}

variable "extra_tags" {
  description = "Extra tags to merge into `local.common_tags`."
  type        = map(string)
  default     = {}
}
