# Plan Review

## Verdict
**NEEDS REVISION** — all six original flaws were correctly resolved. However, the revision introduced two new flaws, one of which is deployment-blocking: the first-deploy bootstrapping sequence is self-defeating because the build script's own guard will reject the image-push step before the Lambda function exists.

---

## Flaws Found

### Status of the 6 original flaws

- **Original Flaw 1 (ECR IAM policy on execution role):** RESOLVED. `infra/iam.tf` is no longer in the impacted files list. No ECR pull permissions are added to the execution role.
- **Original Flaw 2 (public ECR placeholder URI):** RESOLVED. Risk 2 mitigation now uses a correctly sequenced targeted-apply strategy. No `public.ecr.aws/...` placeholder is referenced.
- **Original Flaw 3 (stale Provisioned Concurrency from `publish = true` + `ignore_changes`):** RESOLVED. `publish = true` is removed from the Lambda Terraform resource. Provisioned Concurrency is managed entirely in the deploy script via `publish-version` + `put-provisioned-concurrency-config` after each image push.
- **Original Flaw 4 (`import types` missing from mock block):** RESOLVED. Step 7 item 1 now includes `import types` inside the code block alongside `import sys` and `from unittest import mock`.
- **Original Flaw 5 (`tfidf_cosine` absence guard removed):** RESOLVED. Step 7 item 3 asserts both `"tfidf_cosine" not in body` and `"rouge1" not in body` in the renamed `test_legacy_metrics_not_in_response` test.
- **Original Flaw 6 (unnecessary `boto3.client` mock in cap test):** RESOLVED. Step 7 item 10 calls `lambda_handler` directly with no boto3 mock.

### New flaws introduced by the revision

- **Flaw A — First-deploy bootstrapping sequence is self-defeating (deployment-blocking):** Step 4 instructs the script to include a guard: "if `terraform output gold_comparator_ecr_repository_name` returns empty, print a clear error and exit non-zero." Risk 2's first-deploy sequence then calls `./scripts/build_gold_comparator.sh` as step 2, after only the ECR repo has been created via a targeted `terraform apply`. At that point in the first-deploy sequence, `terraform output gold_comparator_function_name` will return an empty string or null — the Lambda function has not been created yet. The script's guard will trigger, printing an error and exiting non-zero. The image push never happens. This means step 2 of the three-step bootstrapping sequence always fails on first deploy, making it impossible to complete the sequence as written. The consequence is that first deploy is blocked: the operator cannot push the image, and therefore cannot complete `terraform apply` (step 3), because the Lambda `CreateFunction` call requires a valid image already in the private ECR repo.

- **Flaw B — `publish-version` called immediately after `update-function-code` without waiting for the function update to settle (potential runtime error):** Step 4 item 8 calls `aws lambda publish-version` immediately after `aws lambda update-function-code`. `update-function-code` is asynchronous and transitions the Lambda through a `Pending` state before reaching `Active`. If `publish-version` is called while the function is still `Pending`, AWS returns a `ResourceConflictException: The function is currently in the following state: Pending`. The plan contains no `aws lambda wait function-updated` call between these two commands. Consequence: the deploy script intermittently fails mid-run — specifically the `publish-version` call — leaving Provisioned Concurrency on an old version. Subsequent invocations will cold-start on `$LATEST` indefinitely until the script is re-run or manually corrected.

---

## Suggested Improvements

- **Improvement 1 — Fix the first-deploy bootstrapping guard logic:** The build script must distinguish between first-deploy (Lambda does not yet exist) and subsequent deploys (Lambda exists). The cleanest fix is to make the `gold_comparator_function_name` output lookup soft for the image-push phase and hard only for the `update-function-code` phase. Concretely: change the script guard so it exits non-zero only if the *ECR repo name* is empty (which is always available after the targeted apply). Allow the Lambda function name to be empty, and in that case, skip the `update-function-code`, `publish-version`, and `put-provisioned-concurrency-config` calls with an informational message such as `"Lambda function not yet created — image pushed; run terraform apply then re-run this script."` This makes the script safe for both first-deploy and subsequent deploys.

  Concretely, the script's guard block should be split into two guards:
  ```bash
  ECR_REPO_NAME=$(terraform -chdir="${SCRIPT_DIR}/../infra" output -raw gold_comparator_ecr_repository_name 2>/dev/null)
  if [ -z "$ECR_REPO_NAME" ]; then
    echo "ERROR: ECR repo name not found. Run 'terraform apply -target=aws_ecr_repository.gold_comparator' first."
    exit 1
  fi

  FUNCTION_NAME=$(terraform -chdir="${SCRIPT_DIR}/../infra" output -raw gold_comparator_function_name 2>/dev/null)
  FIRST_DEPLOY=false
  if [ -z "$FUNCTION_NAME" ]; then
    echo "INFO: Lambda function not yet created. Image will be pushed but function update will be skipped."
    FIRST_DEPLOY=true
  fi
  ```

  Then after the image push:
  ```bash
  if [ "$FIRST_DEPLOY" = "false" ]; then
    aws lambda update-function-code ...
    aws lambda wait function-updated --function-name "$FUNCTION_NAME"
    VERSION=$(aws lambda publish-version ...)
    aws lambda put-provisioned-concurrency-config ...
  else
    echo "INFO: First deploy — image pushed. Run 'terraform apply' then re-run this script to complete setup."
  fi
  ```

