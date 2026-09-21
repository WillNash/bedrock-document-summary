# Architecture Plan

## Canonical Filename Notice

**IMPORTANT — filename authority:** The canonical filenames for this feature are `gold.html` and `gold.js`. The explorer document (`claude-context-explorer.md`) uses the names `gold-standard.html` and `gold-standard.js` in its summary section. Those names are superseded by this plan. All references — HTML `<a href>` attributes, `<script src>` attributes, navigation links, zip manifest text, and test instructions — must use `gold.html` and `gold.js` exactly.

---

## Context Summary

Add a "Gold Standard" evaluation page (Pathway 2) to the frontend that allows a user to run N pipeline jobs against a single uploaded reference text, then calls a new dedicated `POST /gold-compare` Lambda endpoint to compute per-run embedding cosine similarity and ROUGE-1 F1 scores against the reference — answering "how accurate is the pipeline?" The new Lambda, IAM role, API route, and frontend page are all completely separate from the existing Pathway 1 (`/compare`) infrastructure.

---

## Impacted Files

### New files to create

| File | Purpose |
|---|---|
| `lambda/gold_comparator/handler.py` | New Lambda handler: accepts `{texts, reference}`, returns per-run embedding cosine + ROUGE-1 scores with mean/min/max/std |
| `tests/test_gold_comparator.py` | Unit tests for the new Lambda (mirrors `tests/test_comparator.py` structure) |
| `frontend/gold.html` | New page: same structure as `test.html` with an additional reference file picker |
| `frontend/gold.js` | Page logic: job submission/polling identical to `test.js`, plus reference file reading, call to `POST /gold-compare`, results panel, zip download |

### Existing files to modify

| File | Change |
|---|---|
| `infra/cloudwatch.tf` | Append `"gold-comparator"` to `lambda_function_names` list (line 10) |
| `infra/lambda.tf` | Add `data.archive_file.gold_comparator` block and `aws_lambda_function.gold_comparator` resource |
| `infra/iam.tf` | Add `aws_iam_role.gold_comparator`, `aws_iam_role_policy.gold_comparator_logs`, `aws_iam_role_policy.gold_comparator_bedrock`, `aws_iam_role_policy.gold_comparator_xray` |
| `infra/api_gateway.tf` | Add `aws_apigatewayv2_integration.gold_comparator`, `aws_apigatewayv2_route.gold_compare`, `aws_lambda_permission.apigw_gold_comparator` |
| `frontend/test.html` | Add nav link to `gold.html` in the `signout-row` |
| `frontend/index.html` | Add nav link to `gold.html` in the `signout-row` |

---

## Step-by-Step Execution Plan

### Step 1 — Create `lambda/gold_comparator/handler.py`

Create the directory `lambda/gold_comparator/` and write `handler.py`.

**Request contract:**
```
POST /gold-compare
Authorization: Bearer <id_token>
Content-Type: application/json

{
  "texts": ["summary_1", "summary_2", ...],   // 2–200 strings
  "reference": "gold standard reference text"  // 1 non-empty string
}
```

**Response contract (200 OK):**
```json
{
  "embedding_cosine": {
    "scores": [0.87, 0.91, ...],
    "mean": float,
    "min": float,
    "max": float,
    "std": float,
    "n": int
  },
  "rouge1": {
    "scores": [0.62, 0.71, ...],
    "mean": float,
    "min": float,
    "max": float,
    "std": float,
    "n": int
  }
}
```

**Metric scope — no TF-IDF:** No `tfidf_cosine` metric is computed or returned. TF-IDF is excluded because ROUGE-1 already provides lexical overlap measurement and the two are redundant for gold-standard evaluation. The response top-level keys are exactly `{"embedding_cosine", "rouge1"}` — no others.

**Validation order:** Validate in this order, returning on the first failure:
1. JSON parseable (return 400 if `json.loads` raises).
2. `texts` present and is a list (return 400 if key absent or value is not a list).
3. `texts` length 2–200 (return 400 if fewer than 2 or more than 200).
4. All entries in `texts` are strings (return 400 if any entry is not a `str`).
5. `reference` present and non-empty string (return 400 if key absent, value is not a `str`, or value is empty after stripping).

