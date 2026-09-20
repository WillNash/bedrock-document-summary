# bedrock-document-summary

Serverless medical document summarization pipeline on AWS. Upload a document via the browser; Claude classifies it, extracts structured data, validates it against a JSON schema, and renders a readable summary — all within a Step Functions Express workflow.

## Supported document types

- Lab results
- Doctor's notes
- Injury documentation
- Visit assessments
- Psych evaluations

## Architecture

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

**AWS services:** Lambda (Python 3.12, arm64), Step Functions Express, S3, DynamoDB, API Gateway v2, CloudFront, Cognito, Bedrock (Claude Sonnet for extraction, Haiku for classification), Bedrock Prompt Management, WAF, KMS, X-Ray, CloudWatch.

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

The IAM user needs permissions to create, update, and delete all resources in the stack (Lambda, S3, DynamoDB, API Gateway, CloudFront, Cognito, Step Functions, Bedrock, WAF, KMS, IAM roles, CloudWatch, SQS, SNS).

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
lambda/         Python handler for each Lambda function
schemas/        JSON schemas for structured extraction (one per document type)
templates/      Jinja2 summary templates (one per document type)
prompts/        System prompts for classification and extraction
infra/          Terraform — one .tf file per concern
bootstrap/      Terraform module that creates the S3 state bucket and DynamoDB lock table (run once to enable CI/CD)
scripts/        build_lambdas.sh, deploy_frontend.sh, ensure_guardrail.sh (all called by CI/CD)
tests/          pytest unit tests
frontend/       Vanilla JS SPA (config.js generated at deploy time by deploy_frontend.sh)
```

### Adding a document type

1. Add a JSON schema to `schemas/`
2. Add a Jinja2 template to `templates/`
3. Add a prompt file to `prompts/`
4. Add a `aws_bedrock_prompt` + `aws_bedrock_prompt_version` resource in `infra/bedrock.tf`
5. Add the new type to the `PROMPT_ARNS_JSON` / `PROMPT_VERSIONS_JSON` env vars in `infra/lambda.tf`
6. Add the new schema as a `source` block in both the `extractor` and `validator` archive_file resources in `infra/lambda.tf`
7. Update the valid labels set in `lambda/classifier/handler.py`
