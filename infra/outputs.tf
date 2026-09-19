output "cloudfront_url" {
  description = "CloudFront distribution domain — use this in cognito_callback_urls after first apply"
  value       = aws_cloudfront_distribution.frontend.domain_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID — used by deploy_frontend.sh for cache invalidation"
  value       = aws_cloudfront_distribution.frontend.id
}

output "api_gateway_url" {
  description = "HTTP API Gateway invoke URL"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  value       = aws_cognito_user_pool.main.id
}

output "cognito_app_client_id" {
  description = "Cognito App Client ID (used by frontend for PKCE auth)"
  value       = aws_cognito_user_pool_client.web.id
}

output "cognito_hosted_ui_domain" {
  description = "Cognito Hosted UI base domain (for constructing authorize/token URLs)"
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${local.region}.amazoncognito.com"
}

output "upload_bucket_name" {
  description = "S3 bucket for document uploads"
  value       = aws_s3_bucket.uploads.bucket
}

output "summaries_bucket_name" {
  description = "S3 bucket for rendered summaries"
  value       = aws_s3_bucket.summaries.bucket
}

output "frontend_bucket_name" {
  description = "S3 bucket for frontend static assets"
  value       = aws_s3_bucket.frontend.bucket
}

output "jobs_table_name" {
  description = "DynamoDB jobs table name"
  value       = aws_dynamodb_table.jobs.name
}

output "state_machine_arn" {
  description = "Step Functions Express state machine ARN"
  value       = aws_sfn_state_machine.pipeline.arn
}

output "phi_kms_key_arn" {
  description = "ARN of the PHI data encryption KMS key (S3 and DynamoDB)"
  value       = aws_kms_key.phi.arn
}

output "pipeline_starter_dlq_url" {
  description = "SQS URL for the pipeline_starter dead-letter queue"
  value       = aws_sqs_queue.pipeline_starter_dlq.url
}
