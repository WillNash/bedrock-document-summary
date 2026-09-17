provider "aws" {
  region = var.aws_region
}

# CloudFront WAF must be deployed in us-east-1 regardless of deployment region
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}