**Implementation details:**

- Module-level constants: `EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"`, `EMBEDDING_DIMENSIONS = 1024`, `MAX_TEXTS = 200`.
- Embedding calls: use `concurrent.futures.ThreadPoolExecutor` to call `bedrock-runtime.invoke_model` for all N texts in parallel; make one additional sequential call for the reference embedding. This keeps total Bedrock latency well within the 30-second API Gateway hard limit for reasonable N values. Each call uses `{"inputText": text, "dimensions": 1024, "normalize": True}` and reads `response["body"].read()` then parses `["embedding"]`.
- Cosine similarity: for each text embedding, `sum(a * b for a, b in zip(text_emb, ref_emb))`. Because Titan returns unit-normalised vectors (`normalize=True`), this equals the cosine similarity exactly with no division step needed.
- ROUGE-1 F1: pure stdlib implementation. Tokenize with `re.findall(r'\b\w+\b', text.lower())` to strip punctuation. Compute clipped overlap (sum of `min(ref_count[t], hyp_count[t])` for each token in the reference). Compute recall = overlap/len(ref_tokens), precision = overlap/len(hyp_tokens), F1 = 2*p*r/(p+r) if (p+r)>0 else 0.0.
- Stats helper `_score_stats(scores)`: returns `{"scores": scores, "mean": ..., "min": ..., "max": ..., "std": ..., "n": len(scores)}`. Std uses population formula: `sum((x - mean)**2 for x in scores) / len(scores)` then `sqrt`. This divides by `len(scores)` (= N texts). This differs from the pairwise comparator's `_variability_stats` which divides by `n_pairs` (the upper-triangle count, not N). Both use population std — they are not interchangeable and must not be confused.
- Helper functions `_ok(body)` and `_err(status, message)` following the exact same pattern as the existing comparator.
- No environment variables required. No DynamoDB, S3, or KMS access needed.

**Error responses:**
- 400: JSON not parseable, missing or non-list `texts`, fewer than 2 texts, more than 200 texts, non-string entries in `texts`, missing or empty `reference`
- 500: unhandled exception (let Lambda runtime surface it; do not catch broadly)

### Step 2 — Create `tests/test_gold_comparator.py`

Mirror the structure of `tests/test_comparator.py`. Load the handler via `importlib.util.spec_from_file_location` pointing to `lambda/gold_comparator/handler.py`.

**Helper functions:**

`_bedrock_mock(input_text_to_vec)` — builds a thread-safe mock keyed by input text content (not call order), because `gold_comparator` uses `ThreadPoolExecutor` and call completion order is non-deterministic. Implement as a named function with `*args, **kwargs` and a fallback for positional body argument:

```python
def _bedrock_mock(input_text_to_vec):
    client = mock.MagicMock()
    def _side_effect(*args, **kwargs):
        body_bytes = kwargs.get('body') or (args[1] if len(args) > 1 else b'{}')
        input_text = json.loads(body_bytes)['inputText']
        return _make_response(input_text_to_vec[input_text])
    client.invoke_model.side_effect = _side_effect
    return client
```

`_event(texts, reference)`: returns `{"body": json.dumps({"texts": texts, "reference": reference})}`.

**Test classes:**

`TestValidation`:
- `test_missing_texts_returns_400`
- `test_missing_reference_returns_400`
- `test_empty_reference_returns_400`
- `test_single_text_returns_400` (texts list has only 1 entry)
- `test_above_max_texts_returns_400` (201 entries)
- `test_non_string_text_entry_returns_400`
- `test_invalid_json_returns_400`

`TestResponseStructure`:
- `test_200_for_valid_input`
- `test_top_level_keys` (must be exactly `{"embedding_cosine", "rouge1"}`)
- `test_tfidf_not_in_response` (assert `"tfidf_cosine"` is NOT a key in the response body)
- `test_stats_keys_in_each_metric` (must be `{"scores", "mean", "min", "max", "std", "n"}`)
- `test_scores_length_matches_texts_count`
- `test_n_matches_texts_count`