- **Improvement 2 — Add `aws lambda wait function-updated` before `publish-version`:** Between the `update-function-code` call and the `publish-version` call in Step 4 item 8, insert:
  ```bash
  aws lambda wait function-updated --function-name "$FUNCTION_NAME"
  ```
  This blocks until the Lambda transitions from `Pending` to `Active`, eliminating the `ResourceConflictException` race condition. The wait typically completes in 5–30 seconds.

- **Improvement 3 — Add `-chdir` flag to all `terraform output` calls in the script:** The CLAUDE.md convention and the project's CI use `terraform -chdir=infra` consistently. The build script should derive its Terraform working directory relative to the script's own location:
  ```bash
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  INFRA_DIR="${SCRIPT_DIR}/../infra"
  ```
  Then use `terraform -chdir="$INFRA_DIR" output -raw <name>` for all output lookups. Without `-chdir`, the script will fail if run from any directory other than the repo root.

- **Improvement 4 — Update the Risk 2 bootstrapping description to match the corrected script behaviour:** Once Improvement 1 is applied, the bootstrapping sequence becomes:
  1. `terraform apply -target=aws_ecr_repository.gold_comparator -target=aws_ecr_lifecycle_policy.gold_comparator`
  2. `./scripts/build_gold_comparator.sh` — pushes image, detects Lambda is absent, prints info message and exits 0.
  3. `terraform apply` — creates the Lambda function.
  4. `./scripts/build_gold_comparator.sh` — this time Lambda exists; calls `update-function-code`, waits, publishes version, configures Provisioned Concurrency.

  The Risk 2 section should document this four-step first-deploy sequence rather than the three-step sequence currently described.

---

## Revised Steps (if applicable)

**Revised Step 4 — Build and deploy script (replace items 7–8 and the guard block):**

Replace the current guard and `update-function-code`/`publish-version` block with the following logic:

```bash
# --- Resolve Terraform working directory ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="${SCRIPT_DIR}/../infra"

# --- Resolve ECR repo name (required; fail hard if absent) ---
ECR_REPO_NAME=$(terraform -chdir="$INFRA_DIR" output -raw gold_comparator_ecr_repository_name 2>/dev/null)
if [ -z "$ECR_REPO_NAME" ]; then
  echo "ERROR: ECR repo name not found in Terraform state."
  echo "Run: terraform -chdir=infra apply -target=aws_ecr_repository.gold_comparator -target=aws_ecr_lifecycle_policy.gold_comparator"
  exit 1
fi

# --- Resolve Lambda function name (optional on first deploy) ---
FUNCTION_NAME=$(terraform -chdir="$INFRA_DIR" output -raw gold_comparator_function_name 2>/dev/null)
FIRST_DEPLOY=false
if [ -z "$FUNCTION_NAME" ]; then
  echo "INFO: Lambda function not yet created — image will be pushed only."
  echo "      After this script exits, run 'terraform apply' then re-run this script."
  FIRST_DEPLOY=true
fi

# ... (region, account ID, ECR auth, docker build, docker push as specified) ...

# --- Update Lambda and configure Provisioned Concurrency (skipped on first deploy) ---
if [ "$FIRST_DEPLOY" = "false" ]; then
  aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --image-uri "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}:latest" \
    --region "$AWS_REGION"

  # Wait for function update to complete before publishing a version
  aws lambda wait function-updated \
    --function-name "$FUNCTION_NAME" \
    --region "$AWS_REGION"

  VERSION=$(aws lambda publish-version \
    --function-name "$FUNCTION_NAME" \
    --region "$AWS_REGION" \
    --query 'Version' --output text)

  aws lambda put-provisioned-concurrency-config \
    --function-name "$FUNCTION_NAME" \
    --qualifier "$VERSION" \
    --provisioned-concurrent-executions 1 \
    --region "$AWS_REGION"

  echo "SUCCESS: Lambda updated to version $VERSION with Provisioned Concurrency."
fi
```

**Revised Risk 2 first-deploy bootstrapping sequence:**

Replace the three-step sequence with:
1. `terraform apply -target=aws_ecr_repository.gold_comparator -target=aws_ecr_lifecycle_policy.gold_comparator` — creates the private ECR repo only.
2. `./scripts/build_gold_comparator.sh` — builds and pushes the initial image; detects Lambda is absent and exits cleanly with an informational message.
3. `terraform apply` — creates the Lambda function, referencing the private ECR repo that now contains a valid image.
4. `./scripts/build_gold_comparator.sh` — now that Lambda exists, calls `update-function-code`, waits for `Active` state, publishes a version, and configures Provisioned Concurrency on it.

For subsequent deploys (CI/CD): `terraform apply` (ECR already exists; Lambda `image_uri` is lifecycle-ignored) then `./scripts/build_gold_comparator.sh` — performs the full update, wait, publish, and Provisioned Concurrency configuration.

---

## Summary

All six original flaws were correctly resolved by the planner's revision. The revised plan introduced two new issues: a deployment-blocking logical contradiction in the first-deploy bootstrapping sequence (the build script's guard kills the image-push step before the Lambda exists), and a race condition between `update-function-code` and `publish-version` that will intermittently fail in CI due to missing `wait function-updated`. Both are straightforward to fix with the corrected script logic above. The core architectural approach remains sound.
