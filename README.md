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
terraform -chdir=infra init
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
