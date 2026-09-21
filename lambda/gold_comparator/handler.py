"""
POST /gold-compare — gold standard accuracy evaluator Lambda (stdlib only).

Accepts a list of summary texts and a reference text, fetches Titan embeddings
for each in parallel, and returns per-run embedding cosine similarity and
ROUGE-1 F1 scores against the reference.

Request body: {"texts": ["s1", "s2", ...], "reference": "gold text"}  (texts: 2–200)

Response body:
{
  "embedding_cosine": {"scores": [...], "mean": ..., "min": ..., "max": ..., "std": ..., "n": int},
  "rouge1":           {"scores": [...], "mean": ..., "min": ..., "max": ..., "std": ..., "n": int}
}
"""

import json
import math
import re
import boto3
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024
MAX_TEXTS = 200


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


def _rouge1_f1(hypothesis, reference):
    ref_tokens = re.findall(r'\b\w+\b', reference.lower())
    hyp_tokens = re.findall(r'\b\w+\b', hypothesis.lower())
    if not ref_tokens or not hyp_tokens:
        return 0.0
    ref_count = Counter(ref_tokens)
    hyp_count = Counter(hyp_tokens)
    overlap = sum(min(ref_count[t], hyp_count[t]) for t in ref_count)
    recall = overlap / len(ref_tokens)
    precision = overlap / len(hyp_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


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

    bedrock = boto3.client("bedrock-runtime")

    text_embeddings = [None] * len(texts)
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_embed, bedrock, text): i for i, text in enumerate(texts)}
        for future in as_completed(futures):
            idx = futures[future]
            text_embeddings[idx] = future.result()

    ref_embedding = _embed(bedrock, reference)

    emb_scores = [_cosine(te, ref_embedding) for te in text_embeddings]
    rouge_scores = [_rouge1_f1(text, reference) for text in texts]

    return _ok({
        "embedding_cosine": _score_stats(emb_scores),
        "rouge1": _score_stats(rouge_scores),
    })
