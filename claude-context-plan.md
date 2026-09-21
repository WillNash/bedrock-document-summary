# Architecture Plan

## Context Summary

Replace ROUGE-1 F1 with BERTScore F1 in the `POST /gold-compare` Lambda (`gold_comparator`). Because `bert-score` + CPU-only PyTorch exceeds the 250 MB unzipped Lambda layer limit, the Lambda must be converted from a zip-packaged function to a container image (up to 10 GB). The model weights (~440 MB for `allenai/scibert_scivocab_uncased`) are baked into the image at build time so no HuggingFace download occurs at runtime. All downstream consumers (tests, frontend) must be updated to use the new `bertscore_f1` response key.

---

## Impacted Files

### New files to create
- `lambda/gold_comparator/Dockerfile` — container image definition (Python 3.12 Lambda base, CPU torch, bert-score, pre-cached model weights)
- `scripts/build_gold_comparator.sh` — script to build and push the ECR image, update Lambda function code

### Existing files to modify
- `lambda/gold_comparator/handler.py` — replace `_rouge1_f1` with BERTScorer at module level; change response key `rouge1` → `bertscore_f1`; add N cap for BERTScore
- `infra/lambda.tf` — remove `data "archive_file" "gold_comparator"`; convert `aws_lambda_function.gold_comparator` to `package_type = "Image"`; add `aws_ecr_repository.gold_comparator`; raise `memory_size` to 5120 and `timeout` to 120
- `frontend/gold.js` — update `showGoldPanel()` metrics array, table column headers, `buildGoldReport()` labels, and `_scoreCellClass` threshold note; change `rouge1` → `bertscore_f1` everywhere; add BERTScore scale note to UI
- `tests/test_gold_comparator.py` — mock `bert_score.BERTScorer` before module load; update key assertions from `rouge1` → `bertscore_f1`; update ROUGE-specific test cases to test BERTScore behaviour
- `.github/workflows/deploy.yml` — add Docker build and ECR push step before `terraform apply`

---

## Step-by-Step Execution Plan

### Step 1 — Write the Dockerfile

Create `/workspace/active_repo/lambda/gold_comparator/Dockerfile`.

- Base image: `public.ecr.aws/lambda/python:3.12` (Amazon Linux 2023, arm64-compatible via buildx `--platform linux/arm64`)
- Install CPU-only PyTorch from `https://download.pytorch.org/whl/cpu` first (avoids the multi-GB CUDA wheel that would come from PyPI)
- Install `transformers` and `bert-score` (pinned to `==0.3.13` to match `tools/requirements.txt`)
- Set env vars: `TRANSFORMERS_CACHE=/var/task/hf_cache`, `HF_HOME=/var/task/hf_cache`, `TOKENIZERS_PARALLELISM=false`
- Pre-bake model weights at image build time by running a Python one-liner that instantiates `BERTScorer(model_type="allenai/scibert_scivocab_uncased", num_layers=8)` — this triggers HuggingFace `from_pretrained()` downloads into `/var/task/hf_cache` while building, so the Lambda never needs outbound internet access for model fetching
- `COPY handler.py ${LAMBDA_TASK_ROOT}`
- `CMD ["handler.lambda_handler"]`

Key constraints:
- Build must use `docker buildx build --platform linux/arm64 --provenance=false` (provenance=false is mandatory for Lambda compatibility, as confirmed by official AWS docs)
- The `/var/task/hf_cache` directory is part of the image layer, not `/tmp`, so it is read-only at runtime — which is correct for pre-baked weights

### Step 2 — Rewrite the Lambda handler

Modify `/workspace/active_repo/lambda/gold_comparator/handler.py`:

1. Remove the `re`, `Counter`, and `_rouge1_f1` function entirely.
2. Add imports: `import torch` and `from bert_score import BERTScorer`
3. Add a module-level constant `BERTSCORE_MAX_TEXTS = 20` — BERTScore on CPU at N=200 would exceed the 29-second API Gateway limit. The existing Bedrock embedding path still accepts up to 200 texts; BERTScore is capped separately. N=20 is chosen conservatively based on AWS blog data (up to 25 seconds for distilbert at 5 GB memory); scibert is larger so the cap is kept tight.
4. Instantiate `_scorer` at module level (outside `lambda_handler`):
   ```python
   _scorer = BERTScorer(
       model_type="allenai/scibert_scivocab_uncased",
       num_layers=8,
       device="cpu",
       rescale_with_baseline=False,
   )
   ```
   Module-level init is critical: warm Lambda invocations reuse the already-loaded model, eliminating the ~5-second model-load overhead on every call.
