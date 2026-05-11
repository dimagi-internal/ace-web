packer {
  required_version = ">= 1.10"

  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = "~> 1.3"
    }
  }
}

locals {
  ami_name = "${var.ami_name_prefix}-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"
}

data "amazon-ami" "ubuntu_noble" {
  filters = {
    name                = var.source_ami_filter_name
    root-device-type    = "ebs"
    virtualization-type = "hvm"
    architecture        = "x86_64"
  }
  most_recent = true
  owners      = [var.source_ami_owner]
  region      = var.region
}

source "amazon-ebs" "ace_mobile" {
  region        = var.region
  source_ami    = data.amazon-ami.ubuntu_noble.id
  instance_type = var.instance_type
  ssh_username  = "ubuntu"

  # c5n.metal is slower to stop than non-metal types (regularly 12-15
  # minutes vs the default 10-minute waiter). Without this block, packer
  # times out waiting for `instance-stopped` AFTER all provisioning has
  # succeeded — including the snapshot bake — and discards the work.
  # 30s × 60 attempts = 30 minutes, well above observed worst case.
  aws_polling {
    delay_seconds = 30
    max_attempts  = 60
  }

  # Need ample headroom for the Android SDK + emulator system image + APK +
  # AVD snapshot on the bake instance. The resulting AMI block-device
  # mapping inherits this size.
  launch_block_device_mappings {
    device_name           = "/dev/sda1"
    volume_size           = 30
    volume_type           = "gp3"
    delete_on_termination = true
  }

  ami_name        = local.ami_name
  ami_description = "ACE mobile emulator runner (Android 34 / Pixel 7 AVD, Maestro 1.39.x, CommCare 2.62.0, registered demo user snapshot)."

  tags = {
    Name       = local.ami_name
    owner      = "ace-web-mobile-poc"
    component  = "mobile-emulator"
    base-os    = "ubuntu-24.04"
    managed-by = "packer"
  }

  run_tags = {
    Name  = "${local.ami_name}-bake"
    owner = "ace-web-mobile-poc"
  }

  run_volume_tags = {
    Name  = "${local.ami_name}-bake-root"
    owner = "ace-web-mobile-poc"
  }
}

build {
  name = "ace-mobile"

  sources = ["source.amazon-ebs.ace_mobile"]

  # 00 — apt + KVM packages + JDK + base utils.
  provisioner "shell" {
    script          = "scripts/00-base.sh"
    execute_command = "sudo -E bash '{{ .Path }}'"
  }

  # 10 — Android SDK cmdline-tools, platform-tools, emulator, system image.
  provisioner "shell" {
    script          = "scripts/10-android-sdk.sh"
    execute_command = "sudo -E bash '{{ .Path }}'"
  }

  # 20 — create the AVD with the Pixel 7 profile + camera fix-up.
  provisioner "shell" {
    script          = "scripts/20-avd.sh"
    execute_command = "sudo -E bash '{{ .Path }}'"
  }

  # 30 — Maestro CLI to /opt/maestro.
  provisioner "shell" {
    script          = "scripts/30-maestro.sh"
    execute_command = "sudo -E bash '{{ .Path }}'"
  }

  # 40 — CommCare APKs (one or more versions) to /opt/ace/apks/<ver>/.
  provisioner "shell" {
    script          = "scripts/40-commcare-apk.sh"
    execute_command = "{{ .Vars }} sudo -E bash '{{ .Path }}'"
    environment_vars = [
      "COMMCARE_VERSIONS=${join(",", var.commcare_versions)}",
    ]
  }

  # Stage Maestro recipes, systemd units, idle script.
  # `source = "files/recipes"` (no trailing slash) + `destination =
  # "/tmp"` uploads the directory itself, so the recipes land at
  # /tmp/recipes/{connect-register-1-phone-entry,connect-register-2-app-lock}.yaml.
  # The trailing-slash variant requires the destination dir to already
  # exist on the remote — which it doesn't on a fresh bake instance.
  provisioner "file" {
    source      = "files/recipes"
    destination = "/tmp"
  }

  provisioner "file" {
    source      = "files/ace-mobile-runner.service"
    destination = "/tmp/ace-mobile-runner.service"
  }

  provisioner "file" {
    source      = "files/ace-idle-shutdown.service"
    destination = "/tmp/ace-idle-shutdown.service"
  }

  provisioner "file" {
    source      = "files/ace-idle-shutdown.timer"
    destination = "/tmp/ace-idle-shutdown.timer"
  }

  provisioner "file" {
    source      = "files/ace-idle-shutdown.sh"
    destination = "/tmp/ace-idle-shutdown.sh"
  }

  provisioner "file" {
    source      = "files/ace-emulator-launch"
    destination = "/tmp/ace-emulator-launch"
  }

  # 50 — write /opt/ace/states.yaml manifest. No emulator boot, no
  # snapshot bake — the runtime cold-boots + registers per state on
  # every instance launch. See docs/specs/2026-05-10-phase5-cloud-mobile-integration-design.md
  # for the design rationale.
  provisioner "shell" {
    script          = "scripts/50-bake-snapshot.sh"
    execute_command = "{{ .Vars }} sudo -E bash '{{ .Path }}'"
    environment_vars = [
      "COMMCARE_VERSIONS=${join(",", var.commcare_versions)}",
    ]
  }

  # 60 — install systemd units. Done after snapshot bake so the runner
  # service doesn't try to start during provisioning.
  provisioner "shell" {
    script          = "scripts/60-systemd.sh"
    execute_command = "sudo -E bash '{{ .Path }}'"
  }
}
