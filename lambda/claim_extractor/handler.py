import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from jinja2 import Environment, FileSystemLoader, StrictUndefined

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TEMPLATE_DIR = Path(__file__).parent / 'templates'
TEMPLATE_FILES = {
    'lab_result': 'lab_result.j2',
    'doctors_notes': 'doctors_notes.j2',
    'injury_doc': 'injury_doc.j2',
    'visit_assessment': 'visit_assessment.j2',
    'psych_eval': 'psych_eval.j2',
}
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

s3_client = boto3.client('s3')
bedrock_runtime = boto3.client('bedrock-runtime')

CHEAP_MODEL_ID = os.environ['CHEAP_MODEL_ID']
EMBEDDING_MODEL_ID = os.environ['EMBEDDING_MODEL_ID']
UPLOAD_BUCKET = os.environ['UPLOAD_BUCKET']
SUMMARIES_BUCKET = os.environ['SUMMARIES_BUCKET']
DEDUP_THRESHOLD = float(os.environ.get('DEDUP_SIMILARITY_THRESHOLD', '0.90'))
CLAIM_CAP = 40

EXTRACTION_SYSTEM = (
    "You are a medical claim analyst. For the sentence between <SOS> and <EOS>, "
    "extract a single self-contained atomic claim (no pronouns, all temporal and spatial "
    "modifiers explicit). Then classify it as 'verifiable' (can be proven or disproven "
    "against a source document) or 'non_verifiable' (task_meta, general_knowledge, or "
    "subjective). Return JSON only: "
    '{\"claim\": \"...\", \"type\": \"verifiable\"|\"non_verifiable\", \"reason\": \"...\"}'
)


def _embed(text):
    response = bedrock_runtime.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps({'inputText': text, 'dimensions': 1024, 'normalize': True}),
    )
    return json.loads(response['body'].read())['embedding']


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _split_sentences(text):
    sentences = re.split(r'(?<=[.!?])\s+|\n+', text)
    return [s.strip() for s in sentences if s.strip()]


def _extract_claim(sentence, context_before, context_after):
    context1 = ' '.join(context_before[-3:]) if context_before else ''
    context2 = context_after[0] if context_after else ''
    window = f'{context1} <SOS>{sentence}<EOS> {context2}'.strip()

    response = bedrock_runtime.converse(
        modelId=CHEAP_MODEL_ID,
        system=[{'text': EXTRACTION_SYSTEM}],
        messages=[{'role': 'user', 'content': [{'text': window}]}],
        inferenceConfig={'maxTokens': 256, 'temperature': 0},
    )
    raw = response['output']['message']['content'][0]['text'].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def lambda_handler(event, context):
    job_id = event['job_id']
    doc_type = event['doc_type']
    validated_data = event['validated_data']
    source_bucket = event['bucket']
    source_key = event['key']

    template = jinja_env.get_template(TEMPLATE_FILES[doc_type])
    summary_text = template.render(**validated_data)

    pre_render_key = f'summaries/{job_id}/pre_render.txt'
    s3_client.put_object(
        Bucket=SUMMARIES_BUCKET,
        Key=pre_render_key,
        Body=summary_text.encode('utf-8'),
        ContentType='text/plain; charset=utf-8',
    )

    source_obj = s3_client.get_object(Bucket=source_bucket, Key=source_key)
    source_text = source_obj['Body'].read().decode('utf-8')  # noqa: F841 (available for future use)

    sentences = _split_sentences(summary_text)
    verifiable_claims = []

    for i, sentence in enumerate(sentences):
        before = sentences[:i]
        after = sentences[i + 1:]
        result = _extract_claim(sentence, before, after)
        if result and result.get('type') == 'verifiable' and result.get('claim'):
            verifiable_claims.append(result['claim'])

    if not verifiable_claims:
        claims_key = f'summaries/{job_id}/claims.json'
        s3_client.put_object(
            Bucket=SUMMARIES_BUCKET,
            Key=claims_key,
            Body=json.dumps([]).encode('utf-8'),
            ContentType='application/json',
        )
        logger.info(json.dumps({'job_id': job_id, 'action': 'no_verifiable_claims'}))
        return {
            'job_id': job_id,
            'bucket': source_bucket,
            'key': source_key,
            'summary_key': pre_render_key,
            'claims_key': claims_key,
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        embeddings = list(pool.map(_embed, verifiable_claims))

    accepted_claims = []
    accepted_embeddings = []
    for claim, emb in zip(verifiable_claims, embeddings):
        if any(_dot(emb, acc_emb) >= DEDUP_THRESHOLD for acc_emb in accepted_embeddings):
            continue
        accepted_claims.append(claim)
        accepted_embeddings.append(emb)
        if len(accepted_claims) >= CLAIM_CAP:
            break

    claims_key = f'summaries/{job_id}/claims.json'
    s3_client.put_object(
        Bucket=SUMMARIES_BUCKET,
        Key=claims_key,
        Body=json.dumps(accepted_claims).encode('utf-8'),
        ContentType='application/json',
    )

    logger.info(json.dumps({'job_id': job_id, 'action': 'claims_extracted', 'count': len(accepted_claims)}))

    return {
        'job_id': job_id,
        'bucket': source_bucket,
        'key': source_key,
        'summary_key': pre_render_key,
        'claims_key': claims_key,
    }
