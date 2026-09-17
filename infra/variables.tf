variable "aws_region" {
  type        = string
  description = "AWS region to deploy into"
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Short project identifier used as a prefix for all resource names (e.g. bedrock-doc-summary)"
}

variable "environment" {
  type        = string
  description = "Deployment environment label (prod, staging, dev)"
  default     = "prod"
}

variable "bedrock_model_id" {
  type        = string
  description = "Bedrock inference profile ID for extraction and rendering. Must use a geo or global prefix."
  default     = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

  validation {
    condition     = can(regex("^(us\\.|eu\\.|au\\.|jp\\.|global\\.)", var.bedrock_model_id))
    error_message = "bedrock_model_id must start with a geo or global prefix: us., eu., au., jp., or global. Do not use bare model IDs (e.g. anthropic.claude-*) — they will fail at runtime."
  }
}

variable "bedrock_classifier_model_id" {
  type        = string
  description = "Bedrock inference profile ID for the classification step (cheaper/faster model). Must use a geo or global prefix."
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

  validation {
    condition     = can(regex("^(us\\.|eu\\.|au\\.|jp\\.|global\\.)", var.bedrock_classifier_model_id))
    error_message = "bedrock_classifier_model_id must start with a geo or global prefix: us., eu., au., jp., or global. Do not use bare model IDs — they will fail at runtime."
  }
}

variable "cognito_callback_urls" {
  type        = list(string)
  description = "Allowed OAuth callback URLs for the Cognito app client. Update to the real CloudFront URL after first terraform apply."
  default     = ["http://localhost:3000/callback"]
}

variable "cognito_logout_urls" {
  type        = list(string)
  description = "Allowed logout redirect URLs. Update to the real CloudFront URL after first terraform apply."
  default     = ["http://localhost:3000"]
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log group retention in days"
  default     = 30
}

variable "upload_max_size_bytes" {
  type        = number
  description = "Maximum allowed upload size in bytes for S3 presigned POST"
  default     = 10485760
}

variable "daily_upload_limit" {
  type        = number
  description = "Maximum documents a single user can upload per calendar day (UTC)"
  default     = 20
}

variable "processing_concurrency" {
  type        = number
  description = "Reserved concurrency for classifier and extractor Lambdas — caps simultaneous Bedrock calls across all users"
  default     = 5
}

variable "tags" {
  type        = map(string)
  description = "Additional tags to apply to all resources"
  default     = {}
}
