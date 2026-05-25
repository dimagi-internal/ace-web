variable "region" {
  type    = string
  default = "us-east-1"
}

variable "source_ami_filter_name" {
  description = "Name pattern for the Ubuntu 24.04 (noble) source AMI."
  type        = string
  # Canonical's official AMI naming convention.
  default = "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"
}

variable "source_ami_owner" {
  description = "Canonical's AWS account ID."
  type        = string
  default     = "099720109477"
}

variable "instance_type" {
  description = <<-EOT
    Instance type for the bake. Must expose nested virtualization for KVM
    (the `00-base.sh` script runs `kvm-ok`).

    Default `c5n.metal` (~$3.89/hr) is the cheapest x86 bare-metal type
    in us-east-1; bare metal always exposes nested virt. We don't use a
    smaller virtualized type (m8i.xlarge / c8i.xlarge with the
    `cpu_options.nested_virtualization=enabled` flag) for the bake
    because Packer's amazon-ebs builder doesn't expose `cpu_options`.

    Bake is ~25 min one-time per AMI rebuild (~$1.62). The *runtime*
    instance the Terraform stack creates is m8i.xlarge with nested
    virt enabled, so per-run cost is unaffected.
  EOT
  type        = string
  default     = "c5n.metal"
}

variable "ami_name_prefix" {
  type    = string
  default = "ace-mobile-emulator"
}

variable "commcare_versions" {
  description = <<-EOT
    Ordered list of CommCare APK versions to bake into this AMI. The first
    entry becomes the AMI's `default` state (loaded by the systemd runner
    on boot). Each entry produces:
      - /opt/ace/apks/<version>/commcare.apk
      - an AVD snapshot named `cc-<version>-registered` with the demo
        user pre-registered via the +7426 bypass
      - an entry in /opt/ace/states.yaml
    ace-web's /api/mobile/states reads states.yaml to surface available
    runtime states; ace-web's /api/mobile/ensure-running with
    `state="cc-<version>"` switches to a different one.
    Bake time grows roughly linearly with the list length (~5 min per
    version on c5n.metal).
  EOT
  type        = list(string)
  default     = ["2.63.0", "2.62.0"]
}

# ---------------------------------------------------------------------------
# Test-user credentials. Sourced from 1Password by the operator before
# `packer build`. NEVER set defaults to real values — the README shows
# how to inject them via `packer build -var=...` or env vars.
# ---------------------------------------------------------------------------

# Test-user creds USED to be passed to the bake (back when the bake
# saved a snapshot of the registered state). Now the runtime cold-boots
# and registers on every instance launch, reading creds from AWS
# Secrets Manager (`ace-mobile-test-user-creds`). The bake no longer
# needs them. Variables removed; secret is provisioned out-of-band
# via `aws secretsmanager create-secret` — see
# docs/specs/2026-05-10-phase5-cloud-mobile-integration-design.md.
