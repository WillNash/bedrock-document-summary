#!/usr/bin/env bash
# Build, push, and deploy the gold_scorer Lambda container image.
#
# Tags the image with the current git commit SHA (short) and runs a targeted
# terraform apply to update the Lambda. ECR is IMMUTABLE so each SHA tag is
# write-once — re-running this script at the same commit is a no-op after the
# first push (docker buildx will hit the layer cache; terraform will see no
# change because image_uri already matches).
#
# FIRST-DEPLOY BOOTSTRAPPING SEQUENCE:
#   1. terraform -chdir=infra apply -target=aws_ecr_repository.gold_scorer \
#                                   -target=aws_ecr_lifecycle_policy.gold_scorer
#   2. ./scripts/build_gold_scorer.sh
#   3. terraform -chdir=infra apply   (picks up gold_scorer_image_tag from step 2)
#
# SUBSEQUENT DEPLOYS:
#   ./scripts/build_gold_scorer.sh    (builds, pushes, and applies in one step)
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

# Use git SHA as the image tag. Override with IMAGE_TAG env var if needed
# (e.g. IMAGE_TAG=latest for the very first bootstrapping push before any commits).
IMAGE_TAG="${IMAGE_TAG:-$(git -C "$SCRIPT_DIR" rev-parse --short HEAD)}"

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
  -t "${ECR_URI}:${IMAGE_TAG}" \
  "$SCRIPT_DIR/../lambda/gold_scorer/"

echo "Pushed ${ECR_URI}:${IMAGE_TAG}"

# Check whether the Lambda function exists yet (first-deploy bootstrapping).
_RAW_FUNCTION_NAME=$(terraform -chdir="$INFRA_DIR" output -raw gold_scorer_function_name 2>/dev/null || true)
if ! [[ "${_RAW_FUNCTION_NAME:-}" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "INFO: Lambda function not yet deployed. Run:"
  echo "  terraform -chdir=infra apply -var=\"gold_scorer_image_tag=${IMAGE_TAG}\""
  exit 0
fi

# Update only the gold_scorer Lambda — avoids needing to pass the other image tag variable.
terraform -chdir="$INFRA_DIR" apply \
  -target=aws_lambda_function.gold_scorer \
  -var="gold_scorer_image_tag=${IMAGE_TAG}" \
  -auto-approve

echo "Done: gold_scorer deployed ${ECR_URI}:${IMAGE_TAG}"
