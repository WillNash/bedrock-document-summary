# Claude Context Explorer — BERTScore in Gold Comparator

**Task:** Find a way to use BERTScore in the cloud for the gold standard evaluator (`POST /gold-compare`), replacing or supplementing ROUGE-1 F1.

---

## 1. Files Examined

- `/workspace/active_repo/lambda/gold_comparator/handler.py`
- `/workspace/active_repo/infra/lambda.tf`
- `/workspace/active_repo/infra/iam.tf`
- `/workspace/active_repo/infra/api_gateway.tf`
- `/workspace/active_repo/infra/locals.tf`
- `/workspace/active_repo/infra/variables.tf`
- `/workspace/active_repo/infra/step_functions.tf`
- `/workspace/active_repo/infra/bedrock.tf`
- `/workspace/active_repo/lambda/requirements.txt`
- `/workspace/active_repo/tools/requirements.txt`
- `/workspace/active_repo/tools/consistency_evaluator.py`
- `/workspace/active_repo/tools/consistency_evaluator_cloud.py`
- `/workspace/active_repo/scripts/build_lambdas.sh`
- `/workspace/active_repo/.github/workflows/ci.yml`
- `/workspace/active_repo/.github/workflows/deploy.yml`
- `/workspace/active_repo/frontend/gold.html`
- `/workspace/active_repo/frontend/gold.js`
- `/workspace/active_repo/tests/test_gold_comparator.py`

---

## 2. Current gold_comparator Handler — Full Structure

**File:** `/workspace/active_repo/lambda/gold_comparator/handler.py`

### Request contract
```
POST /gold-compare
Authorization: Bearer <id_token>
Content-Type: application/json

{"texts": ["summary1", "summary2", ...], "reference": "gold text"}
texts: 2–200 strings
```

### Response contract
```json
{
  "embedding_cosine": {"scores": [...], "mean": ..., "min": ..., "max": ..., "std": ..., "n": int},
  "rouge1":           {"scores": [...], "mean": ..., "min": ..., "max": ..., "std": ..., "n": int}
}
```

### How it works
1. Validates `texts` (list, 2–200 strings) and `reference` (non-empty string).
2. Uses `ThreadPoolExecutor` to embed all `texts` in parallel via Bedrock `amazon.titan-embed-text-v2:0`.
3. Embeds the `reference` synchronously after the thread pool completes.
4. Computes cosine similarity of each text embedding vs the reference embedding (dot product — vectors are normalized by Bedrock).
5. Computes ROUGE-1 F1 for each text vs the reference using stdlib only (no numpy, no scikit-learn).
6. Returns both metric blocks with the same stats shape: `{scores, mean, min, max, std, n}`.

### Key constraint
The handler is **stdlib-only** beyond boto3. All non-stdlib logic is pure Python (cosine via `sum(x*y ...)`, ROUGE via `re` + `Counter`). The Lambda layer (`layer.zip`) contains only `jinja2` and `jsonschema` — the gold_comparator Lambda does **not** use that layer at all (no `layers = [...]` in its `aws_lambda_function` block in lambda.tf).

---

## 3. infra/lambda.tf — Packaging Details

**File:** `/workspace/active_repo/infra/lambda.tf`

- `gold_comparator` is packaged as a plain **zip** via `archive_file.gold_comparator` (`source_dir = ../lambda/gold_comparator`).
- It uses `runtime = "python3.12"`, `architectures = ["arm64"]`.
- It does **not** use a Lambda layer — no `layers` attribute on this function.
- It has `timeout = 30` and `memory_size = 256`.
- No `package_type = "Image"` — no container image deployment pattern is used anywhere in the codebase. There is no ECR, no ECS, no Fargate, no SageMaker, no `RunTask` call anywhere in the infra. This is greenfield if the container image route is chosen.
- The only Lambda layer is `aws_lambda_layer_version.deps` (jinja2 + jsonschema), used only by `validator` and `renderer`. Layer size limit is 50 MB zipped / 250 MB unzipped — definitively too small for bert-score + torch.
- The `scripts/build_lambdas.sh` script uses `pip install --platform manylinux2014_aarch64 --only-binary=:all:` which would be the correct approach for building arm64-compatible wheels for a layer.

---

## 4. infra/iam.tf — gold_comparator IAM Role

**File:** `/workspace/active_repo/infra/iam.tf` (lines 372–418)

