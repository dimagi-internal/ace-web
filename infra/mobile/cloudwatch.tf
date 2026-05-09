# Layer-3 backstop. If the in-VM idle watchdog (`ace-idle-shutdown.timer`,
# 5-minute window) fails to fire — kernel panic, watchdog disabled, etc —
# this CloudWatch alarm will stop the instance after 5 consecutive 1-minute
# periods of CPUUtilization < 5% (Maximum statistic, so a single spike
# resets the window).
#
# Tightened from 30 min → 5 min on 2026-05-09 per operator request: the
# safety-net should be aggressive so a bug in layers 1/2 can't quietly
# leak hours of EC2 charges. A live recipe run keeps CPU well above 5%
# (emulator + Maestro), so a 5-min idle window during an active run is
# only possible if something has already gone wrong.
#
# The alarm action `arn:aws:automate:<region>:ec2:stop` is the AWS-builtin
# auto-stop action — no Lambda or SNS in the loop.

resource "aws_cloudwatch_metric_alarm" "idle_stop" {
  alarm_name        = "ace-mobile-emulator-idle-stop-${var.env_suffix}"
  alarm_description = "Stop the ACE mobile emulator after 5 min of <5% CPU."

  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 5
  comparison_operator = "LessThanThreshold"

  treat_missing_data = "notBreaching"

  dimensions = {
    InstanceId = aws_instance.mobile.id
  }

  alarm_actions = [
    "arn:${data.aws_partition.current.partition}:automate:${var.region}:ec2:stop",
  ]

  tags = local.common_tags
}
