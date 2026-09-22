# bedrock-document-summary

Serverless medical document summarization pipeline on AWS. Upload a document via the browser; Claude classifies it, extracts structured data, validates it against a JSON schema, and renders a readable summary — all within a Step Functions Express workflow.

A companion experiment system lets you run the same document through the pipeline N times and automatically analyse the variance between outputs, plus accuracy against a gold-standard reference summary.

## Supported document types

- Lab results
- Doctor's notes
- Injury documentation
- Visit assessments
- Psych evaluations

## Architecture

### Summarisation pipeline

```
Browser (PKCE) → Cognito → API Gateway → api_presign Lambda
                                              ↓
                                     S3 presigned POST
                                              ↓
                               uploads/{job_id}/{filename}
                                              ↓
                          pipeline_starter Lambda (S3 event)
                                              ↓
                        Step Functions Express state machine
                    classify → extract → validate → render
                                              ↓
                           summaries/{job_id}/summary.txt
```

### Experiment comparison pipeline

```
POST /experiments → experiment_starter Lambda
                          ↓
           Copies source doc N times → uploads/{job_id}/{filename}  (×N)
                          ↓
           Each copy triggers pipeline_starter → Express SM (×N)
                          ↓
           renderer writes experiments/{experiment_id}/runs/{n}/summary.txt
                       + experiments/{experiment_id}/runs/{n}/metadata.json
                          ↓
           When all N runs reach a terminal state → comparison SM triggered
                          ↓
        Step Functions Standard state machine (comparison)
          CollectSummaries → ComputeVariance → [ComputeGoldAccuracy] → GenerateReport → WriteReport
                          ↓
           experiments/{experiment_id}/report/comparison.json
           experiments/{experiment_id}/report/narrative.md
```

The comparison SM is Standard (not Express) so it can accommodate runs that exceed five minutes and provides a durable audit trail.

**AWS services:** Lambda (Python 3.12, arm64), Step Functions (Express + Standard), S3, DynamoDB, API Gateway v2, CloudFront, Cognito, Bedrock (Claude Sonnet for extraction and report generation, Haiku for classification, Titan Text Embeddings v2 for variance scoring), Bedrock Prompt Management, WAF, KMS, X-Ray, CloudWatch, ECR.

## Running experiments

### Start an experiment

```bash
POST /experiments
Content-Type: application/json

{
  "experiment_id": "lab-result-variance-01",
  "expected_n": 5,
  "source_document_key": "uploads/job-abc/doc.txt",
  "config": {"description": "Temperature 0.7 baseline"},
  "gold_text": "Optional reference summary for accuracy scoring"
}
```

| Field | Required | Description |
|---|---|---|
| `experiment_id` | yes | Unique identifier; used as the S3 prefix and SF execution name |
| `expected_n` | yes | Number of pipeline runs to trigger (2–100) |
| `source_document_key` | yes | S3 key of an already-uploaded document to use as input |
| `config` | no | Arbitrary JSON stored alongside the results for reproducibility |
| `gold_text` | no | Reference summary; enables BERTScore accuracy scoring if present |

The handler validates that the source document exists, writes an experiments record to DynamoDB, and copies the document N times — each copy triggers the pipeline independently via the S3 event.

### What gets recorded

Every successful pipeline run writes two files under `experiments/{experiment_id}/runs/{n}/`:

**`summary.txt`** — the rendered plain-text summary (no extracted structured data — PHI is never stored here).

**`metadata.json`** — full provenance record:

```json
{
  "experiment_id": "lab-result-variance-01",
  "run_number": 3,
  "job_id": "job-xyz",
  "source_document_key": "uploads/job-abc/doc.txt",
  "doc_type": "lab_result",
  "timestamp": "2026-09-22T10:00:00Z",
  "classification": {
    "model_id": "us.anthropic.claude-haiku-4-5-...",
    "prompt_arn": "arn:aws:bedrock:...",
    "prompt_version": "1",
    "guardrail_id": "abc123",
    "guardrail_version": "1",
    "input_tokens": 100,
    "output_tokens": 5
  },
  "extraction": {
    "model_id": "us.anthropic.claude-sonnet-4-5-...",
    "prompt_arn": "arn:aws:bedrock:...",
    "prompt_version": "2",
    "input_tokens": 2000,
    "output_tokens": 300
  }
}
```

Everything needed to reproduce any individual run is captured: exact model IDs, pinned prompt ARNs and versions, guardrail version, and token counts.

