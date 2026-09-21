"""
POST /compare — consistency comparator Lambda (stdlib only, no numpy/sklearn).

Accepts a list of summary texts, fetches Titan Text Embeddings v2 for each,
and returns pairwise cosine similarity (embedding + TF-IDF) with variability
stats and the raw embedding vectors.

Titan returns pre-normalised vectors when normalize=True, so cosine similarity
reduces to a dot product — no numpy required.

Request body: {"texts": ["summary 1", "summary 2", ...]}   (2–200 entries)

Response body:
{
  "embeddings": [[...1024 floats per text...]],
  "embedding_cosine": {"matrix": [[...]], "mean": ..., "min": ..., ...},
  "tfidf_cosine":     {"matrix": [[...]], "mean": ..., "min": ..., ...}
}
"""

import json
import math
import re
import boto3
from collections import Counter
from itertools import combinations

EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024
MAX_TEXTS = 200


def _upper_triangle(matrix):
    n = len(matrix)
    return [matrix[i][j] for i, j in combinations(range(n), 2)]


def _variability_stats(n_runs, scores):
    n_pairs = len(scores)
    mean = sum(scores) / n_pairs
    variance = sum((s - mean) ** 2 for s in scores) / n_pairs
    std = math.sqrt(variance)
    return {
        "n_runs": n_runs,
        "n_pairs": n_pairs,
        "mean": mean,
        "min": min(scores),
        "max": max(scores),
        "std": std,
        "variance": variance,
        "cv": std / mean if mean != 0 else None,
    }


def _embedding_sim_matrix(embeddings):
    """Cosine similarity via dot product (valid because Titan normalises vectors)."""
    n = len(embeddings)
    matrix = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for i, j in combinations(range(n), 2):
        score = sum(a * b for a, b in zip(embeddings[i], embeddings[j]))
        matrix[i][j] = matrix[j][i] = score
    return matrix


def _tokenize(text):
    return re.findall(r'\b[a-z]{2,}\b', text.lower())


def _tfidf_sim_matrix(texts):
    n = len(texts)
    tf_dicts = [Counter(_tokenize(t)) for t in texts]
    all_terms = set(term for tf in tf_dicts for term in tf)

    if not all_terms:
        return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

    df = {term: sum(1 for tf in tf_dicts if term in tf) for term in all_terms}
    idf = {term: math.log((n + 1) / (df[term] + 1)) + 1 for term in all_terms}

    vectors = []
    for tf in tf_dicts:
        vec = {term: tf[term] * idf[term] for term in tf}
        norm = math.sqrt(sum(v ** 2 for v in vec.values()))
        vectors.append({t: v / norm for t, v in vec.items()} if norm > 0 else {})

    matrix = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for i, j in combinations(range(n), 2):
        score = sum(vectors[i].get(t, 0.0) * vectors[j].get(t, 0.0) for t in vectors[i])
        matrix[i][j] = matrix[j][i] = score
    return matrix


def _ok(body):
    return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def _err(status, message):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": message})}


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _err(400, "Invalid JSON body")

    texts = body.get("texts", [])
    if not isinstance(texts, list) or len(texts) < 2:
        return _err(400, "texts must be an array of at least 2 strings")
    if len(texts) > MAX_TEXTS:
        return _err(400, f"texts must have at most {MAX_TEXTS} entries")
    if not all(isinstance(t, str) for t in texts):
        return _err(400, "every entry in texts must be a string")

    bedrock = boto3.client("bedrock-runtime")

    embeddings = []
    for text in texts:
        response = bedrock.invoke_model(
            modelId=EMBEDDING_MODEL,
            body=json.dumps({"inputText": text, "dimensions": EMBEDDING_DIMENSIONS, "normalize": True}),
            contentType="application/json",
            accept="application/json",
        )
        embeddings.append(json.loads(response["body"].read())["embedding"])

    n = len(embeddings)
    emb_matrix = _embedding_sim_matrix(embeddings)
    tfidf_matrix = _tfidf_sim_matrix(texts)

    return _ok({
        "embeddings": embeddings,
        "embedding_cosine": {"matrix": emb_matrix, **_variability_stats(n, _upper_triangle(emb_matrix))},
        "tfidf_cosine":     {"matrix": tfidf_matrix, **_variability_stats(n, _upper_triangle(tfidf_matrix))},
    })
