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
    (the `00-base.sh` script runs `kvm-ok`). m8i.xlarge is the cheapest
    member of the m8i family that supports it. If KVM fails on bake,
    fallbacks are `c8i.xlarge` (cheaper) or `m7i.metal-24xl` (bare metal).
  EOT
  type        = string
  default     = "m8i.xlarge"
}

variable "ami_name_prefix" {
  type    = string
  default = "ace-mobile-emulator"
}

# ---------------------------------------------------------------------------
# Test-user credentials. Sourced from 1Password by the operator before
# `packer build`. NEVER set defaults to real values — the README shows
# how to inject them via `packer build -var=...` or env vars.
# ---------------------------------------------------------------------------

variable "test_phone_local" {
  description = "Local digits of the demo phone (no `+`, no country code). e.g., 4260000100. The combined COUNTRY_CODE+PHONE_LOCAL must start with `+7426` for the Connect-id demo-bypass to skip OTP."
  type        = string
  sensitive   = true
}

variable "test_country_code" {
  description = "Country-code prefix of the demo phone, including the `+`. Typically `+7` for the +7426 demo range."
  type        = string
  sensitive   = true
}

variable "test_pin" {
  description = "4-digit PIN that backs the App Lock setup. e.g., 1234"
  type        = string
  sensitive   = true
}

variable "test_backup_code" {
  description = "6-digit numeric backup code for ConnectID."
  type        = string
  sensitive   = true
}

variable "test_name" {
  description = "Display name written to ConnectID. e.g., \"ACE Test User\"."
  type        = string
  default     = "ACE Test User"
}