5. In `lambda_handler`, after validation, add a secondary check: if `len(texts) > BERTSCORE_MAX_TEXTS`, return a 400 error with a clear message explaining the BERTScore cap (e.g., `f"BERTScore supports at most {BERTSCORE_MAX_TEXTS} texts per request due to CPU inference limits"`).
6. Replace the ROUGE scoring block with:
   ```python
   refs_repeated = [reference] * len(texts)
   with torch.no_grad():
       _P, _R, F1 = _scorer.score(cands=texts, refs=refs_repeated,
                                   verbose=False, batch_size=8)
   bertscore_scores = [float(f) for f in F1.tolist()]
   ```
7. Update the return value: replace `"rouge1": _score_stats(rouge_scores)` with `"bertscore_f1": _score_stats(bertscore_scores)`. The `_score_stats` helper is unchanged.
8. Update the module docstring to reflect the new metric and the BERTScore scale note ([0.84, 0.97] typical range, not [0, 1]).

### Step 3 — Add ECR repository and update Lambda Terraform resource

Modify `/workspace/active_repo/infra/lambda.tf`:

1. Remove the `data "archive_file" "gold_comparator"` block (lines 114–118). Terraform no longer manages the artifact; the deploy script pushes it.

2. Add a new `aws_ecr_repository` resource and lifecycle policy:
   ```hcl
   resource "aws_ecr_repository" "gold_comparator" {
     name                 = "${local.name_prefix}-gold-comparator"
     image_tag_mutability = "MUTABLE"
     force_delete         = true

     image_scanning_configuration {
       scan_on_push = true
     }

     tags = local.common_tags
   }

   resource "aws_ecr_lifecycle_policy" "gold_comparator" {
     repository = aws_ecr_repository.gold_comparator.name
     policy = jsonencode({
       rules = [{
         rulePriority = 1
         description  = "Keep only the 3 most recent images"
         selection = {
           tagStatus   = "any"
           countType   = "imageCountMoreThan"
           countNumber = 3
         }
         action = { type = "expire" }
       }]
     })
   }
   ```

3. Replace `aws_lambda_function.gold_comparator` entirely. The new resource:
   - Removes: `filename`, `source_code_hash`, `handler`, `runtime` attributes
   - Removes: `publish = true` (version publishing is handled by the deploy script, not Terraform, to avoid Provisioned Concurrency pinning to stale code)
   - Adds: `package_type = "Image"` and `image_uri = "${aws_ecr_repository.gold_comparator.repository_url}:latest"`
   - Adds: `lifecycle { ignore_changes = [image_uri] }` — Terraform sets the initial image URI after the real image is pushed; subsequent updates are handled by the deploy script via `update-function-code`
   - Increases: `memory_size = 5120` (matching AWS ML blog recommendation) and `timeout = 120`
   - Keeps: `architectures = ["arm64"]`, role, tracing_config, logging_config, tags, depends_on

4. Add two outputs so the deploy script can resolve names without hardcoding:
   ```hcl
   output "gold_comparator_ecr_repository_name" {
     value = aws_ecr_repository.gold_comparator.name
   }

   output "gold_comparator_function_name" {
     value = aws_lambda_function.gold_comparator.function_name
   }
   ```

### Step 4 — Write the build and deploy script

Create `/workspace/active_repo/scripts/build_gold_comparator.sh` and mark it executable (`chmod +x`):

The script must:
1. Near the top, resolve and validate the AWS region:
   ```bash
   AWS_REGION=${AWS_DEFAULT_REGION:-$(aws configure get region)}
   if [ -z "$AWS_REGION" ]; then
     echo "ERROR: AWS region not set. Set AWS_DEFAULT_REGION or configure aws default region."
     exit 1
   fi
   ```
2. Resolve the AWS account ID via `aws sts get-caller-identity`
3. Resolve the ECR repo name and Lambda function name from `terraform output`
4. Authenticate with ECR via `aws ecr get-login-password | docker login`
5. Build the image with `docker buildx build --platform linux/arm64 --provenance=false`
6. Push the image with `docker push`
7. Call `aws lambda update-function-code --image-uri <ecr-uri>:latest` to pin the Lambda to the new digest
8. Immediately after `update-function-code`, publish a new version and configure Provisioned Concurrency on it:
   ```bash
   VERSION=$(aws lambda publish-version --function-name "$FUNCTION_NAME" --query 'Version' --output text)
   aws lambda put-provisioned-concurrency-config --function-name "$FUNCTION_NAME" --qualifier "$VERSION" --provisioned-concurrent-executions 1
   ```

