data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "sfn_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

# ── api role (api_presign, api_status, api_summary) ──────────────────────────

resource "aws_iam_role" "api" {
  name               = "${local.name_prefix}-api-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "api_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.api.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = "arn:aws:logs:*:${local.account_id}:log-group:/aws/lambda/${local.name_prefix}-api-*:*"
    }]
  })
}

resource "aws_iam_role_policy" "api_dynamodb" {
  name = "dynamodb-jobs"
  role = aws_iam_role.api.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
      ]
      Resource = [
        aws_dynamodb_table.jobs.arn,
        "${aws_dynamodb_table.jobs.arn}/index/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "api_s3" {
  name = "s3-access"
  role = aws_iam_role.api.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.uploads.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.summaries.arn}/*"
      },
    ]
  })
}

resource "aws_iam_role_policy" "api_kms" {
  name = "kms-phi"
  role = aws_iam_role.api.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
      Resource = aws_kms_key.phi.arn
    }]
  })
}

resource "aws_iam_role_policy" "api_xray" {
  name = "xray"
  role = aws_iam_role.api.id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = local.xray_actions, Resource = "*" }]
  })
}

# ── pipeline_starter role ─────────────────────────────────────────────────────

resource "aws_iam_role" "pipeline_starter" {
  name               = "${local.name_prefix}-pipeline-starter-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "pipeline_starter_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.pipeline_starter.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = "arn:aws:logs:*:${local.account_id}:log-group:/aws/lambda/${local.name_prefix}-pipeline-starter:*"
    }]
  })
}

resource "aws_iam_role_policy" "pipeline_starter_dynamodb" {
  name = "dynamodb-jobs"
  role = aws_iam_role.pipeline_starter.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:UpdateItem"]
      Resource = aws_dynamodb_table.jobs.arn
    }]
  })
}

resource "aws_iam_role_policy" "pipeline_starter_sfn" {
  name = "step-functions-start"
  role = aws_iam_role.pipeline_starter.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = aws_sfn_state_machine.pipeline.arn
    }]
  })
}

resource "aws_iam_role_policy" "pipeline_starter_xray" {
  name = "xray"
  role = aws_iam_role.pipeline_starter.id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = local.xray_actions, Resource = "*" }]
  })
}

# ── processing role (classifier, extractor, validator, renderer) ──────────────

resource "aws_iam_role" "processing" {
  name               = "${local.name_prefix}-processing-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "processing_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.processing.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = [
        "arn:aws:logs:*:${local.account_id}:log-group:/aws/lambda/${local.name_prefix}-classifier:*",
        "arn:aws:logs:*:${local.account_id}:log-group:/aws/lambda/${local.name_prefix}-extractor:*",
        "arn:aws:logs:*:${local.account_id}:log-group:/aws/lambda/${local.name_prefix}-validator:*",
        "arn:aws:logs:*:${local.account_id}:log-group:/aws/lambda/${local.name_prefix}-renderer:*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "processing_dynamodb" {
  name = "dynamodb-jobs"
  role = aws_iam_role.processing.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:UpdateItem"]
      Resource = aws_dynamodb_table.jobs.arn
    }]
  })
}

resource "aws_iam_role_policy" "processing_s3" {
  name = "s3-access"
  role = aws_iam_role.processing.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.uploads.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.summaries.arn}/*"
      },
    ]
  })
}

resource "aws_iam_role_policy" "processing_bedrock_runtime" {
  name = "bedrock-invoke"
  role = aws_iam_role.processing.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = ["*"]
      },
      {
        Effect   = "Allow"
        Action   = ["aws-marketplace:ViewSubscriptions"]
        Resource = ["*"]
      },
    ]
  })
}

resource "aws_iam_role_policy" "processing_bedrock_prompt" {
  name = "bedrock-prompt-management"
  role = aws_iam_role.processing.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["bedrock:GetPrompt"]
      Resource = flatten([
        aws_bedrockagent_prompt.classifier.arn,
        [for k in local.extraction_doc_types : aws_bedrockagent_prompt.extraction[k].arn],
      ])
    }]
  })
}

resource "aws_iam_role_policy" "processing_bedrock_guardrail" {
  name = "bedrock-guardrail"
  role = aws_iam_role.processing.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:ApplyGuardrail"]
      Resource = "arn:aws:bedrock:${local.region}:${local.account_id}:guardrail/${var.guardrail_id}"
    }]
  })
}

resource "aws_iam_role_policy" "processing_kms" {
  name = "kms-phi"
  role = aws_iam_role.processing.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
      Resource = aws_kms_key.phi.arn
    }]
  })
}

resource "aws_iam_role_policy" "processing_xray" {
  name = "xray"
  role = aws_iam_role.processing.id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = local.xray_actions, Resource = "*" }]
  })
}

# ── fail_handler role ─────────────────────────────────────────────────────────

resource "aws_iam_role" "fail_handler" {
  name               = "${local.name_prefix}-fail-handler-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "fail_handler_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.fail_handler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = "arn:aws:logs:*:${local.account_id}:log-group:/aws/lambda/${local.name_prefix}-fail-handler:*"
    }]
  })
}

resource "aws_iam_role_policy" "fail_handler_dynamodb" {
  name = "dynamodb-jobs"
  role = aws_iam_role.fail_handler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:UpdateItem"]
      Resource = aws_dynamodb_table.jobs.arn
    }]
  })
}

resource "aws_iam_role_policy" "fail_handler_kms" {
  name = "kms-phi"
  role = aws_iam_role.fail_handler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
      Resource = aws_kms_key.phi.arn
    }]
  })
}

resource "aws_iam_role_policy" "fail_handler_xray" {
  name = "xray"
  role = aws_iam_role.fail_handler.id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = local.xray_actions, Resource = "*" }]
  })
}

# ── Step Functions role ───────────────────────────────────────────────────────

resource "aws_iam_role" "sfn" {
  name               = "${local.name_prefix}-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_trust.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "sfn_invoke_lambdas" {
  name = "invoke-lambdas"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["lambda:InvokeFunction"]
      Resource = [
        aws_lambda_function.classifier.arn,
        aws_lambda_function.extractor.arn,
        aws_lambda_function.validator.arn,
        aws_lambda_function.renderer.arn,
        aws_lambda_function.fail_handler.arn,
      ]
    }]
  })
}

resource "aws_iam_role_policy" "sfn_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogDelivery",
        "logs:PutLogEvents",
        "logs:GetLogDelivery",
        "logs:UpdateLogDelivery",
        "logs:DeleteLogDelivery",
        "logs:ListLogDeliveries",
        "logs:PutResourcePolicy",
        "logs:DescribeResourcePolicies",
        "logs:DescribeLogGroups",
      ]
      Resource = "*"
    }]
  })
}
