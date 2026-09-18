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

## Prerequisites

- AWS CLI configured with credentials for the target account
- Terraform >= 1.6
- Python 3.12 and pip (for building the Lambda layer)
- Bedrock model access enabled in your account for Claude Sonnet and Haiku

## Deploy

### 1. Build the Lambda layer

```bash
./scripts/build_lambdas.sh
```

Creates `infra/lambda_packages/layer.zip` with `jinja2` and `jsonschema`. Must be run before every `terraform apply`.

### 2. Configure

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars
cp infra/backend.hcl.example infra/backend.hcl
```

Edit `terraform.tfvars`. The only required variable is `project_name`. Key options:

| Variable | Default | Notes |
|---|---|---|
| `project_name` | *(required)* | Used as a prefix for all resource names |
| `aws_region` | `us-east-1` | Target deployment region |
| `environment` | `prod` | |
| `bedrock_model_id` | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | Must use a geo/global prefix |
| `bedrock_classifier_model_id` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Must use a geo/global prefix |
| `alert_email` | *(unset)* | Email for CloudWatch alarms and cost anomaly alerts |

### 3. First apply

```bash
terraform -chdir=infra init -backend-config=backend.hcl
terraform -chdir=infra apply
```

Leave `cognito_callback_urls` at the localhost default for now.

### 4. Deploy the frontend

```bash
./scripts/deploy_frontend.sh
```

Reads Terraform outputs, generates `frontend/config.js`, syncs assets to S3, and invalidates the CloudFront cache. Prints the live URL when done.

### 5. Update Cognito callback URLs

Edit `terraform.tfvars` with the CloudFront URL from the previous step:

```hcl
cognito_callback_urls = ["https://<your-cloudfront-domain>/callback"]
cognito_logout_urls   = ["https://<your-cloudfront-domain>"]
```

Then apply again — only the Cognito App Client is updated:

```bash
terraform -chdir=infra apply
```

## CI/CD

Two GitHub Actions workflows are included:

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | Every push; PRs to main | Runs pytest on all branches. On pushes to main, also runs `terraform fmt`, `validate`, and `plan`. |
| `deploy.yml` | Manual (`workflow_dispatch`) | Builds the Lambda layer, runs `terraform apply`, deploys the frontend. |

### One-time setup

#### 1. Create Terraform state infrastructure

Terraform needs a remote backend so state is shared between your machine and CI. Create an S3 bucket and a DynamoDB table for locking:

```bash
# Replace the names — bucket names are globally unique
aws s3api create-bucket \
  --bucket your-project-tf-state \
  --region us-east-1

aws s3api put-bucket-versioning \
  --bucket your-project-tf-state \
  --versioning-configuration Status=Enabled

aws dynamodb create-table \
  --table-name your-project-tf-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

#### 2. Create your local backend config

```bash
cp infra/backend.hcl.example infra/backend.hcl
```

Edit `infra/backend.hcl` with the bucket and table names you just created:

```hcl
bucket         = "your-project-tf-state"
key            = "bedrock-doc-summary/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "your-project-tf-locks"
```

`backend.hcl` is gitignored — it stays on your machine and in GitHub secrets only.

#### 3. Migrate local state to S3

If you have existing local state (from a previous `terraform apply`), reinitialise to migrate it:

```bash
terraform -chdir=infra init -backend-config=backend.hcl -migrate-state
```

If this is a fresh repo with no prior state, omit `-migrate-state`:

```bash
terraform -chdir=infra init -backend-config=backend.hcl
```

#### 4. Commit terraform.tfvars

`infra/terraform.tfvars` is tracked by git (none of its values are sensitive). If you haven't committed it yet:

```bash
git add infra/terraform.tfvars
git commit -m "add terraform.tfvars"
```

#### 5. Add GitHub secrets

Go to **Settings → Secrets and variables → Actions** in your GitHub repository and add:

| Secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | Access key ID for a CI IAM user |
| `AWS_SECRET_ACCESS_KEY` | Secret access key for that user |
| `TF_BACKEND_CONFIG` | The full contents of your `infra/backend.hcl` |

The IAM user needs permissions to create, update, and delete all resources in the stack (Lambda, S3, DynamoDB, API Gateway, CloudFront, Cognito, Step Functions, Bedrock, WAF, KMS, IAM roles, CloudWatch, SQS, SNS). Using `AdministratorAccess` is the easiest starting point; scope it down to least-privilege once the stack is stable.

#### 6. Optionally configure the production environment

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
scripts/        build_lambdas.sh, deploy_frontend.sh
tests/          pytest unit tests
frontend/       Vanilla JS SPA (config.js generated at deploy time)
```

### Adding a document type

1. Add a JSON schema to `schemas/`
2. Add a Jinja2 template to `templates/`
3. Add a prompt file to `prompts/`
4. Add a `aws_bedrock_prompt` + `aws_bedrock_prompt_version` resource in `infra/bedrock.tf`
5. Add the new type to the `PROMPT_ARNS_JSON` / `PROMPT_VERSIONS_JSON` env vars in `infra/lambda.tf`
6. Add the new schema as a `source` block in both the `extractor` and `validator` archive_file resources in `infra/lambda.tf`
7. Update the valid labels set in `lambda/classifier/handler.py`
