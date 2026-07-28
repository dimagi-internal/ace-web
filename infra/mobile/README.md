# `infra/mobile/` — AWS infra for the ACE mobile cloud runner

This stack provisions the EC2 instance, S3 artifacts bucket, IAM policies,
and CloudWatch idle-stop alarm that back the `/api/mobile/*` endpoints in
ace-web. The AMI baked by `infra/mobile-ami/` is the input.

**One instance, one bucket, one alarm, two IAM principals.** No SSH key,
no ALB, no inbound security-group rule. Access to the running instance is
exclusively through SSM Session Manager.

---

## Prerequisites

- AWS credentials with permission to create EC2 / IAM / S3 / CloudWatch in
  the target account (the ACE labs account, `858923557655`).
- Terraform `>= 1.6` (a `.terraform-version` file pins the recommended
  release).
- The AMI ID emitted by `cd ../mobile-ami && packer build ...`. Without
  the AMI, `terraform apply` will fail at the `aws_launch_template`
  validation step.
- The default VPC in the target region has at least one subnet with
  outbound 443 to the public internet (SSM endpoints, S3, package
  mirrors). If you don't have a default VPC, set `vpc_id` and `subnet_id`
  in `terraform.tfvars`.

---

## One-time apply runbook

1. **Bake the AMI first.** See `../mobile-ami/README.md`. You'll come back
   here with an AMI ID like `ami-0abcdef1234567890` and a version tag
   (e.g., `2026-05-09-1`).

2. **Create `terraform.tfvars`** (gitignored — never commit):
   ```hcl
   region      = "us-east-1"
   env_suffix  = "labs"
   ami_id      = "ami-0abcdef1234567890"   # from packer
   ami_version = "2026-05-09-1"            # human-readable

   # Optional — leave unset to use the default VPC.
   # vpc_id    = "vpc-0123..."
   # subnet_id = "subnet-0456..."

   # Optional — name of the existing ace-web ECS task role.
   # ace_web_task_role_name = "labs-jj-ecs-task-role"
   ```

3. **Init + apply.**
   ```bash
   cd infra/mobile
   terraform init
   terraform plan -out=apply.tfplan
   terraform apply apply.tfplan
   ```
   The plan should show:
   - 1 × `aws_instance` (the runner, will create then immediately stop)
   - 1 × `aws_launch_template`
   - 1 × `aws_security_group` (egress only)
   - 1 × `aws_s3_bucket` + lifecycle/encryption/versioning/PAB controls
   - 2 × `aws_iam_role` / 1 × `aws_iam_policy` / 1 × `aws_iam_instance_profile`
   - 1 × `aws_cloudwatch_metric_alarm`
   - 1 × `null_resource` (calls `aws ec2 stop-instances` on create)

4. **Capture outputs.** Run `terraform output -json > /tmp/mobile-outputs.json`.
   The interesting values are `instance_id`, `artifacts_bucket_name`,
   `task_addon_policy_arn`, and the assembled `env_for_task_definition`
   block.

---

## Post-apply: wire the IAM policy to the ace-web task role

The Terraform creates the customer-managed policy
`ace-mobile-task-addon-<env_suffix>` but **does not attach it** to the
ace-web ECS task role. The task role itself is owned by another stack;
attaching it here would import a resource we don't manage.

```bash
TASK_ROLE=$(aws cloudformation describe-stacks --stack-name ace-web \
  --region us-east-1 --query \
  "Stacks[0].Parameters[?ParameterKey=='TaskRoleArn'].ParameterValue" \
  --output text | sed -E 's|.*role/||')
POLICY_ARN=$(terraform output -raw task_addon_policy_arn)

aws iam attach-role-policy \
  --role-name "$TASK_ROLE" \
  --policy-arn "$POLICY_ARN"
```

Run `aws iam list-attached-role-policies --role-name "$TASK_ROLE"` to
confirm.

## Post-apply: edit `deploy/aws/ace-web.cfn.yaml`

Append three env vars to the ace-web container's `Environment` list
(CloudFormation owns the task definition — this is the only place they take
effect):

