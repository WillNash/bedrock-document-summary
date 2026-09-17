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
  ]
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each = toset(local.lambda_function_names)

  name              = "/aws/lambda/${local.name_prefix}-${each.key}"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "step_functions" {
  name              = "/aws/states/${local.name_prefix}-pipeline"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}
