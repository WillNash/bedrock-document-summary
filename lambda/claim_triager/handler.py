import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
bedrock_runtime = boto3.client('bedrock-runtime')

CHEAP_MODEL_ID = os.environ['CHEAP_MODEL_ID']
EMBEDDING_MODEL_ID = os.environ['EMBEDDING_MODEL_ID']
UPLOAD_BUCKET = os.environ['UPLOAD_BUCKET']
SUMMARIES_BUCKET = os.environ['SUMMARIES_BUCKET']
TRIAGE_THRESHOLD = float(os.environ.get('TRIAGE_SIMILARITY_THRESHOLD', '0.55'))

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 500
TOP_K = 3

VERDICT_SYSTEM = (
    "You are a strict medical claim verifier. Given a claim and passages from the source "
    "document, assess whether the claim is supported, contradicted, or unverifiable. Rules: "
    "(1) Quote the relevant passage span before rendering your verdict. "
    "(2) Use ONLY the provided passages — no external knowledge. "
    "(3) Named failure modes to detect: quantifier drift, causal embellishment, numerical "
    "transposition, entity swaps. "
    "Return JSON only: "
    '{\"verdict\": \"supported\"|\"contradicted\"|\"unverifiable\", '
    '\"evidence_quote\": \"...\", \"reason\": \"...\"}'
)


def _embed(text):
    response = bedrock_runtime.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps({'inputText': text, 'dimensions': 1024, 'normalize': True}),
    )
    return json.loads(response['body'].read())['embedding']


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _chunk_text(text):
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if c.strip()]


def _triage_claim(claim, passage_texts, passage_embeddings):
    claim_emb = _embed(claim)
    scores = [(_dot(claim_emb, p_emb), p_text) for p_emb, p_text in zip(passage_embeddings, passage_texts)]
    scores.sort(key=lambda x: x[0], reverse=True)
    top = scores[:TOP_K]
    top_similarity = top[0][0] if top else 0.0
    top_passages = '\n\n'.join(f'[Passage]: {p}' for _, p in top)

    user_msg = f'Claim: {claim}\n\nSource passages:\n{top_passages}'
    response = bedrock_runtime.converse(
        modelId=CHEAP_MODEL_ID,
        system=[{'text': VERDICT_SYSTEM}],
        messages=[{'role': 'user', 'content': [{'text': user_msg}]}],
        inferenceConfig={'maxTokens': 512, 'temperature': 0},
    )
    raw = response['output']['message']['content'][0]['text'].strip()
    try:
        verdict = json.loads(raw)
    except json.JSONDecodeError:
        verdict = {'verdict': 'unverifiable', 'evidence_quote': '', 'reason': 'parse_error'}

    verdict['claim'] = claim
    verdict['top_passage_similarity'] = top_similarity
    return verdict


def lambda_handler(event, context):
    job_id = event['job_id']
    source_bucket = event['bucket']
    source_key = event['key']
    claims_key = event['claims_key']

    source_obj = s3_client.get_object(Bucket=source_bucket, Key=source_key)
    source_text = source_obj['Body'].read().decode('utf-8')

    claims_obj = s3_client.get_object(Bucket=SUMMARIES_BUCKET, Key=claims_key)
    claims = json.loads(claims_obj['Body'].read())

    if not claims:
        triage_key = f'summaries/{job_id}/triage.json'
        s3_client.put_object(
            Bucket=SUMMARIES_BUCKET,
            Key=triage_key,
            Body=json.dumps([]).encode('utf-8'),
            ContentType='application/json',
        )
        return {**event, 'triage_key': triage_key}

    passages = _chunk_text(source_text)

    with ThreadPoolExecutor(max_workers=8) as pool:
        passage_embeddings = list(pool.map(_embed, passages))

    verdicts = [_triage_claim(claim, passages, passage_embeddings) for claim in claims]

    triage_key = f'summaries/{job_id}/triage.json'
    s3_client.put_object(
        Bucket=SUMMARIES_BUCKET,
        Key=triage_key,
        Body=json.dumps(verdicts).encode('utf-8'),
        ContentType='application/json',
    )

    logger.info(json.dumps({'job_id': job_id, 'action': 'triage_complete', 'count': len(verdicts)}))

    return {**event, 'triage_key': triage_key}
