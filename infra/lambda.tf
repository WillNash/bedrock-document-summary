# Lambda layer for shared Python dependencies (jinja2, jsonschema).
# Run scripts/build_lambdas.sh before terraform apply to create this file.
resource "aws_lambda_layer_version" "deps" {
  filename                 = "${path.module}/lambda_packages/layer.zip"
  layer_name               = "${local.name_prefix}-deps"
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["arm64"]
  description              = "jinja2 and jsonschema for renderer and validator Lambdas"

  lifecycle {
    create_before_destroy = true
  }
}

# ── Archive data sources ────────────────────────────────────────────────────

data "archive_file" "api_presign" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/api_presign"
  output_path = "${path.module}/lambda_packages/api_presign.zip"
}

data "archive_file" "api_status" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/api_status"
  output_path = "${path.module}/lambda_packages/api_status.zip"
}

data "archive_file" "api_summary" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/api_summary"
  output_path = "${path.module}/lambda_packages/api_summary.zip"
}

data "archive_file" "pipeline_starter" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/pipeline_starter"
  output_path = "${path.module}/lambda_packages/pipeline_starter.zip"
}

data "archive_file" "classifier" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/classifier"
  output_path = "${path.module}/lambda_packages/classifier.zip"
}

# Extractor and validator: bundle schemas/ alongside handler.py
data "archive_file" "extractor" {
  type        = "zip"
  output_path = "${path.module}/lambda_packages/extractor.zip"

  source {
    content  = file("${path.module}/../lambda/extractor/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../schemas/lab_result_schema.json")
    filename = "schemas/lab_result_schema.json"
  }
  source {
    content  = file("${path.module}/../schemas/doctors_notes_schema.json")
    filename = "schemas/doctors_notes_schema.json"
  }
  source {
    content  = file("${path.module}/../schemas/injury_doc_schema.json")
    filename = "schemas/injury_doc_schema.json"
  }
  source {
    content  = file("${path.module}/../schemas/visit_assessment_schema.json")
    filename = "schemas/visit_assessment_schema.json"
  }
  source {
    content  = file("${path.module}/../schemas/psych_eval_schema.json")
    filename = "schemas/psych_eval_schema.json"
  }
}

data "archive_file" "validator" {
  type        = "zip"
  output_path = "${path.module}/lambda_packages/validator.zip"

  source {
    content  = file("${path.module}/../lambda/validator/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../schemas/lab_result_schema.json")
    filename = "schemas/lab_result_schema.json"
  }
  source {
    content  = file("${path.module}/../schemas/doctors_notes_schema.json")
    filename = "schemas/doctors_notes_schema.json"
  }
  source {
    content  = file("${path.module}/../schemas/injury_doc_schema.json")
    filename = "schemas/injury_doc_schema.json"
  }
  source {
    content  = file("${path.module}/../schemas/visit_assessment_schema.json")
    filename = "schemas/visit_assessment_schema.json"
  }
  source {
    content  = file("${path.module}/../schemas/psych_eval_schema.json")
    filename = "schemas/psych_eval_schema.json"
  }
}

# Renderer: bundle templates/ alongside handler.py
data "archive_file" "renderer" {
  type        = "zip"
  output_path = "${path.module}/lambda_packages/renderer.zip"

  source {
    content  = file("${path.module}/../lambda/renderer/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../templates/lab_result.j2")
    filename = "templates/lab_result.j2"
  }
  source {
    content  = file("${path.module}/../templates/doctors_notes.j2")
    filename = "templates/doctors_notes.j2"
  }
  source {
    content  = file("${path.module}/../templates/injury_doc.j2")
    filename = "templates/injury_doc.j2"
  }
  source {
    content  = file("${path.module}/../templates/visit_assessment.j2")
    filename = "templates/visit_assessment.j2"
  }
  source {
    content  = file("${path.module}/../templates/psych_eval.j2")
    filename = "templates/psych_eval.j2"
  }
}

data "archive_file" "fail_handler" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/fail_handler"
  output_path = "${path.module}/lambda_packages/fail_handler.zip"
}

# ── Lambda functions ────────────────────────────────────────────────────────

