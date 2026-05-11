# Two IAM principals here:
#
# 1. mobile-instance-role: attached to the EC2 instance itself. Lets the
#    SSM agent register with AWS Systems Manager and lets the in-VM
#    `aws s3 cp` upload artifacts to the artifacts bucket.
#
# 2. ace-mobile-task-addon: a customer-managed policy with the EC2 + SSM
#    + S3-read permissions ace-web's ECS task needs to drive the runner.
#    This is *output* by Terraform; the operator attaches it to the
#    existing ace-web task role manually (see README runbook).

# ---------------------------------------------------------------------------
# 1. mobile-instance-role
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "mobile_instance" {
  name               = "ace-mobile-instance-role-${var.env_suffix}"
  description        = "EC2 instance role for the ACE mobile emulator runner."
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy_attachment" "mobile_ssm_core" {
  role       = aws_iam_role.mobile_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Inline: PutObject on the artifacts bucket, scoped to its prefix.
data "aws_iam_policy_document" "instance_s3_put" {
  statement {
    sid     = "ArtifactsPutObject"
    actions = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = [
      "${aws_s3_bucket.artifacts.arn}/*",
    ]
  }

  statement {
    sid       = "ArtifactsListBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.artifacts.arn]
  }
}

resource "aws_iam_role_policy" "mobile_instance_s3" {
  name   = "ace-mobile-instance-s3-${var.env_suffix}"
  role   = aws_iam_role.mobile_instance.id
  policy = data.aws_iam_policy_document.instance_s3_put.json
}

# Read test-user creds for the cold-boot registration recipes. Scoped
# to the specific secret so the instance can't read others.
data "aws_iam_policy_document" "instance_secrets" {
  statement {
    sid     = "ReadTestUserCreds"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      "arn:aws:secretsmanager:${var.region}:${local.account_id}:secret:ace-mobile-test-user-creds-*",
    ]
  }
}

resource "aws_iam_role_policy" "mobile_instance_secrets" {
  name   = "ace-mobile-instance-secrets-${var.env_suffix}"
  role   = aws_iam_role.mobile_instance.id
  policy = data.aws_iam_policy_document.instance_secrets.json
}

resource "aws_iam_instance_profile" "mobile" {
  name = "ace-mobile-instance-profile-${var.env_suffix}"
  role = aws_iam_role.mobile_instance.name
  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# 2. ace-mobile-task-addon (attached to ace-web's existing task role)
# ---------------------------------------------------------------------------
#
# Permissions are scoped to resources tagged `owner=ace-web-mobile-poc` so
# nothing in here can touch unrelated infra in the same account. The
# customer-managed policy is created and its ARN is exposed via the
# `task_addon_policy_arn` output. The README documents the manual
# `aws iam attach-role-policy` step.

data "aws_iam_policy_document" "task_addon" {
  statement {
    sid = "EC2LifecycleScopedByOwnerTag"
    actions = [
      "ec2:StartInstances",
      "ec2:StopInstances",
    ]
    resources = ["arn:aws:ec2:${var.region}:${local.account_id}:instance/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/owner"
      values   = ["ace-web-mobile-poc"]
    }
  }

  statement {
    sid = "EC2DescribeNoTagFilter"
    # Describe* doesn't support resource-level conditions. Read-only.
    actions = [
      "ec2:DescribeInstances",
      "ec2:DescribeInstanceStatus",
    ]
    resources = ["*"]
  }

  statement {
    sid = "SSMSendCommandScopedByOwnerTag"
    actions = [
      "ssm:SendCommand",
    ]
    resources = ["arn:aws:ec2:${var.region}:${local.account_id}:instance/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/owner"
      values   = ["ace-web-mobile-poc"]
    }
  }

  statement {
    sid = "SSMSendCommandDocuments"
    # Need to allow the document ARN as well. AWS-RunShellScript is the
    # only document we use.
    actions   = ["ssm:SendCommand"]
    resources = ["arn:${data.aws_partition.current.partition}:ssm:${var.region}::document/AWS-RunShellScript"]
  }

  statement {
    sid = "SSMReadCommandResults"
    actions = [
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
      "ssm:ListCommands",
    ]
    resources = ["*"]
  }

  statement {
    sid = "S3ReadArtifacts"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
    ]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid = "S3GetObjectArtifacts"
    actions = [
      "s3:GetObject",
    ]
    resources = ["${aws_s3_bucket.artifacts.arn}/*"]
  }
}

data "aws_partition" "current" {}

resource "aws_iam_policy" "task_addon" {
  name        = "ace-mobile-task-addon-${var.env_suffix}"
  description = "Add-on permissions for the ace-web ECS task to drive the mobile emulator runner."
  policy      = data.aws_iam_policy_document.task_addon.json
  tags        = local.common_tags
}
