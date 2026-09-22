#!/usr/bin/env bash
# Publish new pinned versions of all Bedrock prompts (classifier + all extraction
# doc types) and print TF_VAR exports for use with terraform apply.
#
# The AWS Terraform provider does not support aws_bedrockagent_prompt_version,
# so versions are managed out-of-band exactly like guardrail versions.
#
# Usage:
#   eval "$(./scripts/publish_prompt_versions.sh)"
#   terraform -chdir=infra apply
#
# Or in GitHub Actions:
#   ./scripts/publish_prompt_versions.sh >> $GITHUB_ENV
#   terraform -chdir=infra apply    # picks up TF_VAR_* from environment
#
# Run this script whenever prompt content changes. Version numbers are
# sequential per-prompt integers (1, 2, 3 ...) assigned by Bedrock.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$SCRIPT_DIR/../infra"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

# ── Read prompt ARNs from Terraform outputs ───────────────────────────────────

CLASSIFIER_ARN=$(terraform -chdir="$INFRA_DIR" output -raw classifier_prompt_arn 2>/dev/null)
if [ -z "$CLASSIFIER_ARN" ]; then
  echo "ERROR: classifier_prompt_arn output not found. Run terraform apply first." >&2
  exit 1
fi

EXTRACTION_ARNS_JSON=$(terraform -chdir="$INFRA_DIR" output -raw extraction_prompt_arns_json 2>/dev/null)
if [ -z "$EXTRACTION_ARNS_JSON" ]; then
  echo "ERROR: extraction_prompt_arns_json output not found. Run terraform apply first." >&2
  exit 1
fi

# ── Publish classifier version ────────────────────────────────────────────────

echo "Publishing classifier prompt version..." >&2
CLASSIFIER_VERSION=$(aws bedrock-agent create-prompt-version \
  --region "$REGION" \
  --prompt-identifier "$CLASSIFIER_ARN" \
  --query 'version' \
  --output text)
echo "  classifier → version $CLASSIFIER_VERSION" >&2

# ── Publish extraction prompt versions ───────────────────────────────────────

echo "Publishing extraction prompt versions..." >&2
declare -A EXTRACTION_VERSIONS

# Parse the ARN map and create a version for each doc type
while IFS="=" read -r DOC_TYPE ARN; do
  VERSION=$(aws bedrock-agent create-prompt-version \
    --region "$REGION" \
    --prompt-identifier "$ARN" \
    --query 'version' \
    --output text)
  EXTRACTION_VERSIONS["$DOC_TYPE"]="$VERSION"
  echo "  $DOC_TYPE → version $VERSION" >&2
done < <(echo "$EXTRACTION_ARNS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for k, v in sorted(data.items()):
    print(f'{k}={v}')
")

# Build the extraction_prompt_versions_json value
VERSIONS_JSON=$(python3 -c "
import json, sys
pairs = sys.stdin.read().strip().split('\n')
d = {}
for p in pairs:
    if '=' in p:
        k, v = p.split('=', 1)
        d[k] = v
print(json.dumps(d, separators=(',', ':')))
" <<< "$(for k in "${!EXTRACTION_VERSIONS[@]}"; do echo "$k=${EXTRACTION_VERSIONS[$k]}"; done)")

# ── Output TF_VAR exports ─────────────────────────────────────────────────────

echo "TF_VAR_classifier_prompt_version=$CLASSIFIER_VERSION"
echo "TF_VAR_extraction_prompt_versions_json=$VERSIONS_JSON"
