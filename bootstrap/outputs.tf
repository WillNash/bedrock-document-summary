output "state_bucket_name" {
  description = "Name of the S3 bucket storing Terraform state"
  value       = aws_s3_bucket.tf_state.bucket
}

output "lock_table_name" {
  description = "Name of the DynamoDB table used for Terraform state locking"
  value       = aws_dynamodb_table.tf_locks.name
}

output "backend_hcl" {
  value = <<-EOT
    bucket         = "${aws_s3_bucket.tf_state.bucket}"
    key            = "bedrock-doc-summary/terraform.tfstate"
    region         = "${var.aws_region}"
    dynamodb_table = "${aws_dynamodb_table.tf_locks.name}"
  EOT
  description = "Paste this into infra/backend.hcl"
}
