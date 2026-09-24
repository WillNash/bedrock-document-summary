import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
bedrock_runtime = boto3.client('bedrock-runtime')

SUMMARIES_BUCKET = os.environ['SUMMARIES_BUCKET']
CHEAP_MODEL_ID = os.environ['CHEAP_MODEL_ID']
EXPENSIVE_MODEL_ID = os.environ['EXPENSIVE_MODEL_ID']
TRIAGE_THRESHOLD = float(os.environ.get('TRIAGE_SIMILARITY_THRESHOLD', '0.55'))

VERDICT_SYSTEM = (
    "You are a strict medical claim verifier conducting scrutiny review. Given a claim "
    "and passages from the source document, assess whether the claim is supported, "
    "contradicted, or unverifiable. Rules: "
    "(1) Quote the relevant passage span before rendering your verdict. "
    "(2) Use ONLY the provided passages — no external knowledge. "
    "(3) Named failure modes to detect: quantifier drift, causal embellishment, numerical "
    "transposition, entity swaps. "
    "(4) Apply maximum caution — this claim has been flagged as potentially incorrect. "
    "Return JSON only: "
    '{\"verdict\": \"supported\"|\"contradicted\"|\"unverifiable\", '
    '\"evidence_quote\": \"...\", \"reason\": \"...\"}'
)


def _needs_escalation(verdict_record):
    return (
        verdict_record.get('verdict') == 'contradicted'
        or verdict_record.get('top_passage_similarity', 1.0) < TRIAGE_THRESHOLD
    )


def _reassess(verdict_record):
    claim = verdict_record['claim']
    passages_text = '\n\n'.join(f'[Passage]: {p}' for p in verdict_record.get('top_passages', []))
    user_msg = f'Claim: {claim}\n\nSource passages:\n{passages_text}'
    response = bedrock_runtime.converse(
        modelId=EXPENSIVE_MODEL_ID,
        system=[{'text': VERDICT_SYSTEM}],
        messages=[{'role': 'user', 'content': [{'text': user_msg}]}],
        inferenceConfig={'maxTokens': 512, 'temperature': 0},
    )
    raw = response['output']['message']['content'][0]['text'].strip()
    try:
        updated = json.loads(raw)
    except json.JSONDecodeError:
        updated = {'verdict': 'unverifiable', 'evidence_quote': '', 'reason': 'parse_error'}

    updated['claim'] = claim
    updated['top_passage_similarity'] = verdict_record.get('top_passage_similarity', 0.0)
    updated['escalated'] = True
    return updated


def lambda_handler(event, context):
    job_id = event['job_id']
    triage_key = event['triage_key']

    triage_obj = s3_client.get_object(Bucket=SUMMARIES_BUCKET, Key=triage_key)
    verdicts = json.loads(triage_obj['Body'].read())

    escalated_indices = [i for i, v in enumerate(verdicts) if _needs_escalation(v)]

    for i in escalated_indices:
        verdicts[i] = _reassess(verdicts[i])

    verdicts_key = f'summaries/{job_id}/verdicts.json'
    s3_client.put_object(
        Bucket=SUMMARIES_BUCKET,
        Key=verdicts_key,
        Body=json.dumps(verdicts).encode('utf-8'),
        ContentType='application/json',
    )

    logger.info(json.dumps({
        'job_id': job_id,
        'action': 'assessment_complete',
        'total': len(verdicts),
        'escalated': len(escalated_indices),
    }))

    return {**event, 'verdicts_key': verdicts_key}