The `gold_comparator` role has exactly three policies:
1. **`gold_comparator_logs`** — CloudWatch Logs scoped to `/aws/lambda/{prefix}-gold-comparator:*`.
2. **`gold_comparator_bedrock`** — `bedrock:InvokeModel` on `Resource: ["*"]` (unrestricted model access). This already covers any Bedrock model.
3. **`gold_comparator_xray`** — X-Ray tracing.

**There are no `ecs:RunTask`, `sagemaker:InvokeEndpoint`, or `lambda:InvokeFunction` permissions on this role.** Any approach that calls a second Lambda or an ECS task would require new IAM policies on this role.

---

## 5. API Gateway Route for gold-compare

**File:** `/workspace/active_repo/infra/api_gateway.tf`

- `POST /gold-compare` is wired as `AWS_PROXY` (`payload_format_version = "2.0"`) directly to `gold_comparator` Lambda.
- It is JWT-authorized via Cognito (same authorizer as all other routes).
- This is a **synchronous** Lambda invocation — API Gateway HTTP API has a hard 29-second response timeout. No async/SQS/polling pattern exists anywhere in the codebase for the gold compare path.

---

## 6. No Existing ECS/Fargate/Container Infrastructure

A full-text search across all `.tf`, `.sh`, `.yml`, and `.py` files found **zero references** to ECS, Fargate, ECR, SageMaker, container images, or `package_type = "Image"`. The entire architecture is pure Lambda + Step Functions + API Gateway + S3 + DynamoDB. Any heavier-compute approach is greenfield.

---

## 7. Requirements Files

**`/workspace/active_repo/lambda/requirements.txt`** (the shared Lambda layer):
```
jinja2>=3.1.0
jsonschema>=4.21.0
```

**`/workspace/active_repo/tools/requirements.txt`** (local dev tools — NOT deployed):
```
python-hcl2==8.1.4
sentence-transformers>=6.1.0
bert-score==0.3.13
scikit-learn>=1.4.0
rouge-score>=0.1.2
numpy>=1.26.0
torch>=2.2.0
jinja2>=3.1.0
jsonschema>=4.21.0
```

`bert-score==0.3.13` with `torch` is already used in local tools and in CI tests. The CI workflow installs CPU-only torch via `--index-url https://download.pytorch.org/whl/cpu` to avoid the 2–3 GB CUDA wheel.

---

## 8. Existing BERTScore Usage Pattern (tools/)

**File:** `/workspace/active_repo/tools/consistency_evaluator.py`

The local evaluator uses `bert_score.BERTScorer` with `model_type="microsoft/deberta-large-mnli"` (~900 MB download). CI tests use `distilbert-base-uncased` as a smaller substitute. The call pattern for a one-to-one score (each hypothesis vs one reference):

```python
from bert_score import BERTScorer
scorer = BERTScorer(model_type=BERTSCORE_MODEL, lang="en")
_, _, F1 = scorer.score([hypothesis], [reference])
f1_value = F1.item()  # torch.Tensor -> Python scalar
```

For the gold standard use case (N texts vs 1 reference), this would be called as:
```python
_, _, F1s = scorer.score(summaries, [reference] * len(summaries))
# F1s is a torch.Tensor of shape (N,)
bertscore_scores = F1s.tolist()
```

---

## 9. CI/CD Build Environment

**File:** `/workspace/active_repo/.github/workflows/ci.yml`

- Tests run on `ubuntu-latest` with Python 3.11.
- CPU-only torch installed explicitly.
- HuggingFace model cache stored via `actions/cache@v4` keyed to `hf-models-all-minilm-v2`.
- BERTScore tests in `test_consistency.py` are marked `slow` and excluded from the default run (`pytest -m "not slow"`).

**File:** `/workspace/active_repo/.github/workflows/deploy.yml`

- Manually triggered (`workflow_dispatch`).
- Calls `scripts/build_lambdas.sh` then `terraform apply`.
- No step that builds or pushes any container image.

---

## 10. frontend/gold.js — Full API Call Flow

**File:** `/workspace/active_repo/frontend/gold.js`

The flow is:
1. User picks a document file and a reference text file in the browser.
2. The document is uploaded N times in parallel (staggered 200 ms each) via `POST /presign` → S3 presigned POST → pipeline runs.
3. All N jobs are polled concurrently (`GET /jobs/{jobId}` every 5 s, 10-minute max).
4. Completed jobs: `GET /summaries/{jobId}` fetches the summary text.
5. Single call to `POST /gold-compare` with `{ texts: succeededSummaries, reference: referenceText }`.
6. Results displayed in `showGoldPanel()` and downloaded as a zip via `buildAndDownloadZip()`.

