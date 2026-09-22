"""
Step Functions task — ComputeGoldAccuracy.

Reads summaries from S3 (never via payload to avoid PHI in SFn history),
fetches Titan embeddings, and computes per-run embedding cosine similarity
and BERTScore F1 against the gold-standard reference text.

Input:  {
  "summaries_bucket": "...",
  "run_manifests": [{"run_number": N, "summary_key": "...", ...}],
  "gold_key": "experiments/.../gold.txt"
}
Output (merged into $.gold_results via ResultPath): {
  "embedding_cosine": {"scores": [...], "run_numbers": [...], "mean": ..., "std": ..., "min": ..., "max": ..., "n": N},
  "bertscore_f1":     {"scores": [...], "run_numbers": [...], "mean": ..., "std": ..., "min": ..., "max": ..., "n": N}
}
"""

import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import torch
from bert_score import BERTScorer

logger = logging.getLogger()
logger.setLevel(logging.INFO)

EMBEDDING_MODEL = 'amazon.titan-embed-text-v2:0'
EMBEDDING_DIMENSIONS = 1024

s3_client = boto3.client('s3')
bedrock_client = boto3.client('bedrock-runtime')

_scorer = BERTScorer(
    model_type='allenai/scibert_scivocab_uncased',
    num_layers=8,
    device='cpu',
    rescale_with_baseline=False,
)
# scibert's tokenizer_config.json omits model_max_length; force to actual positional limit.
# Step Functions timeout is 300s — use the full 512-token limit for accuracy.
# (gold_comparator, which is behind API Gateway, keeps 256.)
_scorer._tokenizer.model_max_length = 512


def _read_text(bucket, key):
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


def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


def _score_stats(scores, run_numbers):
    n = len(scores)
    mean = sum(scores) / n
    variance = sum((x - mean) ** 2 for x in scores) / n
    return {
        'scores': scores,
        'run_numbers': run_numbers,
        'mean': mean,
        'min': min(scores),
        'max': max(scores),
        'std': math.sqrt(variance),
        'n': n,
    }


def lambda_handler(event, context):
    bucket = event['summaries_bucket']
    run_manifests = event['run_manifests']
    gold_key = event['gold_key']

    gold_text = _read_text(bucket, gold_key)
    texts = []
    run_numbers = []
    for manifest in run_manifests:
        texts.append(_read_text(bucket, manifest['summary_key']))
        run_numbers.append(manifest['run_number'])

    logger.info(json.dumps({'action': 'embedding_gold_runs', 'n': len(texts)}))

    text_embeddings = [None] * len(texts)
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_embed, text): i for i, text in enumerate(texts)}
        for future in as_completed(futures):
            text_embeddings[futures[future]] = future.result()

    ref_embedding = _embed(gold_text)
    emb_scores = [_cosine(te, ref_embedding) for te in text_embeddings]

    refs_repeated = [gold_text] * len(texts)
    with torch.no_grad():
        _P, _R, F1 = _scorer.score(cands=texts, refs=refs_repeated, verbose=False, batch_size=8)
    bertscore_scores = [float(f) for f in (F1.tolist() if hasattr(F1, 'tolist') else F1)]

    logger.info(json.dumps({
        'action': 'gold_accuracy_computed',
        'n_runs': len(texts),
        'embedding_mean': sum(emb_scores) / len(emb_scores),
        'bertscore_mean': sum(bertscore_scores) / len(bertscore_scores),
    }))

    return {
        'embedding_cosine': _score_stats(emb_scores, run_numbers),
        'bertscore_f1': _score_stats(bertscore_scores, run_numbers),
    }
