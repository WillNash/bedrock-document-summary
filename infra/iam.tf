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

resource "aws_iam_role" "lambda" {
  name               = "${local.name_prefix}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.common_tags
}

resource "aws_iam_role" "sfn" {
  name               = "${local.name_prefix}-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_trust.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "lambda_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = "arn:aws:logs:*:${local.account_id}:log-group:/aws/lambda/${local.name_prefix}-*:*"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_s3" {
  name = "s3-access"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "${aws_s3_bucket.uploads.arn}/*",
          "${aws_s3_bucket.summaries.arn}/*",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy" "lambda_dynamodb" {
  name = "dynamodb-jobs"
  role = aws_iam_role.lambda.id

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

resource "aws_iam_role_policy" "lambda_bedrock_runtime" {
  name = "bedrock-invoke"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_bedrock_prompt" {
  name = "bedrock-prompt-management"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["bedrock:GetPrompt"]
      Resource = [
        aws_bedrock_prompt.classifier.arn,
        aws_bedrock_prompt.lab_result.arn,
        aws_bedrock_prompt.doctors_notes.arn,
        aws_bedrock_prompt.injury_doc.arn,
        aws_bedrock_prompt.visit_assessment.arn,
        aws_bedrock_prompt.psych_eval.arn,
      ]
    }]
  })
}

resource "aws_iam_role_policy" "lambda_sfn" {
  name = "step-functions-start"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = aws_sfn_state_machine.pipeline.arn
    }]
  })
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