### Frontend response consumption — hardcoded metric keys

`showGoldPanel()` at lines 272–302 iterates a **hardcoded** metrics array:
```js
const metrics = [
  { key: 'embedding_cosine', title: 'Titan Embedding Cosine vs Reference' },
  { key: 'rouge1',           title: 'ROUGE-1 F1 vs Reference' },
];
```

The per-run score table at lines 304–345 hardcodes three columns: `'Run'`, `'Emb Cosine'`, `'ROUGE-1 F1'`, reading from `comparison.embedding_cosine.scores` and `comparison.rouge1.scores`.

`buildGoldReport()` at lines 350–387 also hardcodes `rouge1` key references and labels.

**Replacing or renaming `rouge1` → `bertscore_f1` requires updating `showGoldPanel()`, `buildGoldReport()`, and the column header array in `gold.js`.** The zip contains `gold_comparison.json` (the raw API response) and `gold_comparison_report.txt` (the formatted text), so report labels also need updating.

---

## 11. tests/test_gold_comparator.py — Test Contract

**File:** `/workspace/active_repo/tests/test_gold_comparator.py`

Line 134 asserts the exact response key set:
```python
assert set(body.keys()) == {"embedding_cosine", "rouge1"}
```

Line 139 asserts:
```python
assert "tfidf_cosine" not in body
```

**Any change to the response shape requires updating this test file.**

---

## 12. Feasible Approaches for Cloud BERTScore

### Why the Lambda layer approach is ruled out
- `bert-score==0.3.13` depends on `torch`, `transformers`, and `numpy`.
- CPU-only torch for aarch64 Linux is ~200 MB stripped. Layer limit is 50 MB zipped / 250 MB unzipped.
- The layer approach is definitively ruled out.

### Option A — Lambda Container Image (recommended, lowest infra lift)

Replace the zip-based `gold_comparator` Lambda with a container image. Lambda supports images up to 10 GB. The image would bundle Python 3.12 + `bert-score==0.3.13` + CPU-only torch + a pre-cached model (baked in at image build time to avoid HuggingFace downloads on cold start).

**Model choice tradeoff:**
- `microsoft/deberta-large-mnli` — what local tools use, ~900 MB, highest quality.
- `distilbert-base-uncased` — ~270 MB, used in CI, lower quality but viable.
- `microsoft/deberta-xlarge-mnli` — ~1.5 GB, best quality, slower inference.

**New infra resources required:**
- `aws_ecr_repository.gold_comparator` — ECR repo for the image.
- `aws_lambda_function.gold_comparator`: change from `filename`/`source_code_hash`/`handler`/`runtime` to `package_type = "Image"` + `image_uri = "${aws_ecr_repository.gold_comparator.repository_url}:latest"`.
- Remove `data "archive_file" "gold_comparator"` from lambda.tf (no longer needed).
- New `lambda/gold_comparator/Dockerfile`.
- Build+push step in deploy workflow: `docker build` + `docker push` before `terraform apply`.
- No change to the `gold_comparator_bedrock` IAM policy — it already covers Titan embeddings.
- Lambda execution role does not need ECR permissions (the Lambda service pulls the image, not the function itself).

**Timeout and memory concerns:**
- Current `timeout = 30` and `memory_size = 256` are inadequate for model inference on CPU.
- BERTScore inference on CPU for N=200 medical summaries (~300 words each) against a reference could take 120–600+ seconds.
- The API Gateway hard limit is 29 seconds. A batch of 200 will exceed this.
- Recommended mitigations: (a) cap the `texts` array at a lower limit (e.g., 50) for BERTScore, keeping 200 for the Titan embedding metric only; or (b) rearchitect as async (adds significant complexity); or (c) increase `memory_size` to 3008–10240 MB to speed up CPU inference.
- A realistic `memory_size` of 3008 MB and `timeout` of 120 s with a batch cap of 20–30 texts is workable within the API GW limit for typical medical summary lengths.

### Option B — Bedrock-Native Approximation (no new infra, not true BERTScore)

The `gold_comparator` role already has `bedrock:InvokeModel` on `*`. Titan embeddings already provide a strong semantic similarity signal. There is no AWS-managed BERTScore endpoint. This option cannot produce true BERTScore.

### Option C — Async Lambda + Polling

