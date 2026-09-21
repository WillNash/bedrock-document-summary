# Claude Context Explorer — Gold Standard Evaluator Page

Task: Document everything needed to build Pathway 2 (Gold Standard) as a new frontend page.

---

## 1. Existing Test Page — `/workspace/active_repo/frontend/test.html` + `/workspace/active_repo/frontend/test.js`

### HTML structure (test.html)
- Single `.card` container inside `#app` (max-width 760px — wider than the main app's 640px).
- Three top-level sections toggled via `.hidden`:
  - `#auth-section` — sign-in button shown when not authenticated.
  - `#test-section` — the working UI (file picker, run count spinner, run button, progress grid, comparison panel, sign-out).
  - Inside `#test-section`:
    - `.config-row` — holds `.file-area` (label + hidden file input + `.file-name` span), `.run-config` (label + number input), and `.btn-primary` run button.
    - `#progress-panel.hidden` — `#progress-header` (status text), `#run-grid` (tile grid), `#error-log`.
    - `#comparison-panel.hidden` — `.comparison-header` (h2 + `#comparison-run-count`), `#comparison-metrics` (metric cards), `.comparison-matrix-heading`, `#similarity-matrix`.
    - `.signout-row` — sign-out link button.
- External scripts: `config.js` (generated at deploy time) then `test.js`.
- JSZip loaded from CDN (`jszip@3.10.1`).

### Auth flow (test.js)
- Reads `window.APP_CONFIG` from `config.js` for `cognitoHostedUiDomain`, `cognitoClientId`, `apiUrl`.
- `REDIRECT_URI` is always `window.location.origin + '/'` (the root path). This means the Cognito callback doesn't need a `/gold-standard.html` entry — it shares the existing redirect.
- Tokens stored in `localStorage` under keys `id_token`, `access_token`, `refresh_token`.
- `init()` on load: reads stored `id_token`, falls back to `tryRefresh()`, or shows the auth section.
- `startSignIn()` stores `auth_return` in localStorage so `app.js` can redirect back after the OAuth callback.
- `ensureValidToken()` called before every API request; triggers refresh or `handleSessionExpired()`.

### Job submission / polling flow (test.js)
- `submitJob(file, runNum)`:
  1. `POST /presign` with `{filename}`, Bearer token → `{job_id, presign_url, presign_fields}`.
  2. Build `FormData` with `presign_fields` entries then append `file` last, POST to `presign_url`.
  3. Returns `job_id`; tile goes to `pending` state.
- `pollUntilDone(job_id, runNum)`:
  1. Loop up to 120 ticks (5 s each = 10 min max).
  2. `GET /jobs/{job_id}` — checks `data.status`.
  3. On `COMPLETED`: `GET /summaries/{job_id}` → `{summary, usage}`.
  4. On `FAILED`: throws with `data.error_message`.
- Multiple jobs are submitted with 200 ms stagger (to protect DynamoDB quota) but polled in parallel via `Promise.all`.

### Comparison call (test.js)
- `runComparison(summaries)`:
  - `POST /compare` with `{texts: [string, ...]}`, Bearer token.
  - Returns comparison object (see comparator response shape below).
- Only called when `succeeded >= 2`.

### Zip builder (test.js)
- Uses JSZip to build a folder `consistency_{timestamp}/` containing:
  - `summary_NN.txt` for each successful run.
  - `manifest.txt`.
  - `usage_report.txt` (tabular token usage per stage per run).
  - `comparison.json` and `comparison_report.txt` if comparison succeeded.
- Triggers browser download via a temporary `<a>` element.

---

## 2. Comparator Lambda — `/workspace/active_repo/lambda/comparator/handler.py`

### Request shape
```
POST /compare
Authorization: Bearer <id_token>
Content-Type: application/json

{
  "texts": ["string", "string", ...]   // 2–200 entries, all strings
}
```

### Response shape (200 OK)
```json
{
  "embeddings": [[...1024 floats...], ...],
  "embedding_cosine": {
    "matrix": [[float, ...], ...],
    "n_runs": int,
    "n_pairs": int,
    "mean": float,
    "min": float,
    "max": float,
    "std": float,
    "variance": float,
    "cv": float | null
  },
  "tfidf_cosine": {
    "matrix": [[float, ...], ...],
    "n_runs": int,
    "n_pairs": int,
    "mean": float,
    "min": float,
    "max": float,
    "std": float,
    "variance": float,
    "cv": float | null
  }
}
```

### Implementation details
- Pure stdlib + boto3 — no numpy, no sklearn. All math is hand-coded Python.
- Calls `bedrock-runtime.invoke_model()` for each text using `amazon.titan-embed-text-v2:0` with `{"inputText": text, "dimensions": 1024, "normalize": true}`. Titan returns pre-normalised vectors so cosine similarity = dot product.
- Embedding matrix: N×N, computed via `itertools.combinations`.
- TF-IDF: pure Python — tokenizes with `re.findall(r'\b[a-z]{2,}\b')`, computes IDF, normalises vectors, then dot products.
- `_variability_stats(n_runs, scores)` takes the upper-triangle list (not the full matrix), returns the stats dict.
- Error responses: `{"error": "message"}` with appropriate 4xx statusCode.

### What the comparator does NOT do
- Does NOT accept a reference text. Every text in the input list is treated symmetrically — pairwise N×N.
- Does NOT return individual per-text scores against a reference.

---

## 3. API Gateway — `/workspace/active_repo/infra/api_gateway.tf`

### Structure
- `aws_apigatewayv2_api.main` — HTTP API, CORS configured for CloudFront origin only. Allow-methods: GET, POST, OPTIONS.
- `aws_apigatewayv2_authorizer.cognito` — JWT authorizer using Cognito user pool.
- `aws_apigatewayv2_stage.default` — `$default` stage, auto_deploy=true, JSON access logging.
- All routes use `authorization_type = "JWT"` with `authorizer_id = aws_apigatewayv2_authorizer.cognito.id`.

### Existing routes
| Route key | Integration | Lambda |
|---|---|---|
| `POST /compare` | comparator | `aws_lambda_function.comparator` |
| `POST /presign` | api_presign | `aws_lambda_function.api_presign` |
| `GET /jobs/{jobId}` | api_status | `aws_lambda_function.api_status` |
| `GET /summaries/{jobId}` | api_summary | `aws_lambda_function.api_summary` |

### Pattern for a new route (e.g. `POST /gold-compare`)
1. `aws_apigatewayv2_integration.gold_comparator` — `integration_type = "AWS_PROXY"`, `payload_format_version = "2.0"`, `integration_uri = aws_lambda_function.gold_comparator.invoke_arn`.
2. `aws_apigatewayv2_route.gold_compare` — `route_key = "POST /gold-compare"`, JWT auth, `target = "integrations/${...integration.id}"`.
3. `aws_lambda_permission.apigw_gold_comparator` — `action = "lambda:InvokeFunction"`, `principal = "apigateway.amazonaws.com"`, `source_arn = "${aws_apigatewayv2_api.main.execution_arn}/*/*"`.

---

## 4. IAM Pattern — `/workspace/active_repo/infra/iam.tf`

### Per-function role anatomy (using comparator as the cleanest example)
```hcl
resource "aws_iam_role" "comparator" {
  name               = "${local.name_prefix}-comparator-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "comparator_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.comparator.id
  policy = jsonencode({...logs to /aws/lambda/${local.name_prefix}-comparator:*...})
}

resource "aws_iam_role_policy" "comparator_bedrock" {
  name = "bedrock-invoke"
  role = aws_iam_role.comparator.id
  policy = jsonencode({ Statement = [{ Effect="Allow", Action=["bedrock:InvokeModel"], Resource=["*"] }] })
}

resource "aws_iam_role_policy" "comparator_xray" {
  name = "xray"
  role = aws_iam_role.comparator.id
  policy = jsonencode({ Statement = [{ Effect="Allow", Action=local.xray_actions, Resource="*" }] })
}
```

The gold standard comparator needs identical policies (logs, bedrock invoke for Titan, xray). No DynamoDB, no S3, no KMS needed — same as the existing comparator.

---

## 5. Lambda Function Pattern — `/workspace/active_repo/infra/lambda.tf`

### archive_file pattern (simple source_dir, like comparator)
```hcl
data "archive_file" "gold_comparator" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/gold_comparator"
  output_path = "${path.module}/lambda_packages/gold_comparator.zip"
}
```

### aws_lambda_function pattern (modelled on comparator)
```hcl
resource "aws_lambda_function" "gold_comparator" {
  function_name    = "${local.name_prefix}-gold-comparator"
  filename         = data.archive_file.gold_comparator.output_path
  source_code_hash = data.archive_file.gold_comparator.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  role             = aws_iam_role.gold_comparator.arn
  timeout          = 30
  memory_size      = 256

  tracing_config { mode = "Active" }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["gold-comparator"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}
```

The existing comparator has no environment variables. The gold comparator similarly needs none.

---

## 6. CloudWatch Log Groups — `/workspace/active_repo/infra/cloudwatch.tf`

### Current `lambda_function_names` list
```hcl
locals {
  lambda_function_names = [
    "api-presign", "api-status", "api-summary",
    "pipeline-starter",
    "classifier", "extractor", "validator", "renderer",
    "fail-handler",
    "comparator",
  ]
}
```

The `aws_cloudwatch_log_group.lambda` resource is a `for_each` over this set. Each entry creates `/aws/lambda/${local.name_prefix}-${each.key}`.

**To add the gold comparator:** append `"gold-comparator"` to this list. That single change creates the log group referenced by the new Lambda's `logging_config`.

---

## 7. Frontend CSS — `/workspace/active_repo/frontend/style.css`

### Classes the new page can reuse directly (no additions needed)
| Class | Usage |
|---|---|
| `.card` | White rounded card with box shadow |
| `.btn-primary` | Blue filled button (sign in, run) |
| `.btn-secondary` | Grey button (used as file picker label) |
| `.btn-link` | Subtle underlined text button (sign out) |
| `.hidden` | `display: none !important` toggle |
| `.config-row` | Flex row: file area + controls + action button |
| `.file-area` | File picker label + file name span |
| `.file-name` | Truncating filename display |
| `.run-config` | Label + number input pair |
| `.run-config input[type="number"]` | Styled number spinner |
| `.progress-header` | Status/progress text above tile grid |
| `.run-grid` | Auto-fill tile grid |
| `.run-tile` + state classes (`.queued`, `.uploading`, `.pending`, `.running`, `.processing`, `.done`, `.failed`) | Coloured status tiles |
| `.run-num`, `.run-status` | Tile label text |
| `#error-log`, `.run-error-entry` | Red error log panel |
| `.comparison-header` | Flex row with border-top separator |
| `.comparison-subhead` | Grey subtitle next to h2 |
| `.comparison-metrics` | 2-column grid of metric cards |
| `.metric-card` | Individual metric card (grey bg, border) |
| `.metric-card-title` | Uppercase label at top of card |
| `.metric-row` | 4-column grid: Mean, Min, Max, Std |
| `.metric-stat`, `.metric-stat-label`, `.metric-stat-value` | Stat cell inside metric-row |
| `.comparison-matrix-heading` | Label above matrix table |
| `.matrix-scroll` | Horizontally scrollable matrix wrapper |
| `.sim-matrix`, `.sim-matrix th`, `.sim-matrix td` | Matrix table |
| `.sim-matrix td.diag`, `.high`, `.mid`, `.low` | Coloured matrix cells |
| `.signout-row` | Right-aligned bottom row |
| `.error-text` | Red inline error block |

### What the new page needs that isn't in the stylesheet
- A "reference upload" area distinct from the "runs" upload area. Could be an additional `.file-area` row with a different label, or a second `.config-row`. No new CSS class needed if the same structure is reused.
- Possibly a "reference label" on the comparison panel to distinguish the gold standard reference from the N summaries. Could be handled with a new section heading using existing `h2` + `.comparison-subhead` pattern.
- The matrix on the gold standard page will be N×1 (or displayed as a bar/list of scores, not a square N×N matrix). The existing `.sim-matrix` table can still be used if rendered as a single-column table.

---

## 8. Pathway 2 — Gold Standard (from `consistency-evaluator-plan.md`)

> **Pathway 2 — Gold standard** (future): N outputs + 1 reference → N individual similarity scores → mean/min/std against the reference. Answers: "how accurate is the pipeline?"

### Key constraints from the plan
- Pathway 2 must be **completely separate** from Pathway 1. No shared function signatures with optional `reference` parameter.
- The only shared infrastructure is `_collect_runs()` (N-run Bedrock collection).
- The CLI tool for Pathway 2 should be named `gold_standard_evaluator.py` (separate from `consistency_evaluator.py`).
- At the API/Lambda level: the new Lambda must be a separate function (`gold_comparator` or similar), not a modified comparator. The existing `/compare` endpoint and `comparator` Lambda must not be changed.

### What Pathway 2 computes
- Input: N summaries (strings) + 1 reference summary (string).
- For each of the N summaries: compute similarity against the reference (embedding cosine, TF-IDF cosine).
- Output: N individual scores per metric, plus mean/min/std across those N scores.
- No pairwise N×N matrix — the matrix is replaced by a vector of N scores.

### Proposed Lambda request shape for the new `POST /gold-compare` endpoint
```json
{
  "texts": ["summary_1", "summary_2", ...],   // N strings (2–200)
  "reference": "the gold standard summary"     // 1 string
}
```

### Proposed Lambda response shape
```json
{
  "reference_embedding": [...1024 floats...],
  "embedding_cosine": {
    "scores": [float, ...],      // one per text, against reference
    "mean": float,
    "min": float,
    "max": float,
    "std": float,
    "n": int
  },
  "tfidf_cosine": {
    "scores": [float, ...],
    "mean": float,
    "min": float,
    "max": float,
    "std": float,
    "n": int
  }
}
```

---

## 9. No Existing Gold Standard Lambda

There is no existing gold standard Lambda or tool beyond what is described in the plan. The `tools/consistency_evaluator.py` and `tools/consistency_evaluator_cloud.py` files exist but are Pathway 1 (pairwise variability). No `gold_standard_evaluator.py` or `gold_comparator` Lambda directory exists yet.

---

## Summary of New Files/Changes Required

### New files
| File | Purpose |
|---|---|
| `lambda/gold_comparator/handler.py` | New Lambda: accepts `{texts, reference}`, returns per-text similarity scores against reference |
| `frontend/gold-standard.html` | New page: same structure as `test.html` but with a second file picker for the reference |
| `frontend/gold-standard.js` | Page logic: same job submission/polling as `test.js`, plus reference upload, calls `POST /gold-compare` |

### Infra changes
| File | Change |
|---|---|
| `infra/cloudwatch.tf` | Append `"gold-comparator"` to `lambda_function_names` list |
| `infra/lambda.tf` | Add `data.archive_file.gold_comparator` + `aws_lambda_function.gold_comparator` |
| `infra/iam.tf` | Add `aws_iam_role.gold_comparator` + policies (logs, bedrock invoke, xray) |
| `infra/api_gateway.tf` | Add integration, route (`POST /gold-compare`), and Lambda permission |

### Frontend deploy
- `scripts/deploy_frontend.sh` syncs the `frontend/` directory to S3. No changes needed to the deploy script; `gold-standard.html` and `gold-standard.js` will be synced automatically.
- `config.js` is shared by all pages — no change needed.
- CloudFront may need `gold-standard.html` added to the invalidation pattern, but the existing `/*` invalidation covers it.

---

## Side-Effects / Risks for the Planner

1. **Comparator timeout**: The existing comparator `timeout = 30s`. For N=200 texts + 1 reference, embedding N+1 texts via Titan sequentially could approach or exceed 30 s. Consider 60 s timeout for the gold comparator or a smaller default N cap (e.g. 50).

2. **Memory**: The existing comparator uses `memory_size = 256`. Should be sufficient for the gold comparator (same pure-Python approach, no ML libraries loaded into the Lambda).

3. **Bedrock permissions**: The gold comparator needs `bedrock:InvokeModel` on `*` for Titan Text Embeddings v2 (`amazon.titan-embed-text-v2:0`). This is the same permission as the existing `comparator_bedrock` policy — copy verbatim.

4. **CORS**: The existing API Gateway CORS config allows `POST` from the CloudFront origin. No change needed — `POST /gold-compare` is covered.

5. **Cognito redirect**: The new page uses the same `REDIRECT_URI = window.location.origin + '/'` trick as `test.js`. No new Cognito callback URL needed.

6. **Reference upload**: The reference is a text string uploaded as a file. The gold standard page should read it client-side (e.g. `file.text()`) and send it as the `reference` field in the `POST /gold-compare` body — not as a presigned upload. This avoids a separate pipeline run for the reference.

7. **No zip changes needed**: The gold standard page may or may not offer a zip download. If it does, the same JSZip CDN script can be reused. The zip would contain: `summary_NN.txt` files, `reference.txt`, `comparison.json`, and a text report.

8. **Matrix display**: The gold standard page does not produce an N×N matrix. Replace the `.comparison-matrix-heading` + `.matrix-scroll` section with a ranked list or bar-style table of N scores (one row per run). Existing CSS `.sim-matrix` table structure can be repurposed as a 2-column table: "Run | Score".