```yaml
- Name: ACE_MOBILE_AWS_REGION
  Value: "us-east-1"
- Name: ACE_MOBILE_INSTANCE_ID
  Value: "i-0abc..."
- Name: ACE_MOBILE_S3_BUCKET
  Value: "ace-mobile-artifacts-labs"
{ "name": "ACE_MOBILE_AMI_VERSION", "value": "2026-05-09-1" }
```

(The `env_for_task_definition` Terraform output contains the exact values
to paste.)

Then redeploy ace-web:

```bash
gh workflow run deploy-labs.yml --ref main -f run_migrations=false
```

---

## Smoke test (success bar #4)

After the deploy completes:

```bash
# 1. Mint a personal token if you don't already have one in your env.
#    See /ace-web:create-cli-credentials or the ace-web-pat-mint skill.
export ACE_WEB_PAT_TOKEN=...

# 2. Boot the instance.
curl -X POST https://labs.connect.dimagi.com/ace/api/mobile/ensure-running \
  -H "Authorization: Bearer $ACE_WEB_PAT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Expected: `{"data": {"instance_id": "i-...", "state": "running",
"public_dns": "...", "started_at": "..."}, "error": null}` after ~90 s.
The first call cold-starts the EC2 instance + waits for the SSM agent +
verifies `sys.boot_completed` inside the AVD; subsequent calls within
the 5-minute idle window return immediately.

```bash
# 3. Confirm the CloudWatch alarm is wired up.
aws cloudwatch describe-alarms \
  --alarm-names "ace-mobile-emulator-idle-stop-labs" \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Action:AlarmActions}'
```

You should see the `ec2:stop` action in the `Action` field.

---

## Auto-stop verification (success bar #5)

The plan calls for "kill ace-web mid-run, verify stop within 40 min."
Manual smoke:

1. Trigger `/api/mobile/ensure-running` to bring the instance up.
2. `aws ec2 describe-instances --instance-ids <id> --query 'Reservations[].Instances[].State'`
   confirms `running`.
3. Don't issue any further requests for 40 minutes.
4. Re-run the describe; expected state is `stopped`. Either the in-VM
   idle watchdog (5 min, layer 2) or the CloudWatch alarm (5 min,
   layer 3) will have fired.

---

## Rollback / teardown

```bash
# Terraform destroy stops + terminates the instance, deletes the bucket
# (you'll need to empty it first if it has objects), and removes the IAM
# policies. Detach the add-on policy from the ace-web task role first:
aws iam detach-role-policy \
  --role-name "$TASK_ROLE" \
  --policy-arn "$POLICY_ARN"

# Empty the artifacts bucket (objects don't delete with the bucket if
# any exist).
aws s3 rm s3://"$(terraform output -raw artifacts_bucket_name)" --recursive

terraform destroy
```

---

## Notes

- **Why `m8i.xlarge`?** It's the smallest m8i exposing nested virt for
  KVM. The Packer bake runs `kvm-ok` early; if it ever fails, the
  fallbacks (in cost order) are `c8i.xlarge` and `m7i.metal-24xl`. Update
  `instance_type` in `terraform.tfvars` and re-apply.
- **Why no SSH?** SSM Session Manager covers the same ground without
  having to manage keys, security groups, or bastions. To shell in:
  `aws ssm start-session --target $(terraform output -raw instance_id)`.
- **Why does Terraform stop the instance immediately on create?** The
  POC budget is one instance, idle most of the time. ace-web boots it
  on demand via `/api/mobile/ensure-running`. Leaving it running after
  apply would burn ~$0.16/hour for nothing. See the comment block at
  the top of `ec2.tf`.
- **Versioned AMIs.** `var.ami_version` is a label, not a constraint.
  Bumping it requires a re-apply (the `aws_launch_template` notices the
  `ami_id` change). Existing instances keep their old AMI until next
  stop/start cycle, since `aws_instance.lifecycle.ignore_changes`
  includes `ami` to prevent terraform from replacing them.
