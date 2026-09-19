terraform {
  required_version = "~> 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.66"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}
