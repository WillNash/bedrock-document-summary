# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Medical document summarization pipeline on AWS. Users upload documents (lab results, doctor's notes, injury docs, visit assessments, psych evals) via a browser UI; Claude classifies and extracts structured data, which is rendered into a readable summary. A companion experiment system runs the same document through the pipeline N times to analyse output variance and accuracy against a gold-standard reference.

## Commands

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

### Terraform

```bash
# Validate and preview changes (CI runs this on pushes to main)
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
terraform -chdir=infra plan

# Always run fmt before committing — CI will fail if formatting is off
terraform -chdir=infra fmt -recursive
```

### Build and deploy (done by CI/CD; run manually if needed)

```bash
scripts/build_lambdas.sh          # Builds Lambda layer with arm64-optimized wheels
scripts/build_gold_scorer.sh      # Builds and pushes gold_scorer Docker image to ECR
scripts/build_gold_comparator.sh  # Builds and pushes gold_comparator Docker image to ECR
scripts/ensure_guardrail.sh       # Creates/updates Bedrock guardrail (see note below)
scripts/deploy_frontend.sh        # Syncs frontend to S3, invalidates CloudFront, generates config.js
```

## Architecture

### Three state machines

The pipeline is split across three Step Functions Standard state machines:

**1. Main pipeline** (`infra/state_machine.json.tpl`):
```
classifier → extractor → validator → [claim_validator sub-SM if $.validate=true] → renderer → fail_handler
```

**2. Claim validator sub-SM** (`infra/claim_validator_sm.json.tpl`) — invoked synchronously from the main pipeline when `validate: true`:
```
claim_extractor → claim_triager → claim_assessor → summary_assembler
```

**3. Comparison SM** (`infra/comparison_sm.json.tpl`) — triggered by `renderer`/`fail_handler` when all N experiment runs complete:
```
summary_collector → variance_scorer → [gold_scorer if has_gold] → report_generator → report_writer → comparison_fail_handler
```

All three are `type = "STANDARD"`. All processing states have `Catch` blocks using `ResultPath: "$.error"` to preserve the original input alongside errors so fail handlers can read `event['job_id']` at the top level.

### Full pipeline flow

```
Browser → Cognito (PKCE) → API Gateway (JWT) → api_presign Lambda
                                                      ↓
                                              S3 presigned POST
                                                      ↓
                                           uploads/{job_id}/{filename}
                                                      ↓
                                          pipeline_starter Lambda (S3 event)
                                                      ↓
                                     Step Functions Standard state machine
                           classifier → extractor → validator → renderer
                                                      ↓
                                           summaries/{job_id}/summary.txt
```

### Experiment pipeline

```
POST /experiments → experiment_starter Lambda
                          ↓
           Copies source doc N times → uploads/{job_id}/{filename}  (×N)
                          ↓
           Each copy triggers pipeline_starter → main SM (×N)
                          ↓
           renderer writes experiments/{experiment_id}/runs/{n}/summary.txt
                       + experiments/{experiment_id}/runs/{n}/metadata.json
                          ↓
           When all N runs reach terminal state → comparison SM triggered
                          ↓
        CollectSummaries → ComputeVariance → [ComputeGoldAccuracy] → GenerateReport → WriteReport
                          ↓
           experiments/{experiment_id}/report/comparison.json
           experiments/{experiment_id}/report/narrative.md
```

### Lambda roles

| Role | Functions |
|------|-----------|
| `api-role` | api_presign, api_status, api_summary, api_experiment_status |
| `pipeline-starter-role` | pipeline_starter |
| `processing-role` | classifier, extractor, validator, renderer |
| `fail-handler-role` | fail_handler |
| `comparator-role` | comparator |
| `gold-comparator-role` | gold_comparator |
| `experiment-starter-role` | experiment_starter |
| `comparison-processing-role` | summary_collector, variance_scorer, report_generator, report_writer |
| `comparison-fail-handler-role` | comparison_fail_handler |
| `claim-validator-processing-role` | claim_extractor, claim_triager, claim_assessor, summary_assembler |

### Docker-based Lambdas

Two Lambdas use container images (`package_type = "Image"`) rather than zip archives because they require native/ML dependencies too large for a Lambda layer:

- **`gold_scorer`** — BERTScore F1 using `allenai/scibert_scivocab_uncased` (PyTorch + bert_score). Built by `scripts/build_gold_scorer.sh`. The scibert tokenizer's `model_max_length` is forced to 256 (not the default VERY_LARGE_INTEGER) to keep warm-Lambda inference within the API Gateway timeout.
- **`gold_comparator`** — HTTP API equivalent of gold_scorer for ad-hoc comparisons. Built by `scripts/build_gold_comparator.sh`.

When deploying, `var.gold_scorer_image_tag` and `var.gold_comparator_image_tag` must be set to the ECR image tag produced by the respective build scripts.