`TestMetricCorrectness`:
- `test_identical_embedding_gives_score_one`: reference vec = text vec = `[1.0, 0.0, 0.0]`, expect embedding_cosine scores all ≈ 1.0
- `test_orthogonal_embedding_gives_score_zero`: reference vec orthogonal to all text vecs, expect all ≈ 0.0
- `test_rouge1_identical_texts_score_one`: reference and all texts identical string, expect rouge1 scores all ≈ 1.0
- `test_rouge1_disjoint_texts_score_zero`: reference "apple banana", texts "cat dog elephant", expect rouge1 scores ≈ 0.0
- `test_invoke_model_called_n_plus_one_times`: N texts + 1 reference = N+1 calls total
- `test_all_values_are_plain_python_types`: no numpy floats, no custom objects in numeric fields
- `test_mean_is_average_of_scores`: verify `mean == sum(scores)/len(scores)` within floating-point tolerance

### Step 3 — Update `infra/cloudwatch.tf`

In the `lambda_function_names` list (currently 10 entries ending with `"comparator"`), append `"gold-comparator"` as the 11th entry. This creates the log group `/aws/lambda/${local.name_prefix}-gold-comparator` that the Lambda's `logging_config` block references.

```hcl
locals {
  lambda_function_names = [
    "api-presign", "api-status", "api-summary",
    "pipeline-starter",
    "classifier", "extractor", "validator", "renderer",
    "fail-handler",
    "comparator",
    "gold-comparator",   # ← add this line
  ]
}
```

### Step 4 — Update `infra/iam.tf`

Append a new IAM role block after the `comparator` role block (before the `fail_handler` role). Four resources, copied verbatim from the comparator role pattern:

```hcl
# ── gold_comparator role ─────────────────────────────────────────────────────

resource "aws_iam_role" "gold_comparator" {
  name               = "${local.name_prefix}-gold-comparator-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy" "gold_comparator_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.gold_comparator.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "arn:aws:logs:*:${local.account_id}:log-group:/aws/lambda/${local.name_prefix}-gold-comparator:*"
    }]
  })
}

resource "aws_iam_role_policy" "gold_comparator_bedrock" {
  name = "bedrock-invoke"
  role = aws_iam_role.gold_comparator.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = ["*"]
    }]
  })
}

resource "aws_iam_role_policy" "gold_comparator_xray" {
  name = "xray"
  role = aws_iam_role.gold_comparator.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = local.xray_actions, Resource = "*" }]
  })
}
```

### Step 5 — Update `infra/lambda.tf`

Add two blocks. First, the archive data source (after the `comparator` archive block, before `fail_handler`):

```hcl
data "archive_file" "gold_comparator" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/gold_comparator"
  output_path = "${path.module}/lambda_packages/gold_comparator.zip"
}
```

Second, the Lambda function resource (after `aws_lambda_function.comparator`, before `aws_lambda_function.fail_handler`):

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

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.lambda["gold-comparator"].name
  }

  tags       = local.common_tags
  depends_on = [aws_cloudwatch_log_group.lambda]
}
```

Note: `timeout = 30` matches the existing comparator and the hard API Gateway limit. The ThreadPoolExecutor parallelism in the handler means N concurrent Bedrock calls for text embeddings + 1 sequential call for the reference, so actual wall-clock time for N=10 will be approximately max(individual_call_latency) + 1 call ≈ 1–2 seconds. Only at very high N with very large texts (approaching 8K tokens each) would this approach the 30-second limit.

### Step 6 — Update `infra/api_gateway.tf`

Append three blocks after the existing comparator blocks. Add them in the same section ordering used by the existing file (integrations section, then routes section, then permissions section):

```hcl
# Integration
resource "aws_apigatewayv2_integration" "gold_comparator" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.gold_comparator.invoke_arn
  payload_format_version = "2.0"
}

# Route
resource "aws_apigatewayv2_route" "gold_compare" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "POST /gold-compare"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
  target             = "integrations/${aws_apigatewayv2_integration.gold_comparator.id}"
}

