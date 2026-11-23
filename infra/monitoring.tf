# Logs, alarms (SNS e-mail) and the monthly budget.
# Without a load balancer, health comes from metrics the instance publishes every minute (files/health.sh)
# in the ACLOPI namespace: PlatformReady, AgentUp, VpnUp (1/0), plus mem_used_percent from the CloudWatch Agent.
# Missing data = instance off (out of hours) = not an alarm.

resource "aws_cloudwatch_log_group" "app" {
  for_each          = toset(["platform", "agent", "system"])
  name              = "/${var.project}/${each.key}"
  retention_in_days = 30
}

resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  alarms = {
    platform-not-ready = { metric = "PlatformReady", threshold = 1, op = "LessThanThreshold", periods = 5, stat = "Maximum", dims = {}, desc = "/health/ready has failed for 5 minutes while the instance is on" }
    agent-down         = { metric = "AgentUp", threshold = 1, op = "LessThanThreshold", periods = 5, stat = "Maximum", dims = {}, desc = "The platform cannot reach the agent service for 5 minutes" }
    vpn-down           = { metric = "VpnUp", threshold = 1, op = "LessThanThreshold", periods = 5, stat = "Maximum", dims = {}, desc = "No VPN tunnel for 5 minutes: the agent has no LLM (rule 3 decides)" }
    memory-high        = { metric = "mem_used_percent", threshold = 85, op = "GreaterThanThreshold", periods = 5, stat = "Average", dims = { AutoScalingGroupName = aws_autoscaling_group.platform.name }, desc = "Memory above 85% for 5 minutes" }
  }
}

resource "aws_cloudwatch_metric_alarm" "app" {
  for_each            = local.alarms
  alarm_name          = "${var.project}-${each.key}"
  alarm_description   = each.value.desc
  namespace           = "ACLOPI"
  metric_name         = each.value.metric
  dimensions          = each.value.dims
  statistic           = each.value.stat
  period              = 60
  evaluation_periods  = each.value.periods
  threshold           = each.value.threshold
  comparison_operator = each.value.op
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = var.project
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title   = "Platform, agent and VPN (1 = up)"
          region  = var.region
          stat    = "Maximum"
          period  = 60
          metrics = [["ACLOPI", "PlatformReady"], ["ACLOPI", "AgentUp"], ["ACLOPI", "VpnUp"]]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "CPU and memory (%)"
          region = var.region
          period = 60
          metrics = [
            ["AWS/EC2", "CPUUtilization", "AutoScalingGroupName", aws_autoscaling_group.platform.name],
            ["ACLOPI", "mem_used_percent", "AutoScalingGroupName", aws_autoscaling_group.platform.name],
          ]
        }
      },
    ]
  })
}

resource "aws_budgets_budget" "monthly" {
  name         = "${var.project}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
