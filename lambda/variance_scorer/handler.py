"""
Step Functions task — ComputeVariance.

Reads summaries from S3 (never via payload to avoid PHI in SFn history),
fetches Titan Text Embeddings v2 for each, and computes pairwise cosine
similarity (embedding + TF-IDF) with variability statistics.

Input:  {
  "summaries_bucket": "...",
  "run_manifests": [{"run_number": N, "summary_key": "...", ...}]
}
Output (merged into $.variance_results via ResultPath): {
  "embedding_cosine": {"matrix": [[...]], "mean": ..., "std": ..., "variance": ..., "min": ..., "max": ..., "n_runs": N, "n_pairs": M},
  "tfidf_cosine":     {"matrix": [[...]], "mean": ..., "std": ..., "variance": ..., "min": ..., "max": ..., "n_runs": N, "n_pairs": M}
}
"""

import json
import logging
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

EMBEDDING_MODEL = 'amazon.titan-embed-text-v2:0'
EMBEDDING_DIMENSIONS = 1024

s3_client = boto3.client('s3')
bedrock_client = boto3.client('bedrock-runtime')


def _read_summary(bucket, key):
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    return obj['Body'].read().decode('utf-8', errors='replace')


def _embed(text):
    response = bedrock_client.invoke_model(
        modelId=EMBEDDING_MODEL,
        body=json.dumps({'inputText': text, 'dimensions': EMBEDDING_DIMENSIONS, 'normalize': True}),
        contentType='application/json',
        accept='application/json',
    )
    return json.loads(response['body'].read())['embedding']


def _upper_triangle(matrix):
    n = len(matrix)
    return [matrix[i][j] for i, j in combinations(range(n), 2)]


def _variability_stats(n_runs, scores):
    n_pairs = len(scores)
    mean = sum(scores) / n_pairs
    variance = sum((s - mean) ** 2 for s in scores) / n_pairs
    std = math.sqrt(variance)
    return {
        'n_runs': n_runs,
        'n_pairs': n_pairs,
        'mean': mean,
        'min': min(scores),
        'max': max(scores),
        'std': std,
        'variance': variance,
    }


def _embedding_sim_matrix(embeddings):
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


def lambda_handler(event, context):
    bucket = event['summaries_bucket']
    run_manifests = event['run_manifests']

    if len(run_manifests) < 2:
        raise ValueError(f'Need at least 2 successful runs to compute variance, got {len(run_manifests)}')

    texts = []
    run_numbers = []
    for manifest in run_manifests:
        texts.append(_read_summary(bucket, manifest['summary_key']))
        run_numbers.append(manifest['run_number'])

    logger.info(json.dumps({'action': 'embedding_runs', 'n': len(texts)}))
    embeddings = [None] * len(texts)
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_embed, t): i for i, t in enumerate(texts)}
        for future in as_completed(futures):
            embeddings[futures[future]] = future.result()

    n = len(embeddings)
    emb_matrix = _embedding_sim_matrix(embeddings)
    tfidf_matrix = _tfidf_sim_matrix(texts)

    emb_scores = _upper_triangle(emb_matrix)
    tfidf_scores = _upper_triangle(tfidf_matrix)

    logger.info(json.dumps({
        'action': 'variance_computed',
        'n_runs': n,
        'embedding_mean': sum(emb_scores) / len(emb_scores),
        'tfidf_mean': sum(tfidf_scores) / len(tfidf_scores),
    }))

    return {
        'embedding_cosine': {
            'matrix': emb_matrix,
            'run_numbers': run_numbers,
            **_variability_stats(n, emb_scores),
        },
        'tfidf_cosine': {
            'matrix': tfidf_matrix,
            'run_numbers': run_numbers,
            **_variability_stats(n, tfidf_scores),
        },
    }
