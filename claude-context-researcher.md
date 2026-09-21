# Research Findings — BERTScore in the Cloud

## Source URLs

- [Create a Lambda function using a container image](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html) — **Official**
- [Deploy Python Lambda functions with container images](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html) — **Official**
- [Deploy models with Amazon SageMaker Serverless Inference](https://docs.aws.amazon.com/sagemaker/latest/dg/serverless-endpoints.html) — **Official**
- [AWS Fargate or AWS Lambda? Decision Guide](https://docs.aws.amazon.com/decision-guides/latest/decision-guides/fargate-or-lambda.html) — **Official**
- [FacebookAI/roberta-large at Hugging Face](https://huggingface.co/FacebookAI/roberta-large/tree/main) — **Official**
- [distilbert/distilbert-base-uncased at Hugging Face](https://huggingface.co/distilbert/distilbert-base-uncased) — **Official**
- [allenai/scibert_scivocab_uncased at Hugging Face](https://huggingface.co/allenai/scibert_scivocab_uncased) — **Official**
- [GitHub - Tiiiger/bert_score (README)](https://github.com/Tiiiger/bert_score) — **Official**
- [GitHub - Tiiiger/bert_score scorer.py](https://github.com/Tiiiger/bert_score/blob/master/bert_score/scorer.py) — **Official**
- [HuggingFace Transformers installation (cache env vars)](https://huggingface.co/docs/transformers/installation) — **Official**
- [Amazon ECR Public Gallery - Lambda Python base images](https://gallery.ecr.aws/lambda/python) — **Official**
- [Using container images to run PyTorch models in AWS Lambda - AWS Blog](https://aws.amazon.com/blogs/machine-learning/using-container-images-to-run-pytorch-models-in-aws-lambda/) — Semi-official
- [aws-samples/aws-lambda-docker-serverless-inference](https://github.com/aws-samples/aws-lambda-docker-serverless-inference) — Semi-official
- [The case for containers on Lambda - benchmarks](https://aaronstuyvenberg.com/posts/containers-on-lambda) — Semi-official
- [BERT Score - Hugging Face evaluate-metric space](https://huggingface.co/spaces/evaluate-metric/bertscore) — **Official**

---

## Core Concepts

### 1. AWS Lambda Container Images

Lambda supports Docker container images as a deployment package type. Key facts from official AWS docs:

- **Maximum uncompressed image size**: 10 GB including all layers. Makes PyTorch + BERT models viable (vs 250 MB zip limit).
- **ECR required**: Images must be stored in Amazon ECR private registry, same region as Lambda.
- **Python 3.12 supported** on `public.ecr.aws/lambda/python:3.12` (Amazon Linux 2023).
- **arm64 supported**: Use `--platform linux/arm64` in `docker buildx build`. Same base image tag as x86_64; architecture set at build time.
- **Read-only root filesystem**: Only `/tmp` writable at runtime.
- **Lambda pins to ECR image digest at deploy time**: Pushing to `:latest` does NOT auto-update the function. Must call `update-function-code` explicitly after every push.
- **`--provenance=false` is required** when building with `docker buildx build` for Lambda. Without it, buildx creates a multi-platform manifest index Lambda cannot use.

**Cold start impact**:
- PyTorch model container with ~250 MB model: AWS blog reports initial cold start up to 25 seconds.
- Lambda lazy-loads container layers — only startup layers pulled eagerly, rest stream in.
- Estimated cold starts: 5–15 seconds for ~2 GB image (distilbert + CPU torch + OS, warm caches); 15–30 seconds for ~4 GB image (roberta-large).
- **Provisioned Concurrency** eliminates cold starts by keeping N environments initialized. Standard production mitigation for ML Lambda containers.

### 2. BERTScore Library

**Default model for English**: `roberta-large` (when `lang="en"` without specifying `model_type`).

**Model weights sizes** (from HuggingFace model file listings — official):

| Model | Weight file size | Notes |
|---|---|---|
| `roberta-large` | 1.42 GB | BERTScore English default |
| `distilbert-base-uncased` | ~268 MB | 6 layers, 66M params |
| `allenai/scibert_scivocab_uncased` | ~440 MB | Recommended for scientific/medical text |
| `all-MiniLM-L6-v2` | ~90.9 MB | 22.7M params, 384-dim |

**pip dependencies**: `torch >= 1.0.0`, `transformers >= 3.0.0`, `pandas`, `numpy`, `requests`, `tqdm`, `matplotlib`, `packaging`

**Approximate installed container size**: CPU-only torch from `download.pytorch.org/whl/cpu` is ~185–200 MB for Linux x86_64. Full container (CPU torch + bert-score + distilbert weights baked in + AL2023 OS base) is approximately 1.5–2.5 GB compressed in ECR.

**Model type to num_layers mapping** (from `utils.py` — official):

| Model | Optimal num_layers |
|---|---|
| `roberta-large` | 17 |
| `bert-base-uncased` | 9 |
| `distilbert-base-uncased` | 5 |
| `allenai/scibert_scivocab_uncased` | 8 |

**Model caching / custom paths**: Set `ENV TRANSFORMERS_CACHE=/var/task/hf_cache` and `ENV HF_HOME=/var/task/hf_cache` in Dockerfile to pre-bake models at image-build time. `from_pretrained()` only needs read access. `BERTScorer` accepts a local filesystem path as `model_type`; when doing so, `num_layers` must be set explicitly (no auto-lookup for paths).

### 3. BERTScore Python API

**`BERTScorer.__init__` key parameters**:
```python
BERTScorer(
    model_type=None,           # HuggingFace model name OR local filesystem path
    num_layers=None,           # which layer; auto-selected for known model names
    batch_size=64,
    device=None,               # "cpu" or "cuda:0"
    lang=None,                 # "en" for English
    rescale_with_baseline=False,
)
```

**`BERTScorer.score(cands, refs)` returns `(P, R, F1)` — three torch.Tensor of shape (N,)**

To score N summaries against 1 reference: repeat the reference N times in the `refs` list.

**Output value range**: F1 values for English text with roberta-large typically fall in [0.84, 0.97]. NOT on a simple [0, 1] scale. With `rescale_with_baseline=True`, values are mapped to a more human-interpretable range.

### 4. Manual BERTScore (transformers only, no bert-score package)

Can skip the bert-score package (~20 MB extra deps) and implement the algorithm directly:
```python
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModel

def bertscore_f1(hypotheses, reference, model, tokenizer):
    ref_emb, ref_mask = _get_token_embeddings([reference], model, tokenizer)
    hyp_emb, hyp_mask = _get_token_embeddings(hypotheses, model, tokenizer)
    f1_scores = []
    for i in range(len(hypotheses)):
        h = F.normalize(hyp_emb[i], dim=-1)
        r = F.normalize(ref_emb[0], dim=-1)
        hm = hyp_mask[i].float()
        rm = ref_mask[0].float()
        sim = h @ r.T
        sim = sim * hm.unsqueeze(1) * rm.unsqueeze(0)
        precision = (sim.max(dim=1).values * hm).sum() / (hm.sum() + 1e-8)
        recall = (sim.max(dim=0).values * rm).sum() / (rm.sum() + 1e-8)
        f1 = 2 * precision * recall / (precision + recall + 1e-8)
        f1_scores.append(f1.item())
    return f1_scores
```

### 5. AWS SageMaker Serverless Inference

- **Memory options**: 1024–6144 MB max. Sufficient for distilbert/scibert; tight for roberta-large.
- **Cold starts**: 5–20 seconds for BERT-class models.
- **No GPU support** on serverless. CPU-only.
- **Lambda integration**: `boto3.client("sagemaker-runtime").invoke_endpoint()` synchronously.
- **Operational complexity**: Requires IAM role, model object, endpoint config, endpoint — 4 extra resources.
- **Verdict**: More operational overhead than Lambda container for a single scoring Lambda. Not recommended.

### 6. AWS Fargate for BERTScore

- **Cold start**: 25–90 seconds consistently. **Not viable synchronously** (API Gateway limit: 29 seconds).
- **Async pattern only**: Lambda triggers Fargate via `ecs.run_task()`, results arrive via S3/DynamoDB.
- **Verdict**: Only viable if BERTScore evaluation is decoupled from the synchronous API response. Not recommended for this pipeline without architectural changes.

### 7. ECR Storage Costs

- $0.10/GB-month. A 2 GB image (distilbert) costs ~$0.20/month.
- Lambda pulls from ECR in-region: no data transfer cost.
- ECR deduplicates layers per private registry, so shared OS base layers stored once.

---

## Code Snippets

### Dockerfile for Python 3.12 arm64 Lambda with BERTScore (distilbert)

```dockerfile
FROM public.ecr.aws/lambda/python:3.12

# CPU-only torch — avoids ~600 MB CUDA stubs in PyPI wheel
RUN pip install --no-cache-dir torch \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir transformers bert-score

ENV TRANSFORMERS_CACHE=/var/task/hf_cache
ENV HF_HOME=/var/task/hf_cache
ENV TOKENIZERS_PARALLELISM=false

# Pre-bake model weights at image build time (~268 MB for distilbert)
# For medical domain: swap 'distilbert-base-uncased' -> 'allenai/scibert_scivocab_uncased'
RUN python -c "\
from transformers import AutoTokenizer, AutoModel; \
m = 'distilbert-base-uncased'; \
AutoTokenizer.from_pretrained(m); \
AutoModel.from_pretrained(m)"

COPY handler.py ${LAMBDA_TASK_ROOT}
CMD ["handler.lambda_handler"]
```

Build for arm64:
```bash
docker buildx build --platform linux/arm64 --provenance=false \
  -t gold-comparator:latest .
```

### Lambda Handler Using BERTScorer

```python
import json, math, re, boto3, torch
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from bert_score import BERTScorer

# Module-level init — warm invocations reuse the loaded model
_scorer = BERTScorer(
    model_type="distilbert-base-uncased",
    num_layers=5,
    device="cpu",
    rescale_with_baseline=False,
)

def lambda_handler(event, context):
    body = json.loads(event.get("body") or "{}")
    texts = body.get("texts", [])
    reference = body.get("reference", "")
    # ... validation ...
    refs_repeated = [reference] * len(texts)
    with torch.no_grad():
        P, R, F1 = _scorer.score(cands=texts, refs=refs_repeated,
                                 verbose=False, batch_size=8)
    bertscore_scores = [float(f) for f in F1.tolist()]
    # ... return stats ...
```

### ECR Push + Lambda Update

```bash
REGION=ap-southeast-2
ACCOUNT=111122223333
REPO=gold-comparator

aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin \
  ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com

aws ecr create-repository --repository-name $REPO --region $REGION \
  --image-scanning-configuration scanOnPush=true

docker tag gold-comparator:latest \
  ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${REPO}:latest
docker push ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${REPO}:latest

aws lambda update-function-code \
  --function-name gold-comparator \
  --image-uri ${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${REPO}:latest \
  --architectures arm64
```

---

## Gotchas & Warnings

1. **`--provenance=false` mandatory** with `docker buildx build` for Lambda.
2. **Lambda pins to ECR digest at deploy time** — pushing to `:latest` does NOT auto-update. Must run `update-function-code`.
3. **Architecture mismatch causes runtime failures** — `--platform` must match Lambda `--architectures`.
4. **Read-only root filesystem** — set `TRANSFORMERS_CACHE` to baked-in `/var/task/hf_cache`, NOT `~/.cache`.
5. **`TOKENIZERS_PARALLELISM=false`** — set in Dockerfile to suppress Lambda log warnings.
6. **roberta-large is 1.42 GB weights alone** — cold starts 15–30 seconds without Provisioned Concurrency.
7. **Local path as `model_type` requires explicit `num_layers`** — no auto-lookup for path strings.
8. **F1 output NOT on [0, 1] scale** — roberta-large typical range [0.84, 0.97].
9. **Memory requirements**: At least 2048 MB for distilbert, 4096 MB for roberta-large.
10. **Initialize BERTScorer at module level** — warm invocations reuse loaded model (critical Lambda ML pattern).
11. **Fargate cold start 25–90 seconds** — not viable for synchronous API Gateway calls.
12. **SageMaker adds 3–4 extra resources** — more operational overhead than Lambda container image.
13. **29-second API Gateway hard limit** — with distilbert on a 3 GB Lambda at N=10 short medical summaries, inference should complete in ~5–15 seconds. N=200 may not.

---

## Verification Results

_Verified by Research Verifier agent. Each claim from the findings above is assessed below._

### Claim: Maximum uncompressed container image size is 10 GB
- **Verdict**: CONFIRMED
- **Source**: https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html
- **Notes**: The official Lambda quotas page states "Container image code package size: 10 GB (maximum uncompressed image size, including all layers)" in the Function configuration table. This is a hard limit that cannot be increased.

### Claim: `--provenance=false` is required when building with `docker buildx build` for Lambda
- **Verdict**: CONFIRMED
- **Source**: https://docs.aws.amazon.com/lambda/latest/dg/python-image.html
- **Notes**: The official AWS Python Lambda container image page states explicitly: "To make your image compatible with Lambda, you must use the `--provenance=false` option." This appears twice in the page (once for AWS base images, once for alternative base images). The reason is that buildx with provenance enabled creates an OCI manifest index (multi-platform format) that Lambda cannot consume; Lambda requires a Docker v2 manifest.

### Claim: Estimated cold starts are 5-15 seconds for a ~2 GB image (distilbert + CPU torch + OS)
- **Verdict**: UNVERIFIABLE
- **Attempts made**: (1) Searched "AWS Lambda container cold start distilbert pytorch inference time seconds" — found the AWS ML blog reporting "up to 25 seconds" for a ~250 MB DistilBERT model and a memory setting of 5,000 MB, but no specific benchmark for a ~2 GB image with warm layer caches. (2) Fetched https://aaronstuyvenberg.com/posts/containers-on-lambda — that article benchmarks functions up to 250 MB of dependencies only and does not include distilbert-scale model timings.
- **Notes**: The AWS ML blog's data point of "up to 25 seconds" for a 250 MB DistilBERT model (at 5,000 MB Lambda memory) suggests the lower bound of the 5-15 second estimate may be optimistic. The upper end of 15 seconds is plausible for warm-cache re-invocations but not for true cold starts from zero. The claimed range should be treated as a best-case warm-cache estimate, not a reliable cold-start floor.

### Claim: BERTScore F1 output range for roberta-large is [0.84, 0.97]
- **Verdict**: CONFIRMED (with nuance)
- **Source**: https://github.com/Tiiiger/bert_score/blob/master/journal/rescale_baseline.md
- **Notes**: The official bert_score rescaling documentation states scores "often are between 0.85 and 0.95" for roberta-large. The claimed range of [0.84, 0.97] is slightly broader but consistent with what the authors document. The lower bound 0.84 and upper bound 0.97 are within the range of real-world variation (especially for near-identical texts reaching the upper end). The core point — that these are not simple [0, 1] probabilities — is accurate.

### Claim: `--provenance=false` reason is that buildx creates a multi-platform manifest index Lambda cannot use
- **Verdict**: CONFIRMED
- **Source**: https://github.com/docker/buildx/issues/1533
- **Notes**: The Docker buildx GitHub issue confirms the root cause: newer buildx versions attach OCI provenance by default, changing the manifest type from Docker v2 (`application/vnd.docker.distribution.manifest.v2+json`) to OCI, which Lambda rejects with an InvalidParameterValueException. The fix is `--provenance=false`.

### Claim: distilbert-base-uncased model weight file size is ~268 MB
- **Verdict**: CONFIRMED
- **Source**: https://huggingface.co/distilbert/distilbert-base-uncased/tree/main
- **Notes**: The HuggingFace model repository shows both `model.safetensors` and `pytorch_model.bin` at exactly 268 MB each. This is confirmed directly from the official model page.

### Claim: Fargate cold start is 25-90 seconds, making it not viable for synchronous API calls
- **Verdict**: CONFIRMED (lower bound underestimates; overall conclusion correct)
- **Source**: https://repost.aws/questions/QUjZAzJd27SZWxXM7MgyxOZw/how-to-speed-up-provisioning-of-ecs-fargate-task
- **Notes**: Multiple sources corroborate that unoptimized Fargate task launches take 30-45 seconds as a typical baseline, with some sources citing 35 seconds to 2 minutes. The claimed lower bound of 25 seconds is slightly optimistic — real-world measurements more commonly start at 30+ seconds. The upper bound of 90 seconds is plausible. The conclusion that this exceeds the 29-second API Gateway hard timeout and makes Fargate non-viable for synchronous calls is correct. Notably, with SOCI (Seekable OCI) lazy loading and other optimizations, sub-5-second launches are now achievable in some configurations, but these require deliberate architectural effort and do not represent default Fargate behavior.

### Claim: Memory requirements for distilbert are at least 2048 MB
- **Verdict**: CORRECTED
- **What is actually correct**: The AWS ML blog post that is the primary source for Lambda/distilbert deployment uses 5,000 MB (5 GB) as its example memory configuration. The HuggingFace automated memory requirements discussion shows the model itself only requires ~253 MB at float32 precision (the largest layer is ~89 MB). However, Lambda memory also governs CPU allocation and overall process headroom for PyTorch, Python runtime, and operator overhead. Community benchmarks show 2048 MB is a workable configuration, but AWS's own example uses 5,000 MB for a similar deployment. The claim that 2048 MB is the minimum is not well-sourced; the official AWS example suggests 5,000 MB for comfortable production use. Treating 2048 MB as a hard minimum understates the memory that AWS itself recommends in practice.
- **Source**: https://aws.amazon.com/blogs/machine-learning/using-container-images-to-run-pytorch-models-in-aws-lambda/
- **Notes**: The claim is not factually wrong in the sense that 2048 MB can work for distilbert inference, but the framing of "at least 2048 MB" as a minimum is misleading when the official AWS example for an equivalent deployment uses 5,000 MB. The Planner should be cautious about sizing Lambda memory at exactly 2048 MB for production workloads with this model.

### Summary

Total claims assessed: 7
- CONFIRMED: 4 (Lambda 10 GB limit, --provenance=false requirement, distilbert weight size, Fargate cold start conclusion)
- CORRECTED: 1 (distilbert Lambda memory requirement)
- UNVERIFIABLE: 1 (distilbert cold start 5-15 second estimate for ~2 GB image)
- CONFIRMED with nuance: 1 (BERTScore F1 range — slightly broader than what authors document as "typical")

**Claims requiring particular Planner caution:**

1. CORRECTED — "Memory requirements: at least 2048 MB for distilbert": The official AWS ML blog example for an equivalent PyTorch/DistilBERT Lambda deployment uses 5,000 MB. 2048 MB may work but is not what AWS demonstrates. Planner should size Lambda at 3072 MB minimum and benchmark, or match the AWS example at 5,000 MB.

2. UNVERIFIABLE — "Estimated cold starts: 5-15 seconds for ~2 GB image": No official or authoritative benchmark was found for this specific image size and model combination. The only official data point (AWS blog) shows up to 25 seconds for a 250 MB distilbert model with 5 GB Lambda memory. The 5-second lower bound of the claimed range is likely too optimistic for an unprimed cold start.
