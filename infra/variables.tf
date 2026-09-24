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
  description = "Bedrock model or inference profile ID for extraction and rendering. Use a geo-prefixed cross-region inference profile (us., eu., etc.) when available; use the bare model ID (anthropic.claude-*) for models that don't yet have a cross-region profile."
  default     = "us.anthropic.claude-sonnet-4-6"
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

variable "alert_email" {
  type        = string
  description = "Email address for operational and cost anomaly alerts. Leave empty to disable alerting."
  default     = ""
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log group retention in days"
  default     = 30

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be a valid CloudWatch retention period (1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653)."
  }
}

variable "upload_max_size_bytes" {
  type        = number
  description = "Maximum allowed upload size in bytes for S3 presigned POST"
  default     = 10485760

  validation {
    condition     = var.upload_max_size_bytes > 0 && var.upload_max_size_bytes <= 5368709120
    error_message = "upload_max_size_bytes must be between 1 and 5368709120 (5 GiB S3 single-PUT limit)."
  }
}

variable "daily_upload_limit" {
  type        = number
  description = "Maximum documents a single user can upload per calendar day (UTC)"
  default     = 200

  validation {
    condition     = var.daily_upload_limit >= 1
    error_message = "daily_upload_limit must be at least 1."
  }
}

variable "processing_concurrency" {
  type        = number
  description = "Reserved concurrency for classifier and extractor Lambdas — caps simultaneous Bedrock calls across all users"
  default     = 5

  validation {
    condition     = var.processing_concurrency >= 1
    error_message = "processing_concurrency must be at least 1."
  }
}

variable "tags" {
  type        = map(string)
  description = "Additional tags to apply to all resources"
  default     = {}
}

variable "gold_scorer_image_tag" {
  type        = string
  description = "ECR image tag for the gold_scorer Lambda container. Set by scripts/build_gold_scorer.sh using the git commit SHA."
  default     = "latest"
}

variable "gold_comparator_image_tag" {
  type        = string
  description = "ECR image tag for the gold_comparator Lambda container. Set by scripts/build_gold_comparator.sh using the git commit SHA."
  default     = "latest"
}

variable "classifier_prompt_version" {
  type        = string
  description = "Pinned version number for the classifier Bedrock prompt. Set by scripts/publish_prompt_versions.sh before terraform apply. Defaults to DRAFT (mutable staging slot — unsafe for production)."
  default     = "DRAFT"
}

variable "extraction_prompt_versions_json" {
  type        = string
  description = "JSON object mapping extraction doc types to pinned prompt version numbers, e.g. {\"lab_result\":\"2\",\"doctors_notes\":\"2\",...}. Set by scripts/publish_prompt_versions.sh before terraform apply. Empty string defaults all types to DRAFT."
  default     = ""
}

variable "guardrail_id" {
  type        = string
  description = "Bedrock guardrail ID. Created by scripts/ensure_guardrail.sh and passed in by the deploy workflow."
  default     = ""
}

variable "guardrail_version" {
  type        = string
  description = "Bedrock guardrail version number to use in Lambda env vars."
  default     = "1"
}

variable "bedrock_claim_cheap_model_id" {
  type        = string
  description = "Bedrock geo inference profile ID for cheap claim-validation steps (claim extraction and triage). Must use au., us., eu., jp., or global. prefix."
  default     = "au.anthropic.claude-haiku-4-5-20251001-v1:0"

  validation {
    condition     = can(regex("^(us\\.|eu\\.|au\\.|jp\\.|global\\.)", var.bedrock_claim_cheap_model_id))
    error_message = "bedrock_claim_cheap_model_id must start with a geo or global prefix."
  }
}

variable "bedrock_claim_expensive_model_id" {
  type        = string
  description = "Bedrock geo inference profile ID for expensive claim-validation steps (deep assessment and summary assembly). Must use au., us., eu., jp., or global. prefix."
  default     = "au.anthropic.claude-sonnet-4-6"

  validation {
    condition     = can(regex("^(us\\.|eu\\.|au\\.|jp\\.|global\\.)", var.bedrock_claim_expensive_model_id))
    error_message = "bedrock_claim_expensive_model_id must start with a geo or global prefix."
  }
}
