#!/usr/bin/env bash
# Usage: ./scripts/debug_experiment.sh <experiment_id> [project] [env]
# Shows experiment status, per-run job outcomes, and any error messages.
# Requires: aws CLI, jq

set -euo pipefail

EXPERIMENT_ID="${1:?Usage: $0 <experiment_id> [project] [env]}"
PROJECT="${2:-medsum}"
ENV="${3:-prod}"
PREFIX="${PROJECT}-${ENV}"
EXPERIMENTS_TABLE="${PREFIX}-experiments"
JOBS_TABLE="${PREFIX}-jobs"

echo "=== Experiment: ${EXPERIMENT_ID} ==="
aws dynamodb get-item \
  --table-name "${EXPERIMENTS_TABLE}" \
  --key "{\"experiment_id\": {\"S\": \"${EXPERIMENT_ID}\"}}" \
  --output json \
| jq '.Item | {
    status:      .status.S,
    expected_n:  .expected_n.N,
    completed_n: .completed_n.N,
    successful_n:.successful_n.N,
    failed_n:    .failed_n.N,
    created_at:  .created_at.S,
    completed_at:.completed_at.S,
    error_message:.error_message.S
  }'

echo ""
echo "=== Jobs for experiment (from GSI not available — scanning) ==="
echo "(Showing jobs where experiment_id matches — may be slow on large tables)"
aws dynamodb scan \
  --table-name "${JOBS_TABLE}" \
  --filter-expression "experiment_id = :eid" \
  --expression-attribute-values "{\":eid\": {\"S\": \"${EXPERIMENT_ID}\"}}" \
  --output json \
| jq '[.Items[] | {
    job_id:      .job_id.S,
    run_number:  .run_number.N,
    status:      .status.S,
    error_message:.error_message.S,
    created_at:  .created_at.S,
    completed_at:.completed_at.S
  }] | sort_by(.run_number | tonumber)'
