variable "alert_email" {
  type        = string
  description = "Email address for operational and cost anomaly alerts"
  default     = ""
}

# ── Pipeline failure alarm ───────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "sfn_failures" {
  alarm_name          = "${local.name_prefix}-pipeline-failures"
  alarm_description   = "Step Functions executions are failing — documents are not being processed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.pipeline.arn
  }

  alarm_actions = length(var.alert_email) > 0 ? [aws_sns_topic.alerts[0].arn] : []

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "sfn_throttled" {
  alarm_name          = "${local.name_prefix}-pipeline-throttled"
  alarm_description   = "Step Functions executions are being throttled — possible Bedrock throttling or concurrency limits"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ExecutionThrottled"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.pipeline.arn
  }

  alarm_actions = length(var.alert_email) > 0 ? [aws_sns_topic.alerts[0].arn] : []

  tags = local.common_tags
}

# ── DLQ depth alarm ──────────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "pipeline_starter_dlq" {
  alarm_name          = "${local.name_prefix}-pipeline-starter-dlq"
  alarm_description   = "Messages in pipeline_starter DLQ — documents were uploaded but pipeline did not start"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.pipeline_starter_dlq.name
  }

  alarm_actions = length(var.alert_email) > 0 ? [aws_sns_topic.alerts[0].arn] : []

  tags = local.common_tags
}

# ── Lambda error alarms ──────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "api_presign_errors" {
  alarm_name          = "${local.name_prefix}-api-presign-errors"
  alarm_description   = "api_presign Lambda errors — users cannot upload documents"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.api_presign.function_name
  }

  alarm_actions = length(var.alert_email) > 0 ? [aws_sns_topic.alerts[0].arn] : []

  tags = local.common_tags
}

# ── SNS topic for alerts ─────────────────────────────────────────────────────

resource "aws_sns_topic" "alerts" {
  count = length(var.alert_email) > 0 ? 1 : 0
  name  = "${local.name_prefix}-alerts"
  tags  = local.common_tags
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = length(var.alert_email) > 0 ? 1 : 0
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── Cost Anomaly Detection ───────────────────────────────────────────────────

resource "aws_ce_anomaly_monitor" "services" {
  name              = "${local.name_prefix}-service-monitor"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "alerts" {
  count     = length(var.alert_email) > 0 ? 1 : 0
  name      = "${local.name_prefix}-cost-anomaly-alert"
  frequency = "DAILY"

  monitor_arn_list = [aws_ce_anomaly_monitor.services.arn]

  subscriber {
    type    = "EMAIL"
    address = var.alert_email
  }

  threshold_expression {
    and {
      dimension {
        key           = "ANOMALY_TOTAL_IMPACT_PERCENTAGE"
        values        = ["50"]
        match_options = ["GREATER_THAN_OR_EQUAL"]
      }
      dimension {
        key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
        values        = ["10"]
        match_options = ["GREATER_THAN_OR_EQUAL"]
      }
    }
  }
}

# ── DLQ + Lambda async event destination ────────────────────────────────────

resource "aws_sqs_queue" "pipeline_starter_dlq" {
  name                      = "${local.name_prefix}-pipeline-starter-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = local.common_tags
}

resource "aws_iam_role_policy" "pipeline_starter_dlq" {
  name = "dlq-send"
  role = aws_iam_role.pipeline_starter.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = aws_sqs_queue.pipeline_starter_dlq.arn
    }]
  })
}

resource "aws_lambda_function_event_invoke_config" "pipeline_starter" {
  function_name          = aws_lambda_function.pipeline_starter.function_name
  maximum_retry_attempts = 2

  destination_config {
    on_failure {
      destination = aws_sqs_queue.pipeline_starter_dlq.arn
    }
  }
}
