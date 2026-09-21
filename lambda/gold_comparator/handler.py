"""
POST /gold-compare — gold standard accuracy evaluator Lambda.

Accepts a list of summary texts and a reference text, fetches Titan embeddings
for each in parallel, and computes per-run embedding cosine similarity and
BERTScore F1 against the reference using allenai/scibert_scivocab_uncased.

BERTScore F1 is calibrated for scientific/medical text. Typical range for
similar texts: ~0.84–0.97 (not a 0-to-1 scale — scores below 0.84 indicate
meaningful semantic divergence from the reference).

Request body: {"texts": ["s1", "s2", ...], "reference": "gold text"}  (texts: 2–200)
BERTScore cap: at most 20 texts per request due to CPU inference time.

Response body:
{
  "embedding_cosine": {"scores": [...], "mean": ..., "min": ..., "max": ..., "std": ..., "n": int},
  "bertscore_f1":     {"scores": [...], "mean": ..., "min": ..., "max": ..., "std": ..., "n": int}
}
"""

import json
import math
import boto3
import torch
from bert_score import BERTScorer
from concurrent.futures import ThreadPoolExecutor, as_completed

EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024
MAX_TEXTS = 200
BERTSCORE_MAX_TEXTS = 20

_scorer = BERTScorer(
    model_type="allenai/scibert_scivocab_uncased",
    num_layers=8,
    device="cpu",
    rescale_with_baseline=False,
)


def _embed(bedrock, text):
    response = bedrock.invoke_model(
        modelId=EMBEDDING_MODEL,
        body=json.dumps({"inputText": text, "dimensions": EMBEDDING_DIMENSIONS, "normalize": True}),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]


def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


def _score_stats(scores):
    n = len(scores)
    mean = sum(scores) / n
    variance = sum((x - mean) ** 2 for x in scores) / n
    return {
        "scores": scores,
        "mean": mean,
        "min": min(scores),
        "max": max(scores),
        "std": math.sqrt(variance),
        "n": n,
    }


def _ok(body):
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def _err(status, message):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": message})}


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _err(400, "Invalid JSON body")

    texts = body.get("texts")
    if not isinstance(texts, list):
        return _err(400, "texts must be an array of at least 2 strings")
    if len(texts) < 2:
        return _err(400, "texts must be an array of at least 2 strings")
    if len(texts) > MAX_TEXTS:
        return _err(400, f"texts must have at most {MAX_TEXTS} entries")
    if not all(isinstance(t, str) for t in texts):
        return _err(400, "every entry in texts must be a string")

    reference = body.get("reference")
    if not isinstance(reference, str) or not reference.strip():
        return _err(400, "reference must be a non-empty string")

    if len(texts) > BERTSCORE_MAX_TEXTS:
        return _err(400, f"BERTScore supports at most {BERTSCORE_MAX_TEXTS} texts per request due to CPU inference limits")

    bedrock = boto3.client("bedrock-runtime")

    text_embeddings = [None] * len(texts)
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_embed, bedrock, text): i for i, text in enumerate(texts)}
        for future in as_completed(futures):
            idx = futures[future]
            text_embeddings[idx] = future.result()

    ref_embedding = _embed(bedrock, reference)

    emb_scores = [_cosine(te, ref_embedding) for te in text_embeddings]

    refs_repeated = [reference] * len(texts)
    with torch.no_grad():
        _P, _R, F1 = _scorer.score(cands=texts, refs=refs_repeated, verbose=False, batch_size=8)
    bertscore_scores = [float(f) for f in (F1.tolist() if hasattr(F1, "tolist") else F1)]

    return _ok({
        "embedding_cosine": _score_stats(emb_scores),
        "bertscore_f1": _score_stats(bertscore_scores),
    })
