#!/usr/bin/env bash
# Creates the Bedrock PHI guardrail if it does not already exist, then creates
# a numbered version. Prints two lines suitable for eval or >> $GITHUB_ENV:
#   TF_VAR_guardrail_id=<id>
#   TF_VAR_guardrail_version=<version>
#
# Usage: eval "$(./scripts/ensure_guardrail.sh)"
#   or in GitHub Actions: ./scripts/ensure_guardrail.sh >> $GITHUB_ENV
set -euo pipefail

GUARDRAIL_NAME="${TF_VAR_project_name:-bedrock-doc-summary}-${TF_VAR_environment:-prod}-phi-guardrail"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "Looking for guardrail: $GUARDRAIL_NAME" >&2

GUARDRAIL_ID=$(aws bedrock list-guardrails \
  --region "$REGION" \
  --query "guardrails[?name=='$GUARDRAIL_NAME'].id | [0]" \
  --output text)

if [ -z "$GUARDRAIL_ID" ] || [ "$GUARDRAIL_ID" = "None" ]; then
  echo "Guardrail not found — creating..." >&2
  GUARDRAIL_ID=$(aws bedrock create-guardrail \
    --region "$REGION" \
    --name "$GUARDRAIL_NAME" \
    --blocked-input-messaging "This request contains content that cannot be processed." \
    --blocked-outputs-messaging "The response contains content that cannot be displayed." \
    --sensitive-information-policy-config '{
      "piiEntitiesConfig": [
        {"type": "NAME",                   "action": "ANONYMIZE"},
        {"type": "EMAIL",                  "action": "ANONYMIZE"},
        {"type": "PHONE",                  "action": "ANONYMIZE"},
        {"type": "ADDRESS",                "action": "ANONYMIZE"},
        {"type": "US_SOCIAL_SECURITY_NUMBER", "action": "ANONYMIZE"},
        {"type": "US_PASSPORT_NUMBER",     "action": "ANONYMIZE"},
        {"type": "DRIVER_ID",              "action": "ANONYMIZE"}
      ]
    }' \
    --query 'guardrailId' \
    --output text)
  echo "Created guardrail: $GUARDRAIL_ID" >&2
else
  echo "Found existing guardrail: $GUARDRAIL_ID" >&2
fi

echo "Creating guardrail version..." >&2
GUARDRAIL_VERSION=$(aws bedrock create-guardrail-version \
  --region "$REGION" \
  --guardrail-identifier "$GUARDRAIL_ID" \
  --query 'version' \
  --output text)

echo "Guardrail version: $GUARDRAIL_VERSION" >&2

echo "TF_VAR_guardrail_id=$GUARDRAIL_ID"
echo "TF_VAR_guardrail_version=$GUARDRAIL_VERSION"