### Bedrock integration

- **Classification:** `bedrock-agent` client → `get_prompt()` then `bedrock-runtime` → `converse()`. Uses Claude Haiku.
- **Extraction:** Same pattern. Forces tool use with `toolChoice={"tool": {"name": "extract_document"}}` so the response always contains a `toolUse` block. Uses Claude Sonnet.
- **Claim validation:** `claim_triager` uses Titan Text Embeddings v2 for RAG-style passage retrieval; `claim_assessor` escalates flagged claims (`contradicted` verdict or similarity < `TRIAGE_THRESHOLD`) to the expensive model for re-assessment; `summary_assembler` rewrites the summary using only evidence-grounded claims.
- **Model IDs must use a geo or global inference profile prefix** (`us.`, `eu.`, `au.`, `jp.`, `global.`). Bare model IDs (`anthropic.claude-*`) fail at runtime.
- **Bedrock Prompt Management versions:** The AWS Terraform provider does not support `aws_bedrockagent_prompt_version`. Prompt versions are managed out-of-band: run `scripts/publish_prompt_versions.sh` (calls `aws bedrock-agent create-prompt-version` for each prompt) then pass the printed `TF_VAR_*` exports to `terraform apply`. `CLASSIFIER_PROMPT_VERSION` and `PROMPT_VERSIONS_JSON` Lambda env vars default to `"DRAFT"` — must be set explicitly in CI to pin live traffic to an immutable version.
- **Bedrock guardrail workaround:** The AWS Terraform provider cannot manage the guardrail resource reliably. The deploy workflow removes it from state (`terraform state rm`) before `apply`, then `ensure_guardrail.sh` recreates/updates it via AWS CLI. Don't manage the guardrail resource directly in Terraform.

### Terraform structure (`infra/`)

- **`lambda.tf`** — All Lambda functions and archive_file data sources. Extractor and validator zips bundle `schemas/` via multiple `source` blocks; renderer bundles `templates/`. The Lambda layer zip comes from `scripts/build_lambdas.sh`. Docker-based Lambdas reference ECR image URIs via `image_uri`.
- **`step_functions.tf`** — Three Standard SMs: pipeline, claim_validator, and comparison.
- **`iam.tf`** — Per-function IAM roles with least-privilege policies. Includes a local `xray_actions` for X-Ray permissions shared across roles.
- **`bedrock.tf`** — Guardrail (PII anonymization, excluding DATE_TIME which would break date field extraction), 6 prompts, 6 prompt versions.
- **`monitoring.tf`** — CloudWatch alarms (SFN failures, throttling, DLQ depth, API errors), SNS alerts, Cost Anomaly Detection, and the pipeline_starter DLQ. All conditional on `var.alert_email`.
- **`kms.tf`** — Single CMK for S3 uploads, S3 summaries, and DynamoDB encryption.

### Key data patterns

- **DynamoDB `jobs` table:** Only `job_id`, `user_id`, `created_at` have attribute blocks (Terraform requires this for key/GSI attributes only). All other attributes (status, doc_type, etc.) are written as item attributes without Terraform declarations.
- **S3 presigned POST:** The `file` field in the FormData upload must be appended last. Content-Type condition uses `starts-with` rather than exact match.
- **Job deduplication:** `pipeline_starter` uses `job_id` as the Step Functions execution name. S3 event retries hit `ExecutionAlreadyExists` which is caught and treated as a no-op.
- **Claim validator triage:** `claim_triager` chunks the source document (1000 chars, 500 overlap), embeds chunks via Titan, and retrieves the top-3 passages per claim. Claims with low passage similarity or a `contradicted` verdict from the cheap model are escalated to `claim_assessor` for re-assessment with the expensive model.

### Frontend (`frontend/`)

Vanilla JS PKCE flow. Tokens stored in `localStorage` with silent refresh via the Cognito token endpoint. `config.js` is generated at deploy time by `scripts/deploy_frontend.sh` — it is not committed and is not present until after first deploy.

**First-deploy Cognito two-step:** On initial deploy, run once with the localhost callback URL defaults in `terraform.tfvars`, then update the Cognito callback URLs with the CloudFront domain printed in the deploy log, commit, and deploy again.

## Adding a document type

1. Add a JSON schema to `schemas/`
2. Add a Jinja2 template to `templates/`
3. Add a prompt file to `prompts/`
4. Add `aws_bedrock_prompt` + `aws_bedrock_prompt_version` resources in `infra/bedrock.tf`
5. Add the new type to `PROMPT_ARNS_JSON` / `PROMPT_VERSIONS_JSON` env vars in `infra/lambda.tf`
6. Add the new schema as a `source` block in both the `extractor` and `validator` archive_file resources in `infra/lambda.tf`
7. Update the valid labels set in `lambda/classifier/handler.py`
