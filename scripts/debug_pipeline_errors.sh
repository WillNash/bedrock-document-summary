#!/usr/bin/env bash
# Usage: ./scripts/debug_pipeline_errors.sh <experiment_id> [project] [env] [minutes_ago]
# Pulls ERROR-level events from the pipeline state machine CloudWatch log group,
# filtered to job_ids belonging to the given experiment.
#
# The pipeline SM is an EXPRESS workflow — execution history is only in CW Logs.
# Logs are at ERROR level, so each Catch event appears here with its cause.

set -euo pipefail

EXPERIMENT_ID="${1:?Usage: $0 <experiment_id> [project] [env] [minutes_ago]}"
PROJECT="${2:-medsum}"
ENV="${3:-prod}"
MINUTES="${4:-60}"
PREFIX="${PROJECT}-${ENV}"
LOG_GROUP="/aws/states/${PREFIX}-pipeline"
JOBS_TABLE="${PREFIX}-jobs"

# Epoch millis for the start of the window
START_MS=$(( ($(date +%s) - MINUTES * 60) * 1000 ))

echo "=== Fetching job_ids for experiment ${EXPERIMENT_ID} ==="
JOB_IDS=$(aws dynamodb scan \
  --table-name "${JOBS_TABLE}" \
  --filter-expression "experiment_id = :eid" \
  --expression-attribute-values "{\":eid\": {\"S\": \"${EXPERIMENT_ID}\"}}" \
  --output json \
| jq -r '[.Items[].job_id.S] | join("|")')

if [ -z "${JOB_IDS}" ]; then
  echo "No jobs found for experiment ${EXPERIMENT_ID}"
  exit 1
fi
echo "Job IDs: ${JOB_IDS}"
echo ""

echo "=== Pipeline SM error logs (last ${MINUTES} min) ==="
# Express Workflow logs use the execution name (= job_id) in the log stream name.
# Filter log events across all streams in the log group for these job_ids.
aws logs filter-log-events \
  --log-group-name "${LOG_GROUP}" \
  --start-time "${START_MS}" \
  --filter-pattern "ERROR" \
  --output json \
| jq --arg ids "${JOB_IDS}" '
    .events[]
    | select(.message | test($ids))
    | {
        timestamp: (.timestamp / 1000 | strftime("%Y-%m-%dT%H:%M:%SZ")),
        message: (.message | try fromjson catch .)
      }'
