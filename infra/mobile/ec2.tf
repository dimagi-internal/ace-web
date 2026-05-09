# EC2 launch template + lone instance for the mobile emulator runner.
#
# Initial-state pattern. Terraform has no native "create the instance, then
# stop it" idiom. We let aws_instance create the instance in `running`
# state, then a `null_resource` with a `local-exec` provisioner immediately
# stops it. The aws_instance lifecycle ignores the runtime state attributes
# so subsequent `terraform apply`s don't fight start/stop initiated by
# ace-web or the CloudWatch alarm.
#
# Why a launch template AND an aws_instance? The launch template captures
# the canonical block-device + IMDS + tag config so future scale-up to a
# small fleet (Step N+1) is a one-line change. For the POC we instantiate
# exactly one aws_instance from it.

resource "aws_security_group" "mobile" {
  name        = "ace-mobile-emulator-${var.env_suffix}"
  description = "Egress-only SG for the ACE mobile emulator. SSM only - no inbound."
  vpc_id      = data.aws_vpc.selected.id

  # No ingress rules. Period. Access is via SSM Session Manager.

  egress {
    description      = "Outbound HTTPS for SSM, S3, package mirrors."
    from_port        = 443
    to_port          = 443
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    description = "Outbound DNS (UDP) for in-VM lookups."
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "ace-mobile-emulator-${var.env_suffix}"
  })
}

resource "aws_launch_template" "mobile" {
  name        = "ace-mobile-emulator-${var.env_suffix}"
  description = "Mobile emulator runner - KVM-on-EC2, SSM-only access."

  image_id      = var.ami_id
  instance_type = var.instance_type

  iam_instance_profile {
    arn = aws_iam_instance_profile.mobile.arn
  }

  vpc_security_group_ids = [aws_security_group.mobile.id]

  instance_initiated_shutdown_behavior = "stop"

  block_device_mappings {
    device_name = "/dev/sda1" # root volume on Ubuntu HVM AMIs

    ebs {
      volume_size           = 30
      volume_type           = "gp3"
      delete_on_termination = true
      encrypted             = true
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2
  }

  # Nested virt is required for the Android emulator's KVM path on
  # virtualized m8i/c8i/r8i (Feb 2026 AWS feature, default-off). The
  # AWS provider doesn't expose `cpu_options.nested_virtualization`
  # yet (5.100.0); we set it via the AWS CLI in a post-create
  # null_resource against the running instance (stopped first by
  # null_resource.stop_on_create). Hacky but provider-version-independent.

  tag_specifications {
    resource_type = "instance"
    tags = merge(local.common_tags, {
      Name = "ace-mobile-emulator"
    })
  }

  tag_specifications {
    resource_type = "volume"
    tags = merge(local.common_tags, {
      Name = "ace-mobile-emulator-root"
    })
  }

  tags = local.common_tags
}

resource "aws_instance" "mobile" {
  launch_template {
    id      = aws_launch_template.mobile.id
    version = "$Latest"
  }

  subnet_id = local.subnet_id

  tags = merge(local.common_tags, {
    Name = "ace-mobile-emulator"
  })

  volume_tags = merge(local.common_tags, {
    Name = "ace-mobile-emulator-root"
  })

  lifecycle {
    ignore_changes = [
      # Don't fight ace-web / CloudWatch start-stop activity.
      # The instance state isn't a Terraform-managed attribute, but
      # tags applied at runtime (e.g., from autoscaling lifecycle) and
      # AMI changes would otherwise force replacement on every apply.
      ami,
      user_data,
    ]
  }
}

# Stop the instance once at create-time. Subsequent applies are no-ops.
# Idempotent: stop on an already-stopped instance returns success.
resource "null_resource" "stop_on_create" {
  triggers = {
    instance_id = aws_instance.mobile.id
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      aws ec2 stop-instances \
        --region ${var.region} \
        --instance-ids ${aws_instance.mobile.id} \
        > /dev/null
      aws ec2 wait instance-stopped \
        --region ${var.region} \
        --instance-ids ${aws_instance.mobile.id}
    EOT
  }

  depends_on = [aws_instance.mobile]
}

# Enable nested virtualization on the stopped instance. The AWS provider
# 5.100.0 doesn't expose this attribute yet; we set it via the CLI.
# Required for the Android emulator's KVM path on m8i/c8i/r8i (Feb 2026
# AWS feature, default-off). Re-runs are no-ops (modify-instance-attribute
# is idempotent).
resource "null_resource" "enable_nested_virt" {
  triggers = {
    instance_id = aws_instance.mobile.id
  }

  provisioner "local-exec" {
    command = <<-EOT
      aws ec2 modify-instance-cpu-options \
        --region ${var.region} \
        --instance-id ${aws_instance.mobile.id} \
        --nested-virtualization enabled
    EOT
  }

  depends_on = [null_resource.stop_on_create]
}