### Comparison report

When all N runs reach a terminal state (success or failure), the comparison state machine starts automatically. It analyses the successful subset and writes:

**`experiments/{experiment_id}/report/comparison.json`** — structured results:
- `variance_results.embedding_cosine` — pairwise cosine similarity matrix using Titan Text Embeddings v2 (mean, std, min, max, variance, full N×N matrix)
- `variance_results.tfidf_cosine` — same stats using TF-IDF cosine as a lightweight baseline
- `gold_results` — if a gold summary was provided: embedding cosine scores per run and BERTScore F1 scores (SciBERT, `allenai/scibert_scivocab_uncased`) per run

**`experiments/{experiment_id}/report/narrative.md`** — a 200–400 word Markdown analysis generated by Claude Sonnet interpreting the numeric results.

The experiments DynamoDB table tracks status (`PENDING` → `COMPLETED` or `COMPARISON_FAILED`) and the successful/failed run counts.

## CI/CD

Two GitHub Actions workflows are included:

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | Every push; PRs to main | Runs pytest on all branches. On pushes to main, also runs `terraform fmt`, `validate`, and `plan`. |
| `deploy.yml` | Manual (`workflow_dispatch`) | Builds the Lambda layer, runs `terraform apply`, deploys the frontend. |

### One-time setup

#### 1. Create Terraform state infrastructure

The `bootstrap/` module creates the S3 bucket and DynamoDB lock table that Terraform uses as its remote backend. This must exist before CI/CD can run.

Edit `bootstrap/terraform.tfvars` with names for your bucket and table:

```hcl
state_bucket_name = "your-project-tf-state"
lock_table_name   = "your-project-tf-locks"
```

Then apply:

```bash
terraform -chdir=bootstrap init
terraform -chdir=bootstrap apply
```

The `backend_hcl` output prints the exact content needed for the next step. Commit `bootstrap/terraform.tfstate` — it contains only bucket and table names, nothing sensitive.

#### 2. Add GitHub secrets

Go to **Settings → Secrets and variables → Actions** in your GitHub repository and add:

| Secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | Access key ID for the CI IAM user |
| `AWS_SECRET_ACCESS_KEY` | Secret access key for that user |
| `TF_BACKEND_CONFIG` | Contents of `infra/backend.hcl` (S3 bucket, DynamoDB table, region, key) |

The IAM user needs permissions to create, update, and delete all resources in the stack (Lambda, S3, DynamoDB, API Gateway, CloudFront, Cognito, Step Functions, Bedrock, WAF, KMS, IAM roles, CloudWatch, SQS, SNS, ECR).

#### 3. Optionally configure the production environment

The deploy workflow runs in a GitHub environment called `production`. If you want to require a manual approval before every deploy:

1. Go to **Settings → Environments → production**
2. Enable **Required reviewers** and add yourself

### Day-to-day usage

**Tests** run automatically on every push to any branch. No setup needed.

**Terraform plan** runs automatically when you push or merge to `main`. Check the Actions tab to see what would change before triggering a deploy.

**Deploy** is always manual. Go to **Actions → Deploy → Run workflow** and click the button. The workflow:
1. Builds the Lambda layer
2. Runs `terraform apply`
3. Syncs the frontend to S3 and invalidates the CloudFront cache

### First deploy via CI

The Cognito callback URL two-step still applies on a first deploy. Run the deploy workflow once with the localhost defaults in `terraform.tfvars`, then update the callback URLs with the CloudFront domain that's printed in the deploy log, commit, and run the deploy workflow a second time.

### Subsequent deploys

For code changes (Lambda handlers, schemas, templates, prompts): push to main, check the plan, then trigger the deploy workflow.

For infrastructure changes (adding resources, changing variables): same flow — the plan on main shows the diff before you deploy.

## Development

### Running tests

No AWS credentials needed — all AWS calls are mocked.

```bash
pip install pytest jinja2 jsonschema

# All tests
pytest tests/

# Single file
pytest tests/test_extractor.py

# Single test
pytest tests/test_extractor.py::TestExtractorToolUseRequest::test_tool_choice_is_forced
```

### Project layout

