locals {
  lambda_function_names = [
    "api-presign",
    "api-status",
    "api-summary",
    "pipeline-starter",
    "classifier",
    "extractor",
    "validator",
    "renderer",
    "fail-handler",
    "comparator",
    "gold-comparator",
    "experiment-starter",
    "summary-collector",
    "variance-scorer",
    "gold-scorer",
    "report-generator",
    "report-writer",
    "comparison-fail-handler",
  ]

  sfn_names = ["pipeline", "comparison"]
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each = toset(local.lambda_function_names)

  name              = "/aws/lambda/${local.name_prefix}-${each.key}"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "step_functions" {
  for_each = toset(local.sfn_names)

  name              = "/aws/states/${local.name_prefix}-${each.key}"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}