Include a guard: if `terraform output gold_comparator_ecr_repository_name` returns empty (Terraform not yet applied), print a clear error and exit non-zero.

Include a comment block explaining the bootstrapping order for first deploy and subsequent deploys (see Risk 2 mitigation below).

### Step 5 — Update the deploy workflow

Modify `/workspace/active_repo/.github/workflows/deploy.yml`:

Add a step after `Terraform Apply` and before `Deploy frontend`:
```yaml
- name: Build and push gold_comparator image
  run: ./scripts/build_gold_comparator.sh
```

The step must come after `Terraform Apply` because the ECR repository must exist before the image can be pushed. The Provisioned Concurrency configuration is applied inside `build_gold_comparator.sh` after each image push.

No Docker-in-Docker or additional setup is needed — GitHub Actions `ubuntu-latest` runners have Docker and buildx available by default.

### Step 6 — Update frontend/gold.js

Modify `/workspace/active_repo/frontend/gold.js`:

1. In `showGoldPanel()`, update the `metrics` array (lines 272–275):
   ```js
   const metrics = [
     { key: 'embedding_cosine', title: 'Titan Embedding Cosine vs Reference' },
     { key: 'bertscore_f1',     title: 'BERTScore F1 vs Reference (typical range ~0.84–0.97)' },
   ];
   ```

2. In `showGoldPanel()`, update the variable reading comparison scores (line 308):
   - Change `const rougeScores = comparison.rouge1.scores;` to `const bertScores = comparison.bertscore_f1.scores;`

3. Update the table column header array (line 316):
   - Change `['Run', 'Emb Cosine', 'ROUGE-1 F1']` to `['Run', 'Emb Cosine', 'BERTScore F1']`

4. In the per-run table loop (lines 336–341):
   - Change `rougeTd` variable to `bertTd`
   - Change `rougeScores[i]` to `bertScores[i]`
   - The `_scoreCellClass` thresholds (0.8 for "high", 0.6 for "mid") will consistently colour BERTScore values as "high" since scibert F1 for similar texts falls in [0.84, 0.97]. This is acceptable behaviour — all scores look green which is informative. No threshold change is required since the scale note in the title communicates the context.

5. In `buildGoldReport()` (lines 350–387):
   - Change `const r = comparison.rouge1;` to `const r = comparison.bertscore_f1;`
   - Change the section header string from `'── ROUGE-1 F1 vs Reference ──'` to `'── BERTScore F1 vs Reference (typical range ~0.84–0.97) ──'`
   - Change the per-run column header from `'ROUGE-1 F1'` to `'BERTScore F1'`
   - Change `const rougeScores = comparison.rouge1.scores;` to `const bertScores = comparison.bertscore_f1.scores;`
   - Update row builder: change `rougeScores[i].toFixed(4)` to `bertScores[i].toFixed(4)`

### Step 7 — Update tests/test_gold_comparator.py

Modify `/workspace/active_repo/tests/test_gold_comparator.py`:

1. Before the existing `importlib` / `exec_module` block, inject a `bert_score` mock into `sys.modules` so the handler's top-level import and module-level `_scorer` instantiation resolve without loading any model:

   ```python
   import sys
   import types
   from unittest import mock

   # --- Mock bert_score before handler module is loaded ---
   _mock_scorer_instance = mock.MagicMock()

   def _fake_score(cands, refs, verbose=False, batch_size=8):
       # Return (P, R, F1) as mock objects with .tolist()
       n = len(cands)
       f1_vals = [0.91] * n
       f1_mock = mock.MagicMock()
       f1_mock.tolist.return_value = f1_vals
       p_mock = mock.MagicMock()
       r_mock = mock.MagicMock()
       return p_mock, r_mock, f1_mock

   _mock_scorer_instance.score.side_effect = _fake_score
   _mock_bertscore_cls = mock.MagicMock(return_value=_mock_scorer_instance)
   _mock_bert_score_module = types.ModuleType('bert_score')
   _mock_bert_score_module.BERTScorer = _mock_bertscore_cls
   sys.modules['bert_score'] = _mock_bert_score_module
   ```

2. Update `test_top_level_keys` (line 134):
   ```python
   assert set(body.keys()) == {"embedding_cosine", "bertscore_f1"}
   ```

3. Rename `test_tfidf_not_in_response` to `test_legacy_metrics_not_in_response` and assert both absence guards:
   ```python
   assert "tfidf_cosine" not in body
   assert "rouge1" not in body
   ```

4. Update `test_stats_keys_in_each_metric`: replace `body["rouge1"]` with `body["bertscore_f1"]`.

