#!/usr/bin/env bash
# Build, push, and deploy the gold_comparator Lambda container image.
#
# FIRST-DEPLOY BOOTSTRAPPING SEQUENCE:
#   1. terraform -chdir=infra apply -target=aws_ecr_repository.gold_comparator \
#                                   -target=aws_ecr_lifecycle_policy.gold_comparator
#   2. ./scripts/build_gold_comparator.sh
#      (pushes image; exits cleanly if Lambda not yet created — see step 3)
#   3. terraform -chdir=infra apply
#      (creates Lambda function referencing the now-existing private image)
#
# SUBSEQUENT DEPLOYS (CI/CD — ECR and Lambda already exist):
#   terraform -chdir=infra apply
#   ./scripts/build_gold_comparator.sh
#
# REQUIREMENTS:
#   - Docker with buildx support (available on GitHub Actions ubuntu-latest)
#   - AWS credentials with ECR push and Lambda update permissions
#   - Internet access during docker build (downloads scibert weights ~440 MB on first build;
#     subsequent builds use Docker layer cache)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$SCRIPT_DIR/../infra"

# Resolve AWS region
AWS_REGION=${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || true)}
if [ -z "$AWS_REGION" ]; then
  echo "ERROR: AWS region not set. Set AWS_DEFAULT_REGION or configure the aws default region."
  exit 1
fi

# Resolve AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Resolve ECR repo name — hard fail if ECR not yet created (run targeted apply first)
ECR_REPO_NAME=$(terraform -chdir="$INFRA_DIR" output -raw gold_comparator_ecr_repository_name 2>/dev/null || true)
if [ -z "$ECR_REPO_NAME" ]; then
  echo "ERROR: ECR repository not yet created. Run:"
  echo "  terraform -chdir=infra apply -target=aws_ecr_repository.gold_comparator \\"
  echo "                               -target=aws_ecr_lifecycle_policy.gold_comparator"
  exit 1
fi

ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

# Resolve Lambda function name — soft fail during first-deploy bootstrapping.
# 2>/dev/null suppresses stderr, but the setup-terraform CI wrapper can write
# ::error:: annotations to stdout on failure, so validate the captured value.
_RAW_FUNCTION_NAME=$(terraform -chdir="$INFRA_DIR" output -raw gold_comparator_function_name 2>/dev/null || true)
if [[ "${_RAW_FUNCTION_NAME:-}" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  FUNCTION_NAME="$_RAW_FUNCTION_NAME"
else
  FUNCTION_NAME=""
fi

# Authenticate with ECR
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Build and push image in one step (arm64, --provenance=false required for Lambda compatibility).
# --push is used instead of a separate docker push because the docker-container buildx driver
# (used in CI) does not export to the local daemon — it must push directly to the registry.
# GHA cache is used in CI to avoid re-downloading torch/transformers/scibert on every run.
CACHE_FLAGS=()
if [ -n "${GITHUB_ACTIONS:-}" ]; then
  CACHE_FLAGS=(--cache-from type=gha --cache-to type=gha,mode=max)
fi

docker buildx build \
  --platform linux/arm64 \
  --provenance=false \
  --push \
  "${CACHE_FLAGS[@]}" \
  -t "${ECR_URI}:latest" \
  "$SCRIPT_DIR/../lambda/gold_comparator/"

# First-deploy exit: Lambda not yet created — image is in ECR, run terraform apply next
if [ -z "$FUNCTION_NAME" ]; then
  echo "INFO: Image pushed to ECR successfully."
  echo "      Lambda function not yet deployed. Run:"
  echo "        terraform -chdir=infra apply"
  exit 0
fi

# Update Lambda to use the new image digest
aws lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --image-uri "${ECR_URI}:latest" \
  --region "$AWS_REGION"

echo "Done: gold_comparator deployed ${ECR_URI}:latest"
