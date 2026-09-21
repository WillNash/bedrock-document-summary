"""
POST /compare — consistency comparator Lambda.

Accepts a list of summary texts, fetches Titan Text Embeddings v2 for each,
and returns pairwise cosine similarity (embedding + TF-IDF) with variability
stats and the raw embedding vectors.

Request body: {"texts": ["summary 1", "summary 2", ...]}   (2–20 entries)

Response body:
{
  "embeddings": [[...1024 floats per text...]],
  "embedding_cosine": {"matrix": [[...]], "mean": ..., "min": ..., ...},
  "tfidf_cosine":     {"matrix": [[...]], "mean": ..., "min": ..., ...}
}
"""

import json
import boto3
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024
MAX_TEXTS = 200


def _variability_stats(sim_matrix: np.ndarray) -> dict:
    n = sim_matrix.shape[0]
    idx = np.triu_indices(n, k=1)
    scores = sim_matrix[idx]
    mean = float(np.mean(scores))
    return {
        "n_runs": int(n),
        "n_pairs": int(len(scores)),
        "mean": mean,
        "min": float(np.min(scores)),
        "max": float(np.max(scores)),
        "std": float(np.std(scores)),
        "variance": float(np.var(scores)),
        "cv": float(np.std(scores) / mean) if mean != 0 else None,
    }


def _ok(body: dict) -> dict:
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _err(status: int, message: str) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }


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
            body=json.dumps(
                {"inputText": text, "dimensions": EMBEDDING_DIMENSIONS, "normalize": True}
            ),
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        embeddings.append(result["embedding"])

    embeddings_np = np.array(embeddings)
    emb_sim = cosine_similarity(embeddings_np)
    emb_stats = _variability_stats(emb_sim)

    try:
        tfidf_sim = cosine_similarity(TfidfVectorizer().fit_transform(texts))
    except ValueError:
        # Empty vocabulary (e.g. texts contain only stop-words or single chars).
        # Return a zero-off-diagonal matrix so stats remain well-defined.
        tfidf_sim = np.zeros((len(texts), len(texts)))
        np.fill_diagonal(tfidf_sim, 1.0)
    tfidf_stats = _variability_stats(tfidf_sim)

    return _ok(
        {
            "embeddings": embeddings,
            "embedding_cosine": {"matrix": emb_sim.tolist(), **emb_stats},
            "tfidf_cosine": {"matrix": tfidf_sim.tolist(), **tfidf_stats},
        }
    )
