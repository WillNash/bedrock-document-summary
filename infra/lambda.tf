# Lambda layer for shared Python dependencies (jinja2, jsonschema).
# Run scripts/build_lambdas.sh before terraform apply to create this file.
resource "aws_lambda_layer_version" "deps" {
  filename                 = "${path.module}/lambda_packages/layer.zip"
  source_code_hash         = filebase64sha256("${path.module}/lambda_packages/layer.zip")
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

data "archive_file" "api_experiment_status" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/api_experiment_status"
  output_path = "${path.module}/lambda_packages/api_experiment_status.zip"
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

# Extractor and validator: bundle schemas/ alongside handler.py.
# dynamic "source" iterates local.extraction_doc_types so adding a new doc
# type here is automatic once the type is added to that set in bedrock.tf.
data "archive_file" "extractor" {
  type        = "zip"
  output_path = "${path.module}/lambda_packages/extractor.zip"

  source {
    content  = file("${path.module}/../lambda/extractor/handler.py")
    filename = "handler.py"
  }

  dynamic "source" {
    for_each = local.extraction_doc_types
    content {
      content  = file("${path.module}/../schemas/${source.value}_schema.json")
      filename = "schemas/${source.value}_schema.json"
    }
  }
}

data "archive_file" "validator" {
  type        = "zip"
  output_path = "${path.module}/lambda_packages/validator.zip"

  source {
    content  = file("${path.module}/../lambda/validator/handler.py")
    filename = "handler.py"
  }

  dynamic "source" {
    for_each = local.extraction_doc_types
    content {
      content  = file("${path.module}/../schemas/${source.value}_schema.json")
      filename = "schemas/${source.value}_schema.json"
    }
  }
}

# Renderer: bundle templates/ alongside handler.py.
# dynamic "source" iterates local.extraction_doc_types so adding a new doc
# type is automatic once the type is added to that set in locals.tf.
data "archive_file" "renderer" {
  type        = "zip"
  output_path = "${path.module}/lambda_packages/renderer.zip"

  source {
    content  = file("${path.module}/../lambda/renderer/handler.py")
    filename = "handler.py"
  }

  dynamic "source" {
    for_each = local.extraction_doc_types
    content {
      content  = file("${path.module}/../templates/${source.value}.j2")
      filename = "templates/${source.value}.j2"
    }
  }
}

data "archive_file" "claim_extractor" {
  type        = "zip"
  output_path = "${path.module}/lambda_packages/claim_extractor.zip"

  source {
    content  = file("${path.module}/../lambda/claim_extractor/handler.py")
    filename = "handler.py"
  }

  dynamic "source" {
    for_each = local.extraction_doc_types
    content {
      content  = file("${path.module}/../templates/${source.value}.j2")
      filename = "templates/${source.value}.j2"
    }
  }
}

data "archive_file" "claim_triager" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/claim_triager"
  output_path = "${path.module}/lambda_packages/claim_triager.zip"
}

data "archive_file" "claim_assessor" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/claim_assessor"
  output_path = "${path.module}/lambda_packages/claim_assessor.zip"
}

data "archive_file" "summary_assembler" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/summary_assembler"
  output_path = "${path.module}/lambda_packages/summary_assembler.zip"
}