# Lambda permission
resource "aws_lambda_permission" "apigw_gold_comparator" {
  statement_id  = "AllowAPIGatewayInvokeGoldComparator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.gold_comparator.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
```

### Step 7 — Create `frontend/gold.html`

Structure mirrors `test.html` with these differences:

- Title: `Gold Standard Test — Document Summarizer`
- H1: `Gold Standard Test`
- Auth section paragraph: `Sign in to run a gold standard accuracy test.`
- Config row: TWO file-area blocks stacked in a `.config-row` (or two separate rows). First row: document file picker (`#doc-input`, label "Choose Document") + runs spinner + "Run Test" button. Second row: reference file picker (`#ref-input`, label "Choose Reference", `#ref-name` span). The reference row sits directly below the first row, visually grouped.
- No matrix panel. Replace `#comparison-panel`'s inner structure with: `.comparison-header` (h2 "Accuracy Results" + run-count subhead), `#comparison-metrics` (two metric cards: Embedding Cosine vs Reference and ROUGE-1 F1 vs Reference), `.comparison-matrix-heading` ("Per-Run Scores"), `#score-table` (div that will hold a 2-column `sim-matrix` table).
- Nav links in `signout-row`: link back to `test.html` ("Consistency Test") and sign-out button.
- **Script placement — order matters for correctness:** In the `<head>` (after the stylesheet link): JSZip CDN script (`jszip@3.10.1` from CDN). At the bottom of `<body>` (before `</body>`): `config.js` then `gold.js`. JSZip must be in `<head>` so it is defined before `gold.js` calls `new JSZip()`. Loading JSZip at the bottom would cause a `ReferenceError` on any code path that runs synchronously on page load.
- `max-width: 760px` on `#app` same as `test.html`.
- The reference picker input should accept `.txt,.md` only (reference texts are expected to be plain text, not PDFs; the document file picker accepts the same types as `test.html`: `.txt,.md,.csv,.pdf`).

### Step 8 — Create `frontend/gold.js`

**Auth block:** Copy verbatim from `test.js` — all PKCE helpers, token storage, `tryRefresh`, `ensureValidToken`, `handleSessionExpired`, `startSignIn`, `signOut`, `showAuth`, `showTest` (renamed `showGold`). Module-level variables: `idToken`, `isRunning`, `currentDocFile`, `currentRefFile`.

**Enable/disable logic:** The "Run Test" button is enabled only when `currentDocFile !== null && currentRefFile !== null && n >= 1 && n <= 200 && !isRunning`.

**Job submission and polling:** Copy verbatim from `test.js` — `submitJob`, `pollUntilDone` are identical. These use `currentDocFile` as the file argument.

**Reference reading:** Before calling the gold comparison endpoint, read the reference file client-side:
```javascript
async function readReferenceText(file) {
  return file.text();  // returns Promise<string>
}
```

**Gold comparison call:**
```javascript
async function runGoldComparison(summaries, referenceText) {
  if (!await ensureValidToken()) throw new Error('auth');
  const res = await fetch(`${API_URL}/gold-compare`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${idToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ texts: summaries, reference: referenceText }),
  });
  if (res.status === 401) throw new Error('auth');
  if (!res.ok) throw new Error(`gold-compare HTTP ${res.status}`);
  return res.json();
}
```

**Results display — `showGoldPanel(comparison, succeededCount)`:**
- Unhide `#comparison-panel`.
- Set `#comparison-run-count` text.
- Render two metric cards in `#comparison-metrics` using the same card HTML template as `test.js`'s `showComparisonPanel`, but with keys `embedding_cosine` (title "Titan Embedding Cosine vs Reference") and `rouge1` (title "ROUGE-1 F1 vs Reference"). The `metric-row` shows Mean / Min / Max / Std.
- Render a 2-column table in `#score-table` with heading "Run" and "Score" (two columns, one per metric side by side, or two separate tables each with columns Run | Score). Use the `.sim-matrix` class for styling. Each row: `R01`, `R02`, … with the score value coloured by the `high`/`mid`/`low` threshold classes (high ≥ 0.8, mid ≥ 0.6, low < 0.6 — different thresholds from the pairwise comparator since scores are against a reference, not between similar runs).

**Zip builder — `buildAndDownloadZip`:** Same structure as `test.js` but:
- Folder name: `gold_${timestamp}/`
- Download filename: `gold_${timestamp}.zip`
- `manifest.txt` header: "Gold Standard Test"
- Include `reference.txt` (the raw reference text)
- Include `gold_comparison.json` (the full comparison object)
- Include `gold_comparison_report.txt` (a text report — see below)
- Include `summary_NN.txt` per successful run and `usage_report.txt` (identical logic to `test.js`)

**Report builder — `buildGoldReport(docName, timestamp, succeededCount, comparison, referenceText)`:**
```
Gold Standard Accuracy Report
==============================
Document : <docName>
Reference: <first 80 chars of referenceText>...
Timestamp: <timestamp>
Runs     : <succeededCount>

── Titan Embedding Cosine vs Reference ──
  Mean   : X.XXXX    Min : X.XXXX    Max : X.XXXX
  Std Dev: X.XXXX

── ROUGE-1 F1 vs Reference ──
  Mean   : X.XXXX    Min : X.XXXX    Max : X.XXXX
  Std Dev: X.XXXX

── Per-Run Scores ──
Run   Emb Cosine   ROUGE-1 F1
---   ----------   ----------
R01   X.XXXX       X.XXXX
R02   X.XXXX       X.XXXX
...
```

**Main runner — `runGoldTest()`:** Identical flow to `test.js`'s `runConsistencyTest()` with these changes:
1. Read `currentRefFile` text before submitting jobs (fail early if the file can't be read).
2. Minimum succeeded threshold for comparison: `succeeded >= 1` (not 2, since we only need one run to compare against the reference; a single run vs a reference is meaningful).
3. Call `runGoldComparison(summaries, referenceText)` instead of `runComparison`.
4. Call `showGoldPanel` and `buildAndDownloadZip` with the gold-specific signatures.

**Init and event listeners:** Same as `test.js`. Add a second file-input change listener for `#ref-input` that sets `currentRefFile` and updates `#ref-name`.

### Step 9 — Update navigation links

**`frontend/test.html`** — The current `signout-row` contains only the sign-out button (no existing nav links). Add a link to `gold.html` before the sign-out button. The result after the edit must be exactly:
```html
<div class="signout-row">
  <a href="gold.html" class="btn-link">Gold Standard Test</a>
  <button id="signout-btn" class="btn-link">Sign Out</button>
</div>
```

**`frontend/index.html`** — In the `signout-row` div, add a link to `gold.html` alongside the existing "Consistency Test" link:
```html
<div class="signout-row">
  <a href="test.html" class="btn-link">Consistency Test</a>
  <a href="gold.html" class="btn-link">Gold Standard Test</a>
  <button id="signout-btn" class="btn-link">Sign Out</button>
</div>
```

---

## Risks and Blockers

**1. ThreadPoolExecutor mock complexity in tests**

The existing `test_comparator.py` mocks boto3 with a simple `side_effect` list that works because calls are sequential. The gold comparator uses `ThreadPoolExecutor`, so the mock must be keyed by call content, not call order. The test file must implement the named `_bedrock_mock` function described in Step 2 — using a dict lookup on `inputText` via `*args, **kwargs` with positional fallback. A lambda-based side_effect that relies on call ordering is fragile and must not be used.

**2. API Gateway 30-second hard timeout**

The HTTP API timeout cannot be raised. For N=200 texts with very long inputs (approaching 8K tokens each), parallel Titan calls might take longer than 30 seconds if Bedrock is under load. The plan mitigates this with `ThreadPoolExecutor` parallelism, which bounds wall-clock time to approximately `max(single_call_latency)` rather than `N * avg_call_latency`. For typical medical summary text (under 500 tokens), this is well within limits. No further mitigation is recommended at this stage; document the N=200 edge case as a known constraint.

**3. Reference file encoding**

`file.text()` in the browser uses UTF-8 by default. If a user uploads a file with a different encoding (e.g., Windows-1252), the resulting string may contain garbled characters. This is acceptable for a first version; add a note in the UI if needed.

**4. CORS — no change needed**

The existing CORS config on `aws_apigatewayv2_api.main` already allows `POST` from the CloudFront origin. `POST /gold-compare` is covered automatically.

**5. Cognito redirect — no change needed**

`gold.js` uses `REDIRECT_URI = window.location.origin + '/'` (identical to `test.js`), so no new callback URL registration is required in Cognito.

**6. Deploy script — no change needed**

`scripts/deploy_frontend.sh` syncs the entire `frontend/` directory to S3. `gold.html` and `gold.js` will be picked up automatically. The existing `/*` CloudFront invalidation pattern covers the new files.

**7. Lambda cold-start for gold comparator**

The gold comparator is a separate Lambda with its own cold-start. For infrequently-used evaluation pages, this is expected. No provisioned concurrency is needed.

**8. Terraform fmt requirement**

Per CLAUDE.md, `terraform -chdir=infra fmt -recursive` must be run before committing. The implementation agent must run this after editing all `.tf` files.

**9. JSZip script placement (functional bug risk)**

JSZip must be loaded in `<head>`, not at the bottom of `<body>`. Any reordering that places the JSZip CDN script after `gold.js` will cause `ReferenceError: JSZip is not defined` at runtime on any code path that calls `new JSZip()`. See Step 7 for the required placement.

---

## Testing Strategy

### Unit tests (no AWS credentials needed)
```bash
pip install pytest boto3
pytest tests/test_gold_comparator.py -v
```
All tests mock boto3; no real Bedrock calls are made. Verify all test classes pass: `TestValidation`, `TestResponseStructure`, `TestMetricCorrectness`. Specifically verify `test_tfidf_not_in_response` passes (confirming TF-IDF is absent from the response).

### Terraform validation
```bash
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
terraform -chdir=infra plan
```
The plan output should show exactly these new resources:
- `aws_cloudwatch_log_group.lambda["gold-comparator"]`
- `aws_iam_role.gold_comparator`
- `aws_iam_role_policy.gold_comparator_logs`
- `aws_iam_role_policy.gold_comparator_bedrock`
- `aws_iam_role_policy.gold_comparator_xray`
- `data.archive_file.gold_comparator`
- `aws_lambda_function.gold_comparator`
- `aws_apigatewayv2_integration.gold_comparator`
- `aws_apigatewayv2_route.gold_compare`
- `aws_lambda_permission.apigw_gold_comparator`

No existing resources should be modified or destroyed.

### Existing test suite regression
```bash
pytest tests/ -v
```
All pre-existing tests must continue to pass. The new Lambda is independent and does not touch any existing Lambda code.

### Frontend smoke test (post-deploy, manual)
1. Navigate to `gold.html` directly — verify the auth section is shown when not signed in, and a "Gold Standard Test" nav link appears from `test.html` and `index.html`.
2. Sign in via the Cognito-hosted UI — verify redirect returns to `gold.html` correctly via the `auth_return` localStorage key.
3. Choose a document file and a reference text file — verify the "Run Test" button enables only after both files are selected.
4. Run with `n=2` — verify the progress grid shows two tiles, both reach "done" state.
5. Verify the zip downloads with the correct folder structure: `gold_TIMESTAMP/summary_01.txt`, `summary_02.txt`, `reference.txt`, `manifest.txt`, `usage_report.txt`, `gold_comparison.json`, `gold_comparison_report.txt`.
6. Verify the "Accuracy Results" panel shows: two metric cards (Titan Embedding Cosine vs Reference and ROUGE-1 F1 vs Reference), each with Mean/Min/Max/Std values; and a per-run score table.
7. Verify that navigating to `test.html` shows a "Gold Standard Test" link and vice versa.
8. Open browser DevTools Network tab and confirm the `POST /gold-compare` response body contains exactly the keys `embedding_cosine` and `rouge1` — and no `tfidf_cosine` key.

---

**IMPORTANT — handoff to main agent:** This plan is complete and written to `/workspace/active_repo/claude-context-plan.md`. Before any implementation begins, the **Plan Reviewer agent MUST be run next** to audit this plan for correctness, completeness, and risks. No code should be written until the Reviewer has issued its verdict.
