#!/usr/bin/env bash
# Build, push, and deploy the gold_scorer Lambda container image.
#
# FIRST-DEPLOY BOOTSTRAPPING SEQUENCE:
#   1. terraform -chdir=infra apply -target=aws_ecr_repository.gold_scorer \
#                                   -target=aws_ecr_lifecycle_policy.gold_scorer
#   2. ./scripts/build_gold_scorer.sh
#   3. terraform -chdir=infra apply
#
# SUBSEQUENT DEPLOYS:
#   terraform -chdir=infra apply
#   ./scripts/build_gold_scorer.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$SCRIPT_DIR/../infra"

AWS_REGION=${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || true)}
if [ -z "$AWS_REGION" ]; then
  echo "ERROR: AWS region not set. Set AWS_DEFAULT_REGION or configure the aws default region."
  exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

ECR_REPO_NAME=$(terraform -chdir="$INFRA_DIR" output -raw gold_scorer_ecr_repository_name 2>/dev/null || true)
if [ -z "$ECR_REPO_NAME" ]; then
  echo "ERROR: ECR repository not yet created. Run:"
  echo "  terraform -chdir=infra apply -target=aws_ecr_repository.gold_scorer \\"
  echo "                               -target=aws_ecr_lifecycle_policy.gold_scorer"
  exit 1
fi

ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

_RAW_FUNCTION_NAME=$(terraform -chdir="$INFRA_DIR" output -raw gold_scorer_function_name 2>/dev/null || true)
if [[ "${_RAW_FUNCTION_NAME:-}" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  FUNCTION_NAME="$_RAW_FUNCTION_NAME"
else
  FUNCTION_NAME=""
fi

aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

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
  "$SCRIPT_DIR/../lambda/gold_scorer/"

if [ -z "$FUNCTION_NAME" ]; then
  echo "INFO: Image pushed to ECR successfully."
  echo "      Lambda function not yet deployed. Run:"
  echo "        terraform -chdir=infra apply"
  exit 0
fi

aws lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --image-uri "${ECR_URI}:latest" \
  --region "$AWS_REGION"

echo "Done: gold_scorer deployed ${ECR_URI}:latest"
