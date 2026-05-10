output "instance_id" {
  description = "Plug into ace-web's `ACE_MOBILE_INSTANCE_ID` env var."
  value       = aws_instance.mobile.id
}

output "instance_security_group_id" {
  description = "Egress-only SG attached to the emulator instance."
  value       = aws_security_group.mobile.id
}

output "artifacts_bucket_name" {
  description = "Plug into ace-web's `ACE_MOBILE_S3_BUCKET` env var."
  value       = aws_s3_bucket.artifacts.bucket
}

output "artifacts_bucket_arn" {
  description = "ARN of the artifacts bucket."
  value       = aws_s3_bucket.artifacts.arn
}

output "task_addon_policy_arn" {
  description = "ARN of the customer-managed IAM policy. Attach manually to the ace-web ECS task role; see README runbook."
  value       = aws_iam_policy.task_addon.arn
}

output "ace_web_task_role_name" {
  description = "Echoes `var.ace_web_task_role_name` so the README's attach-role-policy command can be copy-pasted with terraform output values."
  value       = var.ace_web_task_role_name
}

output "ami_version" {
  description = "Echoes `var.ami_version` so the deploy script can plug it into ACE_MOBILE_AMI_VERSION."
  value       = var.ami_version
}

output "region" {
  description = "Plug into ace-web's `ACE_MOBILE_AWS_REGION` env var."
  value       = var.region
}

output "env_for_task_definition" {
  description = <<-EOT
    Copy these env vars into `deploy/aws/task-definition.json` under the
    ace-web container's `environment` list. They feed `apps/mobile/`.
  EOT
  value = {
    ACE_MOBILE_AWS_REGION  = var.region
    ACE_MOBILE_INSTANCE_ID = aws_instance.mobile.id
    ACE_MOBILE_S3_BUCKET   = aws_s3_bucket.artifacts.bucket
    ACE_MOBILE_AMI_VERSION = var.ami_version
  }
}
