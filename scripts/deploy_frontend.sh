#!/usr/bin/env bash
# deploy_frontend.sh — Inject runtime config, sync frontend to S3, invalidate CloudFront cache.
# Run after terraform apply completes.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
INFRA_DIR="$REPO_ROOT/infra"

echo "==> Reading Terraform outputs..."

CLOUDFRONT_ID=$(terraform -chdir="$INFRA_DIR" output -raw cloudfront_distribution_id)
BUCKET=$(terraform -chdir="$INFRA_DIR" output -raw frontend_bucket_name)
API_URL=$(terraform -chdir="$INFRA_DIR" output -raw api_gateway_url)
COGNITO_POOL_ID=$(terraform -chdir="$INFRA_DIR" output -raw cognito_user_pool_id)
COGNITO_CLIENT_ID=$(terraform -chdir="$INFRA_DIR" output -raw cognito_app_client_id)
COGNITO_DOMAIN=$(terraform -chdir="$INFRA_DIR" output -raw cognito_hosted_ui_domain)

echo "==> Generating config.js..."

cat > "$FRONTEND_DIR/config.js" <<EOF
window.APP_CONFIG = {
  cognitoUserPoolId:    "${COGNITO_POOL_ID}",
  cognitoClientId:      "${COGNITO_CLIENT_ID}",
  cognitoHostedUiDomain: "${COGNITO_DOMAIN}",
  apiUrl:               "${API_URL}"
};
EOF

echo "==> Syncing frontend to s3://${BUCKET}..."
aws s3 sync "$FRONTEND_DIR/" "s3://${BUCKET}/" \
  --delete \
  --cache-control "no-cache, no-store, must-revalidate" \
  --exclude ".gitkeep"

echo "==> Invalidating CloudFront cache (distribution: ${CLOUDFRONT_ID})..."
aws cloudfront create-invalidation \
  --distribution-id "$CLOUDFRONT_ID" \
  --paths "/*" \
  --output text

echo "==> Frontend deployed."
echo ""
CLOUDFRONT_URL=$(terraform -chdir="$INFRA_DIR" output -raw cloudfront_url)
echo "App URL: https://${CLOUDFRONT_URL}"
echo ""
echo "Next step: Update cognito_callback_urls and cognito_logout_urls in terraform.tfvars"
echo "  cognito_callback_urls = [\"https://${CLOUDFRONT_URL}/callback\"]"
echo "  cognito_logout_urls   = [\"https://${CLOUDFRONT_URL}\"]"
echo "Then run: terraform -chdir=infra apply"