Client submits, receives a job token, polls until complete. Requires new SQS or DynamoDB job tracking and frontend changes to add a polling loop for the comparison step. The current frontend treats `POST /gold-compare` as fully synchronous. High infra and frontend complexity.

### Option D — ECS Fargate On-Demand Task

Lambda triggers a one-shot Fargate task; results stored in S3/DynamoDB; frontend polls. No existing ECS infrastructure. Highest infrastructure lift.

---

## 13. Complete List of Files That Must Change

For the Lambda container image approach (Option A):

| File | Change |
|---|---|
| `lambda/gold_comparator/handler.py` | Replace `_rouge1_f1` with BERTScore; update response key from `rouge1` to `bertscore_f1`; import `bert_score` |
| `lambda/gold_comparator/Dockerfile` | New file — build image with Python 3.12, bert-score, CPU torch, pre-cache model |
| `infra/lambda.tf` | Remove `data "archive_file" "gold_comparator"`; change `aws_lambda_function.gold_comparator` to `package_type = "Image"`, add `image_uri`; increase `timeout` and `memory_size`; add `aws_ecr_repository.gold_comparator` |
| `infra/iam.tf` | No changes required (bedrock policy already covers `*`) |
| `frontend/gold.js` | Update `showGoldPanel()` metrics array, `buildGoldReport()` labels, table column header — change `rouge1` → `bertscore_f1` and update display title |
| `tests/test_gold_comparator.py` | Update `test_top_level_keys` assertion from `{"embedding_cosine", "rouge1"}` to `{"embedding_cosine", "bertscore_f1"}`; update any ROUGE-specific tests |
| `.github/workflows/deploy.yml` | Add `docker build` + `docker push` steps before `terraform apply` |
| `scripts/build_lambdas.sh` (or new script) | Optionally add image build logic; or handle in deploy.yml directly |

**Files that do NOT need to change:**
- `infra/api_gateway.tf` — route, integration, and Lambda permission are already correct.
- `infra/iam.tf` — existing `gold_comparator_bedrock` policy already covers Titan embeddings.
- `frontend/gold.html` — no structural change needed; column labels are in gold.js, not HTML.
- `lambda/requirements.txt` — this is for the shared Lambda layer, not the gold_comparator.

---

## 14. Key Side-Effects and Risks

1. **API Gateway 29-second hard limit** — BERTScore on CPU is slow. With a typical medical summary of 300–500 words and N=20 texts, inference takes ~30–90 seconds on CPU even with 3 GB Lambda memory. The 29-second limit means the API will time out for all but the smallest batches unless memory is maximized and the batch is capped at ~5–10 texts for BERTScore, or the architecture is made async.

2. **Cold start latency** — Lambda container cold starts are 5–15 seconds for large images. The BERTScorer model also needs to be loaded from disk on cold start (even if baked into the image). With `microsoft/deberta-large-mnli`, expect 10–20 second model load time in addition to cold start. Provisioned concurrency would eliminate cold starts at extra cost.

3. **Baking the model into the image** — The Dockerfile must run `python -c "from bert_score import BERTScorer; BERTScorer(model_type='...')"` at image build time to pre-cache the model. Without this, the Lambda would attempt to download the model from HuggingFace on every cold start — which will fail if the Lambda has no internet access, or succeed only if a NAT gateway is configured.

4. **VPC/internet access** — The current `gold_comparator` Lambda has no VPC config and accesses the internet freely (for Bedrock API calls, which go through AWS service endpoints). A container image Lambda also needs to pull from ECR. If VPC is added later, NAT or VPC endpoints are required. Currently no VPC config exists, so this is not an issue.

5. **ECR image lifecycle** — The deploy workflow will need to push a new image tag on every deploy. Use a consistent tag (e.g., `latest` or a git SHA) and configure `image_uri` accordingly. ECR lifecycle policies should be added to avoid accumulating stale images.

6. **Test isolation** — `tests/test_gold_comparator.py` mocks `boto3.client` and tests the handler module directly. After the change, `bert_score` will be imported at the top of the handler. The test file will need `bert_score` and `torch` available in the test environment, or the BERTScorer must be mocked. The existing CI installs both, so this should work, but `torch` is a heavy dependency for the test suite.

7. **The `_score_stats` helper is reusable** — The existing `_score_stats(scores)` function in `handler.py` takes a plain Python list and returns the stats dict. It can be reused for the BERTScore output without modification — just pass `F1s.tolist()` as the scores list.
