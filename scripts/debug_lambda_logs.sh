#!/usr/bin/env bash
# Usage: ./scripts/debug_lambda_logs.sh <job_id> [project] [env] [minutes_ago]
# Shows recent CloudWatch log events for all pipeline lambdas containing the job_id.
# Useful for tracing exactly which lambda failed and what the error was.
#
# Lambdas searched: classifier, extractor, validator, renderer, fail-handler,
#                   claim-extractor, claim-triager, claim-assessor, summary-assembler

set -euo pipefail

JOB_ID="${1:?Usage: $0 <job_id> [project] [env] [minutes_ago]}"
PROJECT="${2:-medsum}"
ENV="${3:-prod}"
MINUTES="${4:-60}"
PREFIX="${PROJECT}-${ENV}"

START_MS=$(( ($(date +%s) - MINUTES * 60) * 1000 ))

LAMBDAS=(
  classifier
  extractor
  validator
  renderer
  fail-handler
  claim-extractor
  claim-triager
  claim-assessor
  summary-assembler
)

for LAMBDA in "${LAMBDAS[@]}"; do
  LOG_GROUP="/aws/lambda/${PREFIX}-${LAMBDA}"

  # Check if log group exists before querying
  EXISTS=$(aws logs describe-log-groups \
    --log-group-name-prefix "${LOG_GROUP}" \
    --output json \
  | jq -r '.logGroups | length')

  if [ "${EXISTS}" -eq 0 ]; then
    continue
  fi

  EVENTS=$(aws logs filter-log-events \
    --log-group-name "${LOG_GROUP}" \
    --start-time "${START_MS}" \
    --filter-pattern "\"${JOB_ID}\"" \
    --output json \
  | jq '.events | length')

  if [ "${EVENTS}" -eq 0 ]; then
    continue
  fi

  echo "=== ${LAMBDA} (${EVENTS} events) ==="
  aws logs filter-log-events \
    --log-group-name "${LOG_GROUP}" \
    --start-time "${START_MS}" \
    --filter-pattern "\"${JOB_ID}\"" \
    --output json \
  | jq -r '.events[] | [
      (.timestamp / 1000 | strftime("%H:%M:%S")),
      (.message | try (fromjson | .level // .action // .) catch .)
    ] | @tsv'
  echo ""
done
