# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Medical document summarization pipeline on AWS. Users upload documents (lab results, doctor's notes, injury docs, visit assessments, psych evals) via a browser UI; Claude classifies and extracts structured data, which is rendered into a readable summary.

## Commands

### Build and deploy

```bash
# 1. Build Lambda layer (jinja2, jsonschema) — required before every terraform apply
./scripts/build_lambdas.sh

# 2. First-time infrastructure deploy (localhost Cognito callback URLs)
terraform -chdir=infra init
terraform -chdir=infra apply

# 3. Deploy frontend (reads Terraform outputs, writes config.js, syncs to S3)
./scripts/deploy_frontend.sh

# 4. Update Cognito callback URLs to real CloudFront URL, then re-apply
#    Edit terraform.tfvars: cognito_callback_urls and cognito_logout_urls
terraform -chdir=infra apply
```

### Tests

```bash
# All tests (from repo root — pytest auto-discovers tests/)
pip install pytest boto3 jinja2 jsonschema
pytest tests/

# Single test file
pytest tests/test_extractor.py

# Single test by name
pytest tests/test_extractor.py::TestExtractorToolUseRequest::test_tool_choice_is_forced
```

Tests mock all AWS calls; no credentials or running infrastructure needed.

## Architecture

### Pipeline flow

```
Browser → Cognito (PKCE) → API Gateway (JWT) → api_presign Lambda
                                                      ↓
                                              S3 presigned POST
                                                      ↓
                                           uploads/{job_id}/{filename}
                                                      ↓
                                          pipeline_starter Lambda (S3 event)
                                                      ↓
                                        Step Functions Express state machine
                                          classifier → extractor → validator → renderer
                                                      ↓
                                           summaries/{job_id}/summary.txt
```

### Step Functions state machine (`infra/state_machine.json.tpl`)

All four processing states (ClassifyDocument, ExtractData, ValidateData, RenderSummary) have `Catch` blocks with `ResultPath: "$.error"`. This preserves the original input alongside the error so `fail_handler` can read `event['job_id']` at the top level rather than digging into `event['execution_input']`.

### Lambda roles (4 per-function roles, not shared)

| Role | Functions |
|------|-----------|
| `api-role` | api_presign, api_status, api_summary |
| `pipeline-starter-role` | pipeline_starter |
| `processing-role` | classifier, extractor, validator, renderer |
| `fail-handler-role` | fail_handler |

### Bedrock integration

- **Classification:** `bedrock-agent` client → `get_prompt()` then `bedrock-runtime` → `converse()`. Uses Claude Haiku.
- **Extraction:** Same pattern. Forces tool use with `toolChoice={"tool": {"name": "extract_document"}}` so the response always contains a `toolUse` block. Uses Claude Sonnet.
- **Model IDs must use a geo or global inference profile prefix** (`us.`, `eu.`, `au.`, `jp.`, `global.`). Bare model IDs (`anthropic.claude-*`) fail at runtime.
- Bedrock Prompt Management versions are pinned: `CLASSIFIER_PROMPT_VERSION` and `PROMPT_VERSIONS_JSON` env vars are set from `aws_bedrock_prompt_version.*.version` in Terraform.

### Terraform structure (`infra/`)

- **`lambda.tf`** — All Lambda functions and archive_file data sources. Extractor and validator zips bundle `schemas/` via multiple `source` blocks; renderer bundles `templates/`. The Lambda layer zip comes from `scripts/build_lambdas.sh`.
- **`iam.tf`** — Per-function IAM roles with least-privilege policies. Includes a local `xray_actions` for X-Ray permissions shared across roles.
- **`bedrock.tf`** — Guardrail (PII anonymization, excluding DATE_TIME which would break date field extraction), 6 prompts, 6 prompt versions.
- **`monitoring.tf`** — CloudWatch alarms (SFN failures, throttling, DLQ depth, API errors), SNS alerts, Cost Anomaly Detection, and the pipeline_starter DLQ. All conditional on `var.alert_email`.
- **`waf.tf`** — CloudFront WAF uses `provider = aws.us_east_1`; API WAF is regional. Both defined in this file; the provider alias is in `providers.tf`.
- **`kms.tf`** — Single CMK for S3 uploads, S3 summaries, and DynamoDB encryption.

### Key data patterns

- **DynamoDB `jobs` table:** Only `job_id`, `user_id`, `created_at` have attribute blocks (Terraform requires this for key/GSI attributes only). All other attributes (status, doc_type, etc.) are written as item attributes without Terraform declarations.
- **S3 presigned POST:** The `file` field in the FormData upload must be appended last. Content-Type condition uses `starts-with` rather than exact match.
- **Job deduplication:** `pipeline_starter` uses `job_id` as the Step Functions execution name. S3 event retries hit `ExecutionAlreadyExists` which is caught and treated as a no-op.

### Frontend (`frontend/`)

Vanilla JS PKCE flow. Tokens stored in `sessionStorage`. `config.js` is generated at deploy time by `scripts/deploy_frontend.sh` — it is not committed and is not present until after first deploy.

### Cognito two-step deploy

First apply uses `http://localhost:3000/callback` defaults. After `deploy_frontend.sh` runs and outputs the CloudFront URL, update `terraform.tfvars` with the real URL and re-apply. Only the Cognito App Client is changed on the second apply.