5. Update `test_scores_length_matches_texts_count`: replace `body["rouge1"]["scores"]` with `body["bertscore_f1"]["scores"]` and `body["rouge1"]["n"]` with `body["bertscore_f1"]["n"]`.

6. Update `test_n_matches_texts_count`: same substitutions.

7. Remove `test_rouge1_identical_texts_score_one` and `test_rouge1_disjoint_texts_score_zero` entirely — these test the deleted ROUGE algorithm. Replace with one new test:
   ```python
   def test_bertscore_f1_values_are_floats(self):
       vec_map = self._simple_vec_map(_TEXTS[:2], _REF)
       _, _, body = _call(_TEXTS[:2], _REF, vec_map)
       for score in body["bertscore_f1"]["scores"]:
           assert isinstance(score, float)
   ```

8. Update `test_all_values_are_plain_python_types`: replace the `("embedding_cosine", "rouge1")` tuple with `("embedding_cosine", "bertscore_f1")`.

9. Update `test_mean_is_average_of_scores`: replace `"rouge1"` with `"bertscore_f1"`.

10. Add a validation test for the BERTScore cap. The 400 fires before any AWS call, so no `boto3.client` mock is needed:
    ```python
    def test_above_bertscore_max_returns_400(self):
        texts = [f"text {i}" for i in range(21)]
        resp = lambda_handler(_event(texts, _REF), None)
        assert resp["statusCode"] == 400
    ```

### Step 8 — Verify Terraform formatting

Run `terraform -chdir=infra fmt -recursive` to ensure all `.tf` changes pass CI format checks before committing.

---

## Risks and Blockers

### Risk 1 — API Gateway 29-second hard timeout (HIGH)
BERTScore on CPU for scibert at `memory_size = 5120` is estimated at ~5–25 seconds for small N (AWS blog data for distilbert at 5 GB memory). scibert is larger (~440 MB vs 268 MB for distilbert), so inference will be slower. For N=20 medical summaries at ~300–500 words each, inference time is uncertain.

**Mitigation:** Set `BERTSCORE_MAX_TEXTS = 20` conservatively. After deployment, test empirically with representative medical summaries. If 20 times out, reduce to 10. If 10 is consistently fast, consider raising to 25. The cap value is a module-level constant in `handler.py` — easy to tune without rebuilding the image (it requires a new image push, but is a one-line change). Document the cap and the reason in the handler docstring and the 400 error message.

### Risk 2 — First-deploy bootstrapping order (MEDIUM)
Terraform's `aws_lambda_function.gold_comparator` with `package_type = "Image"` requires a valid private ECR image URI at apply time. Using a public ECR URI as a placeholder causes `CreateFunction` to fail with `InvalidParameterValueException`. On first deploy, the ECR repo does not yet exist and no image has been pushed.

**Mitigation:** Use the following corrected first-deploy bootstrapping sequence:
1. `terraform apply -target=aws_ecr_repository.gold_comparator -target=aws_ecr_lifecycle_policy.gold_comparator` — creates only the private ECR repo.
2. `./scripts/build_gold_comparator.sh` — builds and pushes the real image to the private repo.
3. `terraform apply` — creates the Lambda function (referencing the now-existing private image URI) and all remaining resources.

For CI/CD (subsequent deploys): `terraform apply` runs first (updates all infrastructure), then `./scripts/build_gold_comparator.sh` builds and pushes the updated image and updates the Lambda. The `lifecycle { ignore_changes = [image_uri] }` block ensures Terraform does not overwrite the image URI managed by the deploy script.

Document this bootstrapping sequence clearly in both `build_gold_comparator.sh` and the deploy.yml step comment.

### Risk 3 — Model weight download during Docker build in restricted environments (MEDIUM)
The Dockerfile `RUN` step that pre-bakes model weights downloads ~440 MB from HuggingFace during `docker build`. This requires outbound HTTPS internet access from the build machine.

**Mitigation:** GitHub Actions `ubuntu-latest` has unrestricted internet access. Local developer builds need internet access for the first build (Docker layer cache handles subsequent builds). Document this requirement in `build_gold_comparator.sh` comments. No workaround is needed for the current CI/CD environment.

### Risk 4 — BERTScore F1 scale confuses users (LOW)
Scores in [0.84, 0.97] look "low" to users expecting [0, 1]. The existing `_scoreCellClass` function will colour all BERTScore values as "high" (>= 0.8 threshold), which is visually fine but the absolute numbers may alarm users unfamiliar with BERTScore.