data "archive_file" "comparator" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/comparator"
  output_path = "${path.module}/lambda_packages/comparator.zip"
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

  tags = local.common_tags

  depends_on = [aws_cloudwatch_log_group.lambda]
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

  tags = local.common_tags

  depends_on = [aws_cloudwatch_log_group.lambda]
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

  tags = local.common_tags

  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "api_experiment_status" {
  function_name    = "${local.name_prefix}-api-experiment-status"
  filename         = data.archive_file.api_experiment_status.output_path
  source_code_hash = data.archive_file.api_experiment_status.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.api.arn
  timeout          = 15
  memory_size      = 128

  environment {
    variables = {
      EXPERIMENTS_TABLE = aws_dynamodb_table.experiments.name
      SUMMARIES_BUCKET  = aws_s3_bucket.summaries.bucket
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["api-experiment-status"].name
  }

  tags = local.common_tags

  depends_on = [aws_cloudwatch_log_group.lambda]
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

  tags = local.common_tags

  depends_on = [aws_cloudwatch_log_group.lambda]
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
      CLASSIFIER_PROMPT_ARN       = aws_bedrockagent_prompt.classifier.arn
      CLASSIFIER_PROMPT_VERSION   = var.classifier_prompt_version
      GUARDRAIL_ID                = var.guardrail_id
      GUARDRAIL_VERSION           = var.guardrail_version
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["classifier"].name
  }

  tags = local.common_tags

  depends_on = [aws_cloudwatch_log_group.lambda]
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
      BEDROCK_MODEL_ID     = var.bedrock_model_id
      GUARDRAIL_ID         = var.guardrail_id
      GUARDRAIL_VERSION    = var.guardrail_version
      PROMPT_ARNS_JSON     = jsonencode({ for k in local.extraction_doc_types : k => aws_bedrockagent_prompt.extraction[k].arn })
      PROMPT_VERSIONS_JSON = jsonencode({ for k in local.extraction_doc_types : k => lookup(local.extraction_prompt_versions, k, "DRAFT") })
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["extractor"].name
  }

  tags = local.common_tags

  depends_on = [aws_cloudwatch_log_group.lambda]
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

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["validator"].name
  }

  tags = local.common_tags

  depends_on = [aws_cloudwatch_log_group.lambda]
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
      SUMMARIES_BUCKET  = aws_s3_bucket.summaries.bucket
      JOBS_TABLE        = aws_dynamodb_table.jobs.name
      EXPERIMENTS_TABLE = aws_dynamodb_table.experiments.name
      COMPARISON_SM_ARN = aws_sfn_state_machine.comparison.arn
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["renderer"].name
  }

  tags = local.common_tags

  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "claim_extractor" {
  function_name    = "${local.name_prefix}-claim-extractor"
  filename         = data.archive_file.claim_extractor.output_path
  source_code_hash = data.archive_file.claim_extractor.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.claim_validator_processing.arn
  timeout          = 120
  memory_size      = 512
  layers           = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = {
      UPLOAD_BUCKET              = aws_s3_bucket.uploads.bucket
      SUMMARIES_BUCKET           = aws_s3_bucket.summaries.bucket
      CHEAP_MODEL_ID             = var.bedrock_claim_cheap_model_id
      EMBEDDING_MODEL_ID         = "amazon.titan-embed-text-v2:0"
      DEDUP_SIMILARITY_THRESHOLD = "0.90"
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["claim-extractor"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "claim_triager" {
  function_name    = "${local.name_prefix}-claim-triager"
  filename         = data.archive_file.claim_triager.output_path
  source_code_hash = data.archive_file.claim_triager.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.claim_validator_processing.arn
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      UPLOAD_BUCKET              = aws_s3_bucket.uploads.bucket
      SUMMARIES_BUCKET           = aws_s3_bucket.summaries.bucket
      CHEAP_MODEL_ID             = var.bedrock_claim_cheap_model_id
      EMBEDDING_MODEL_ID         = "amazon.titan-embed-text-v2:0"
      TRIAGE_SIMILARITY_THRESHOLD = "0.55"
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["claim-triager"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "claim_assessor" {
  function_name    = "${local.name_prefix}-claim-assessor"
  filename         = data.archive_file.claim_assessor.output_path
  source_code_hash = data.archive_file.claim_assessor.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.claim_validator_processing.arn
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      SUMMARIES_BUCKET            = aws_s3_bucket.summaries.bucket
      CHEAP_MODEL_ID              = var.bedrock_claim_cheap_model_id
      EXPENSIVE_MODEL_ID          = var.bedrock_claim_expensive_model_id
      TRIAGE_SIMILARITY_THRESHOLD = "0.55"
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["claim-assessor"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "summary_assembler" {
  function_name    = "${local.name_prefix}-summary-assembler"
  filename         = data.archive_file.summary_assembler.output_path
  source_code_hash = data.archive_file.summary_assembler.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.claim_validator_processing.arn
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      SUMMARIES_BUCKET   = aws_s3_bucket.summaries.bucket
      EXPENSIVE_MODEL_ID = var.bedrock_claim_expensive_model_id
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["summary-assembler"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "comparator" {
  function_name    = "${local.name_prefix}-comparator"
  filename         = data.archive_file.comparator.output_path
  source_code_hash = data.archive_file.comparator.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.comparator.arn
  timeout          = 30
  memory_size      = 256

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["comparator"].name
  }

  tags = local.common_tags

  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_ecr_repository" "gold_comparator" {
  name                 = "${local.name_prefix}-gold-comparator"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

resource "aws_ecr_lifecycle_policy" "gold_comparator" {
  repository = aws_ecr_repository.gold_comparator.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only the 3 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 3
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_lambda_function" "gold_comparator" {
  function_name = "${local.name_prefix}-gold-comparator"
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.gold_comparator.repository_url}:${var.gold_comparator_image_tag}"
  architectures = ["arm64"]
  role          = aws_iam_role.gold_comparator.arn
  timeout       = 300
  memory_size   = 5120

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["gold-comparator"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
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
      JOBS_TABLE        = aws_dynamodb_table.jobs.name
      SUMMARIES_BUCKET  = aws_s3_bucket.summaries.bucket
      EXPERIMENTS_TABLE = aws_dynamodb_table.experiments.name
      COMPARISON_SM_ARN = aws_sfn_state_machine.comparison.arn
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["fail-handler"].name
  }

  tags = local.common_tags

  depends_on = [aws_cloudwatch_log_group.lambda]
}

# ── Comparison pipeline archive sources ─────────────────────────────────────

data "archive_file" "experiment_starter" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/experiment_starter"
  output_path = "${path.module}/lambda_packages/experiment_starter.zip"
}

data "archive_file" "summary_collector" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/summary_collector"
  output_path = "${path.module}/lambda_packages/summary_collector.zip"
}

data "archive_file" "variance_scorer" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/variance_scorer"
  output_path = "${path.module}/lambda_packages/variance_scorer.zip"
}

data "archive_file" "report_generator" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/report_generator"
  output_path = "${path.module}/lambda_packages/report_generator.zip"
}

data "archive_file" "report_writer" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/report_writer"
  output_path = "${path.module}/lambda_packages/report_writer.zip"
}

data "archive_file" "comparison_fail_handler" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/comparison_fail_handler"
  output_path = "${path.module}/lambda_packages/comparison_fail_handler.zip"
}

# ── Comparison pipeline Lambda functions ─────────────────────────────────────

resource "aws_lambda_function" "experiment_starter" {
  function_name    = "${local.name_prefix}-experiment-starter"
  filename         = data.archive_file.experiment_starter.output_path
  source_code_hash = data.archive_file.experiment_starter.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.experiment_starter.arn
  timeout          = 120
  memory_size      = 256

  environment {
    variables = {
      UPLOAD_BUCKET     = aws_s3_bucket.uploads.bucket
      SUMMARIES_BUCKET  = aws_s3_bucket.summaries.bucket
      JOBS_TABLE        = aws_dynamodb_table.jobs.name
      EXPERIMENTS_TABLE = aws_dynamodb_table.experiments.name
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["experiment-starter"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "summary_collector" {
  function_name    = "${local.name_prefix}-summary-collector"
  filename         = data.archive_file.summary_collector.output_path
  source_code_hash = data.archive_file.summary_collector.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.comparison_processing.arn
  timeout          = 60
  memory_size      = 256

  environment {
    variables = {
      EXPERIMENTS_TABLE = aws_dynamodb_table.experiments.name
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["summary-collector"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "variance_scorer" {
  function_name    = "${local.name_prefix}-variance-scorer"
  filename         = data.archive_file.variance_scorer.output_path
  source_code_hash = data.archive_file.variance_scorer.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.comparison_processing.arn
  timeout          = 300
  memory_size      = 1024

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["variance-scorer"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_ecr_repository" "gold_scorer" {
  name                 = "${local.name_prefix}-gold-scorer"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

resource "aws_ecr_lifecycle_policy" "gold_scorer" {
  repository = aws_ecr_repository.gold_scorer.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only the 3 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 3
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_lambda_function" "gold_scorer" {
  function_name = "${local.name_prefix}-gold-scorer"
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.gold_scorer.repository_url}:${var.gold_scorer_image_tag}"
  architectures = ["arm64"]
  role          = aws_iam_role.comparison_processing.arn
  timeout       = 300
  memory_size   = 5120

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["gold-scorer"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "report_generator" {
  function_name    = "${local.name_prefix}-report-generator"
  filename         = data.archive_file.report_generator.output_path
  source_code_hash = data.archive_file.report_generator.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.comparison_processing.arn
  timeout          = 120
  memory_size      = 512

  environment {
    variables = {
      REPORT_MODEL_ID = var.bedrock_model_id
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["report-generator"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "report_writer" {
  function_name    = "${local.name_prefix}-report-writer"
  filename         = data.archive_file.report_writer.output_path
  source_code_hash = data.archive_file.report_writer.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.comparison_processing.arn
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      EXPERIMENTS_TABLE = aws_dynamodb_table.experiments.name
      SUMMARIES_BUCKET  = aws_s3_bucket.summaries.bucket
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["report-writer"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function" "comparison_fail_handler" {
  function_name    = "${local.name_prefix}-comparison-fail-handler"
  filename         = data.archive_file.comparison_fail_handler.output_path
  source_code_hash = data.archive_file.comparison_fail_handler.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.comparison_fail_handler.arn
  timeout          = 15
  memory_size      = 128

  environment {
    variables = {
      EXPERIMENTS_TABLE = aws_dynamodb_table.experiments.name
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["comparison-fail-handler"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}
