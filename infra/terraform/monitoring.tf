# Alarms, dashboard and backups (E30 FR-30-3, FR-30-4).
#
# Application metrics (namespace "TutorTrack", dimension Environment) are written every
# minute by the beat task `platform_admin.tasks.emit_metrics` in CloudWatch embedded metric
# format, so they need no agent. Paging alarms go to PagerDuty; everything else to email.

resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-alerts"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic" "paging" {
  name              = "${local.name}-paging"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic_subscription" "paging" {
  count                  = var.pagerduty_endpoint == "" ? 0 : 1
  topic_arn              = aws_sns_topic.paging.arn
  protocol               = "https"
  endpoint               = var.pagerduty_endpoint
  endpoint_auto_confirms = true
}

locals {
  app_metric = { Environment = var.environment }
  # name => [metric, threshold, periods of 1 minute, paging?, description]
  app_alarms = {
    outbox-lag          = ["OutboxLagSeconds", 60, 5, true, "Domain events are more than 60s behind (outbox lag SLO)"]
    dead-letters        = ["OutboxDeadLetters", 0, 1, false, "Events were dead-lettered: replay from the platform console"]
    payment-webhooks    = ["PaymentWebhookBacklog", 50, 15, true, "Payment webhooks are not being processed"]
    billing-webhooks    = ["BillingWebhookBacklog", 20, 15, false, "Stripe Billing webhooks are not being processed"]
    celery-queue-depth  = ["CeleryQueueDepth", 1000, 10, false, "Background jobs are queuing up"]
  }
}

resource "aws_cloudwatch_metric_alarm" "app" {
  for_each = local.app_alarms

  alarm_name          = "${local.name}-${each.key}"
  alarm_description   = each.value[4]
  namespace           = "TutorTrack"
  metric_name         = each.value[0]
  dimensions          = local.app_metric
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = each.value[2]
  threshold           = each.value[1]
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching" # no metrics = beat is down
  alarm_actions       = [each.value[3] ? aws_sns_topic.paging.arn : aws_sns_topic.alerts.arn]
  ok_actions          = [each.value[3] ? aws_sns_topic.paging.arn : aws_sns_topic.alerts.arn]
}

# API availability SLO: 5xx below 1% of requests over 5 minutes.
resource "aws_cloudwatch_metric_alarm" "api_errors" {
  alarm_name          = "${local.name}-api-5xx-rate"
  alarm_description   = "More than 1% of API requests are failing"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.paging.arn]
  ok_actions          = [aws_sns_topic.paging.arn]

  metric_query {
    id          = "rate"
    expression  = "100 * errors / MAX([requests, 1])"
    label       = "5xx %"
    return_data = true
  }
  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_Target_5XX_Count"
      dimensions  = { LoadBalancer = aws_lb.main.arn_suffix }
      period      = 60
      stat        = "Sum"
    }
  }
  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "RequestCount"
      dimensions  = { LoadBalancer = aws_lb.main.arn_suffix }
      period      = 60
      stat        = "Sum"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "api_latency" {
  alarm_name          = "${local.name}-api-latency-p95"
  alarm_description   = "API p95 latency above 1.5s"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix }
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 10
  threshold           = 1.5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  alarm_name          = "${local.name}-unhealthy-web"
  alarm_description   = "Web tasks are failing health checks"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.web.arn_suffix }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.paging.arn]
}

resource "aws_cloudwatch_metric_alarm" "db_cpu" {
  alarm_name          = "${local.name}-db-cpu"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "db_storage" {
  alarm_name          = "${local.name}-db-free-storage"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10 * 1024 * 1024 * 1024
  comparison_operator = "LessThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.name
  dashboard_body = jsonencode({
    widgets = [
      for i, w in [
        ["API requests and 5xx", [["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.main.arn_suffix], [".", "HTTPCode_Target_5XX_Count", ".", "."]], "Sum"],
        ["API latency p95", [["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.main.arn_suffix]], "p95"],
        ["Outbox", [["TutorTrack", "OutboxLagSeconds", "Environment", var.environment], [".", "OutboxPending", ".", "."], [".", "OutboxDeadLetters", ".", "."]], "Maximum"],
        ["Queues and webhooks", [["TutorTrack", "CeleryQueueDepth", "Environment", var.environment], [".", "PaymentWebhookBacklog", ".", "."], [".", "BillingWebhookBacklog", ".", "."]], "Maximum"],
        ["Database", [["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.postgres.identifier], [".", "DatabaseConnections", ".", "."]], "Average"],
      ] : {
        type   = "metric"
        x      = (i % 2) * 12
        y      = floor(i / 2) * 6
        width  = 12
        height = 6
        properties = {
          title   = w[0]
          metrics = w[1]
          stat    = w[2]
          period  = 60
          region  = var.region
        }
      }
    ]
  })
}

# --- Backups (FR-30-4): RDS keeps 35 days of PITR; AWS Backup takes daily snapshots and
# copies them to a vault in the separate backup account. -----------------------------------------

resource "aws_backup_vault" "main" {
  name        = "${local.name}-backups"
  kms_key_arn = aws_kms_key.app_data.arn
}

resource "aws_backup_plan" "daily" {
  name = "${local.name}-daily"

  rule {
    rule_name         = "daily"
    target_vault_name = aws_backup_vault.main.name
    schedule          = "cron(0 3 * * ? *)"

    lifecycle {
      delete_after = 35
    }

    dynamic "copy_action" {
      for_each = var.backup_copy_vault_arn == "" ? [] : [var.backup_copy_vault_arn]
      content {
        destination_vault_arn = copy_action.value
        lifecycle {
          delete_after = 365
        }
      }
    }
  }
}

resource "aws_iam_role" "backup" {
  name = "${local.name}-backup"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_backup_selection" "db" {
  name         = "${local.name}-db"
  plan_id      = aws_backup_plan.daily.id
  iam_role_arn = aws_iam_role.backup.arn
  resources    = [aws_db_instance.postgres.arn, aws_s3_bucket.uploads.arn]
}