resource "aws_lambda_function" "api_presign" {
  function_name    = "${local.name_prefix}-api-presign"
  filename         = data.archive_file.api_presign.output_path
  source_code_hash = data.archive_file.api_presign.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.api.arn
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      UPLOAD_BUCKET         = aws_s3_bucket.uploads.bucket
      JOBS_TABLE            = aws_dynamodb_table.jobs.name
      UPLOAD_MAX_SIZE_BYTES = tostring(var.upload_max_size_bytes)
      DAILY_UPLOAD_LIMIT    = tostring(var.daily_upload_limit)
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["api-presign"].name
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

resource "aws_lambda_function" "api_status" {
  function_name    = "${local.name_prefix}-api-status"
  filename         = data.archive_file.api_status.output_path
  source_code_hash = data.archive_file.api_status.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.api.arn
  timeout          = 10
  memory_size      = 128

  environment {
    variables = {
      JOBS_TABLE = aws_dynamodb_table.jobs.name
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["api-status"].name
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

resource "aws_lambda_function" "api_summary" {
  function_name    = "${local.name_prefix}-api-summary"
  filename         = data.archive_file.api_summary.output_path
  source_code_hash = data.archive_file.api_summary.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.api.arn
  timeout          = 15
  memory_size      = 128

  environment {
    variables = {
      JOBS_TABLE       = aws_dynamodb_table.jobs.name
      SUMMARIES_BUCKET = aws_s3_bucket.summaries.bucket
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["api-summary"].name
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

resource "aws_lambda_function" "pipeline_starter" {
  function_name    = "${local.name_prefix}-pipeline-starter"
  filename         = data.archive_file.pipeline_starter.output_path
  source_code_hash = data.archive_file.pipeline_starter.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.pipeline_starter.arn
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      STATE_MACHINE_ARN = aws_sfn_state_machine.pipeline.arn
      JOBS_TABLE        = aws_dynamodb_table.jobs.name
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["pipeline-starter"].name
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

resource "aws_lambda_function" "classifier" {
  function_name                  = "${local.name_prefix}-classifier"
  filename                       = data.archive_file.classifier.output_path
  source_code_hash               = data.archive_file.classifier.output_base64sha256
  handler                        = "handler.lambda_handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  role                           = aws_iam_role.processing.arn
  timeout                        = 60
  memory_size                    = 512
  reserved_concurrent_executions = var.processing_concurrency

  environment {
    variables = {
      BEDROCK_CLASSIFIER_MODEL_ID = var.bedrock_classifier_model_id
      CLASSIFIER_PROMPT_ARN       = aws_bedrock_prompt.classifier.arn
      CLASSIFIER_PROMPT_VERSION   = aws_bedrock_prompt_version.classifier.version
      GUARDRAIL_ID                = aws_bedrock_guardrail.main.guardrail_id
      GUARDRAIL_VERSION           = aws_bedrock_guardrail_version.main.version
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["classifier"].name
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

resource "aws_lambda_function" "extractor" {
  function_name                  = "${local.name_prefix}-extractor"
  filename                       = data.archive_file.extractor.output_path
  source_code_hash               = data.archive_file.extractor.output_base64sha256
  handler                        = "handler.lambda_handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  role                           = aws_iam_role.processing.arn
  timeout                        = 120
  memory_size                    = 512
  reserved_concurrent_executions = var.processing_concurrency

  environment {
    variables = {
      BEDROCK_MODEL_ID    = var.bedrock_model_id
      GUARDRAIL_ID        = aws_bedrock_guardrail.main.guardrail_id
      GUARDRAIL_VERSION   = aws_bedrock_guardrail_version.main.version
      PROMPT_ARNS_JSON = jsonencode({
        lab_result       = aws_bedrock_prompt.lab_result.arn
        doctors_notes    = aws_bedrock_prompt.doctors_notes.arn
        injury_doc       = aws_bedrock_prompt.injury_doc.arn
        visit_assessment = aws_bedrock_prompt.visit_assessment.arn
        psych_eval       = aws_bedrock_prompt.psych_eval.arn
      })
      PROMPT_VERSIONS_JSON = jsonencode({
        lab_result       = aws_bedrock_prompt_version.lab_result.version
        doctors_notes    = aws_bedrock_prompt_version.doctors_notes.version
        injury_doc       = aws_bedrock_prompt_version.injury_doc.version
        visit_assessment = aws_bedrock_prompt_version.visit_assessment.version
        psych_eval       = aws_bedrock_prompt_version.psych_eval.version
      })
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["extractor"].name
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

resource "aws_lambda_function" "validator" {
  function_name    = "${local.name_prefix}-validator"
  filename         = data.archive_file.validator.output_path
  source_code_hash = data.archive_file.validator.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.processing.arn
  timeout          = 30
  memory_size      = 256
  layers           = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = {
      JOBS_TABLE = aws_dynamodb_table.jobs.name
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["validator"].name
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

resource "aws_lambda_function" "renderer" {
  function_name    = "${local.name_prefix}-renderer"
  filename         = data.archive_file.renderer.output_path
  source_code_hash = data.archive_file.renderer.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.processing.arn
  timeout          = 30
  memory_size      = 256
  layers           = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = {
      SUMMARIES_BUCKET = aws_s3_bucket.summaries.bucket
      JOBS_TABLE       = aws_dynamodb_table.jobs.name
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["renderer"].name
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}

resource "aws_lambda_function" "fail_handler" {
  function_name    = "${local.name_prefix}-fail-handler"
  filename         = data.archive_file.fail_handler.output_path
  source_code_hash = data.archive_file.fail_handler.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.fail_handler.arn
  timeout          = 15
  memory_size      = 128

  environment {
    variables = {
      JOBS_TABLE = aws_dynamodb_table.jobs.name
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["fail-handler"].name
  }

  depends_on = [aws_cloudwatch_log_group.lambda]

  tags = local.common_tags
}
