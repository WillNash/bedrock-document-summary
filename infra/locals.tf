locals {
  name_prefix = "${var.project_name}-${var.environment}"
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.name

  # Strip geo prefix (us., eu., au., jp., global.) to obtain the bare foundation-model IDs
  # needed for IAM resource ARNs — cross-region inference profiles check both the
  # inference-profile ARN and the underlying foundation-model ARN at invoke time.
  classifier_foundation_model_id = replace(var.bedrock_classifier_model_id, "/^(us|eu|au|jp|global)\\./", "")
  extractor_foundation_model_id  = replace(var.bedrock_model_id, "/^(us|eu|au|jp|global)\\./", "")

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

  # try() handles empty string or malformed JSON gracefully — falls back to DRAFT for each type.
  extraction_prompt_versions = try(jsondecode(var.extraction_prompt_versions_json), {})

  xray_actions = [
    "xray:PutTraceSegments",
    "xray:PutTelemetryRecords",
    "xray:GetSamplingRules",
    "xray:GetSamplingTargets",
  ]
}
