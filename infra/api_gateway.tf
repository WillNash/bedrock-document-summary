resource "aws_apigatewayv2_api" "main" {
  name          = "${local.name_prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_headers = ["Authorization", "Content-Type"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_origins = ["https://${aws_cloudfront_distribution.frontend.domain_name}"]
    max_age       = 3600
  }

  tags = local.common_tags
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.main.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "cognito-jwt"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    # The endpoint attribute does not include the https:// scheme
    issuer = "https://${aws_cognito_user_pool.main.endpoint}"
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      sourceIp       = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
      errorMessage   = "$context.error.message"
    })
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${local.name_prefix}"
  retention_in_days = var.log_retention_days
  tags              = local.common_tags
}

# ── Integrations ────────────────────────────────────────────────────────────

resource "aws_apigatewayv2_integration" "comparator" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.comparator.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "api_presign" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api_presign.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "api_status" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api_status.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "api_summary" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api_summary.invoke_arn
  payload_format_version = "2.0"
}

# ── Routes ────────────────────────────────────────────────────────────────────

resource "aws_apigatewayv2_route" "compare" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "POST /compare"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
  target             = "integrations/${aws_apigatewayv2_integration.comparator.id}"
}

resource "aws_apigatewayv2_route" "presign" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "POST /presign"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
  target             = "integrations/${aws_apigatewayv2_integration.api_presign.id}"
}

resource "aws_apigatewayv2_route" "status" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "GET /jobs/{jobId}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
  target             = "integrations/${aws_apigatewayv2_integration.api_status.id}"
}

resource "aws_apigatewayv2_route" "summary" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "GET /summaries/{jobId}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
  target             = "integrations/${aws_apigatewayv2_integration.api_summary.id}"
}

resource "aws_apigatewayv2_integration" "gold_comparator" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.gold_comparator.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "gold_compare" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "POST /gold-compare"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
  target             = "integrations/${aws_apigatewayv2_integration.gold_comparator.id}"
}

# ── Lambda permissions for API Gateway ────────────────────────────────────────

resource "aws_apigatewayv2_integration" "api_experiment_status" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api_experiment_status.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "experiment_status" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "GET /experiments/{experimentId}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
  target             = "integrations/${aws_apigatewayv2_integration.api_experiment_status.id}"
}

resource "aws_lambda_permission" "apigw_api_experiment_status" {
  statement_id  = "AllowAPIGatewayInvokeExperimentStatus"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_experiment_status.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_apigatewayv2_integration" "experiment_starter" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.experiment_starter.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "experiments" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "POST /experiments"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
  target             = "integrations/${aws_apigatewayv2_integration.experiment_starter.id}"
}

resource "aws_lambda_permission" "apigw_experiment_starter" {
  statement_id  = "AllowAPIGatewayInvokeExperimentStarter"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.experiment_starter.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_gold_comparator" {
  statement_id  = "AllowAPIGatewayInvokeGoldComparator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.gold_comparator.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_comparator" {
  statement_id  = "AllowAPIGatewayInvokeComparator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.comparator.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_presign" {
  statement_id  = "AllowAPIGatewayInvokePresign"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_presign.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_status" {
  statement_id  = "AllowAPIGatewayInvokeStatus"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_status.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_summary" {
  statement_id  = "AllowAPIGatewayInvokeSummary"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_summary.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