**Mitigation:** Add the scale context to the metric card title in `gold.js` (Step 6, item 1): `'BERTScore F1 vs Reference (typical range ~0.84–0.97)'`. Add the same note to `buildGoldReport()` section header. This is purely a display/documentation concern.

### Risk 5 — Provisioned Concurrency cost (LOW)
1 provisioned concurrency unit for a 5120 MB Lambda incurs approximately $110–130/month in us-east-1, charged continuously whether or not the function is invoked.

**Mitigation:** Accept this cost as the price of eliminating 25-second cold starts for a medical evaluation tool. If cost becomes a concern, consider adding a Terraform variable (e.g., `var.gold_comparator_provisioned_concurrency` defaulting to `1`, settable to `0`) to make provisioned concurrency optional. At `0`, cold starts would occur but the Lambda would still function correctly.

### Risk 6 — torch.no_grad() and F1.tolist() contract (LOW)
The handler calls `F1.tolist()` on the tensor returned by `_scorer.score()`. If `bert-score` ever returns a non-tensor (e.g., a plain list on some code path), this will fail silently or raise `AttributeError`.

**Mitigation:** Wrap the conversion defensively: `bertscore_scores = [float(f) for f in (F1.tolist() if hasattr(F1, 'tolist') else F1)]`. This is a minor defensive pattern — the `bert-score` library's documented contract is to return torch.Tensor, so this is purely belt-and-suspenders.

---

## Testing Strategy

### Unit tests (no AWS, no Docker, no model)
1. Run `pytest tests/test_gold_comparator.py` — all tests must pass with the mocked BERTScorer. This validates handler logic, response shape, key names, validation rules, and the new BERTScore cap validation.

### Docker build smoke test (Docker required, internet required on first run)
2. Build the Docker image locally:
   ```bash
   docker buildx build --platform linux/arm64 --provenance=false \
     -t gold-comparator:test /workspace/active_repo/lambda/gold_comparator/
   ```
   The build must complete without errors. Success confirms: scibert model weights downloaded and baked in, handler.py importable with bert_score, BERTScorer instantiates at module level without error.

### Container invocation test (Docker required)
3. Run the built container with the Lambda Runtime Interface Emulator (RIE):
   ```bash
   docker run --rm -p 9000:8080 gold-comparator:test
   # In a second terminal:
   curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" \
     -H 'Content-Type: application/json' \
     -d '{"body":"{\"texts\":[\"patient blood glucose elevated hemoglobin\",\"blood glucose high in this patient\"],\"reference\":\"patient has elevated blood glucose and hemoglobin\"}"}'
   ```
   Expected response: JSON with `embedding_cosine` and `bertscore_f1` keys, F1 scores in [0.82, 0.98] range, response time under 29 seconds (model already loaded at module level, no cold start).

   Note: Bedrock calls will fail in local testing (no AWS credentials in the container). Mock the embedding step by either: (a) running with AWS credentials via `-e AWS_ACCESS_KEY_ID=...` env vars, or (b) testing BERTScore independently in the container via `docker exec` and a Python REPL.

### Terraform validation
4. `terraform -chdir=infra fmt -check -recursive` — must pass (run `fmt -recursive` first to fix any issues)
5. `terraform -chdir=infra validate` — must pass (validates ECR repo and Lambda image resource)

### End-to-end (deployed infrastructure)
6. Execute the first-deploy bootstrapping sequence from Risk 2 mitigation. Confirm all three steps complete without error.
7. Open `gold.html` in the browser. Upload a test document and a reference file. Run 2–3 iterations.
8. Verify the UI shows `BERTScore F1 vs Reference (typical range ~0.84–0.97)` metric card (not "ROUGE-1 F1").
9. Verify the per-run score table shows a "BERTScore F1" column.
10. Download the zip. Open `gold_comparison_report.txt` and confirm it contains `BERTScore F1 vs Reference` headers. Open `gold_comparison.json` and confirm it has `bertscore_f1` key and no `rouge1` key.
11. Confirm F1 values are in a reasonable range (roughly 0.84–0.97 for similar medical texts).
12. Test the cap: set run count to 21 and click Run. The `POST /gold-compare` call should return HTTP 400 with a message mentioning the BERTScore limit. The UI should handle this gracefully (the existing error path in `runGoldTest` catches non-200 from `runGoldComparison`).
13. On a subsequent deploy, trigger the `Deploy` workflow. Confirm all steps complete, specifically the `Build and push gold_comparator image` step and that Provisioned Concurrency is applied to the new version.

---

**IMPORTANT — handoff to main agent:** This plan is written and complete. The Plan Reviewer agent MUST be run next before any implementation begins. No code should be written until the Reviewer has issued its verdict.