```
lambda/
  api_presign/          Generates presigned POST URLs
  api_status/           Returns job status from DynamoDB
  api_summary/          Returns rendered summary from S3
  pipeline_starter/     S3-event trigger; starts Express SM; passes experiment context when present
  classifier/           Bedrock Haiku classification; returns prompt provenance in usage_stats
  extractor/            Bedrock Sonnet extraction; returns prompt provenance in usage_stats
  validator/            JSON schema validation
  renderer/             Renders summary; writes experiment run outputs; triggers comparison SM
  fail_handler/         Marks failed jobs; increments experiment fail count; triggers comparison SM
  experiment_starter/   POST /experiments handler; copies source doc N times
  summary_collector/    Comparison SM task; discovers run files; reads experiment config
  variance_scorer/      Comparison SM task; Titan embeddings + TF-IDF cosine pairwise scoring
  gold_scorer/          Comparison SM task; BERTScore F1 vs gold (Docker/ECR)
  report_generator/     Comparison SM task; Claude Sonnet narrative analysis
  report_writer/        Comparison SM task; writes comparison.json + narrative.md; marks COMPLETED
  comparison_fail_handler/  Comparison SM catch; marks experiment COMPARISON_FAILED
schemas/        JSON schemas for structured extraction (one per document type)
templates/      Jinja2 summary templates (one per document type)
prompts/        System prompts for classification and extraction
infra/          Terraform — one .tf file per concern
bootstrap/      Terraform module that creates the S3 state bucket and DynamoDB lock table (run once)
scripts/
  build_lambdas.sh        Builds Lambda layer with arm64-optimized wheels
  build_gold_scorer.sh    Builds and pushes gold_scorer Docker image to ECR
  deploy_frontend.sh      Syncs frontend to S3, invalidates CloudFront, generates config.js
  ensure_guardrail.sh     Creates/updates Bedrock guardrail (called by deploy workflow)
tools/          consistency_evaluator.py — local ad-hoc variance tool (predates the experiment system)
tests/          pytest unit tests
frontend/       Vanilla JS SPA (config.js generated at deploy time by deploy_frontend.sh)
```

### Evaluating output consistency

The `tools/` directory contains two standalone scripts for quick local variance checks. These predate the built-in experiment system and remain useful for ad-hoc testing without deploying infrastructure.

#### Local variant (`tools/consistency_evaluator.py`)

Uses local ML models — no Bedrock embedding API calls required. Downloads models on first run (~440 MB PubMedBERT, ~260 MB distilbert for BERTScore).

| Metric | Notes |
|---|---|
| Embedding cosine | `NeuML/pubmedbert-base-embeddings` via sentence-transformers |
| BERTScore F1 | `microsoft/deberta-large-mnli`; skip in CI with `-m "not slow"` |
| TF-IDF cosine | Lightweight baseline; zero downloads |
| Field agreement | Plurality fraction across N extracted values per field |

```bash
pip install -r tools/requirements.txt
python tools/consistency_evaluator.py \
  --doc-type lab_result \
  --document path/to/doc.txt \
  --prompt prompts/lab_result_prompt.txt \
  --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 \
  --n-runs 5 \
  --temperature 0.7 \
  --output-json results.json
```

#### Cloud variant (`tools/consistency_evaluator_cloud.py`)

Uses Bedrock Titan Text Embeddings v2 — no local model downloads. Requires active AWS credentials with Bedrock access.

| Metric | Notes |
|---|---|
| Titan embedding cosine | `amazon.titan-embed-text-v2:0` via Bedrock; ~$0.00002/1K tokens |
| TF-IDF cosine | Lightweight baseline; zero API cost |
| Field agreement | Plurality fraction across N extracted values per field |

```bash
pip install numpy scikit-learn jinja2
python tools/consistency_evaluator_cloud.py \
  --doc-type lab_result \
  --document path/to/doc.txt \
  --prompt prompts/lab_result_prompt.txt \
  --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 \
  --n-runs 5 \
  --temperature 0.7 \
  --output-json results.json
```

The `--prompt` file must match the pinned Bedrock Prompt Management version used in production.

### Adding a document type

1. Add a JSON schema to `schemas/`
2. Add a Jinja2 template to `templates/`
3. Add a prompt file to `prompts/`
4. Add a `aws_bedrock_prompt` + `aws_bedrock_prompt_version` resource in `infra/bedrock.tf`
5. Add the new type to the `PROMPT_ARNS_JSON` / `PROMPT_VERSIONS_JSON` env vars in `infra/lambda.tf`
6. Add the new schema as a `source` block in both the `extractor` and `validator` archive_file resources in `infra/lambda.tf`
7. Update the valid labels set in `lambda/classifier/handler.py`
