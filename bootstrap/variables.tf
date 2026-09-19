variable "aws_region" {
  type        = string
  description = "AWS region where bootstrap resources (state bucket and lock table) are created."
  default     = "us-east-1"
}

variable "state_bucket_name" {
  type        = string
  description = "Globally unique name for the S3 bucket that stores Terraform state."

  validation {
    condition     = !can(regex("^your-", var.state_bucket_name))
    error_message = "Replace the placeholder state_bucket_name before applying."
  }
}

variable "lock_table_name" {
  type        = string
  description = "Name for the DynamoDB table used for Terraform state locking."

  validation {
    condition     = !can(regex("^your-", var.lock_table_name))
    error_message = "Replace the placeholder lock_table_name before applying."
  }
}
