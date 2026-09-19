locals {
  name_prefix = "${var.project_name}-${var.environment}"
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.name

  common_tags = merge(var.tags, {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })

  alert_actions = length(var.alert_email) > 0 ? [aws_sns_topic.alerts[0].arn] : []

  extraction_doc_types = toset([
    "lab_result",
    "doctors_notes",
    "injury_doc",
    "visit_assessment",
    "psych_eval",
  ])

  xray_actions = [
    "xray:PutTraceSegments",
    "xray:PutTelemetryRecords",
    "xray:GetSamplingRules",
    "xray:GetSamplingTargets",
  ]
}
