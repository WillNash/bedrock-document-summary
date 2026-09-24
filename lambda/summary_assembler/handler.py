import json
import logging
import os
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
bedrock_runtime = boto3.client('bedrock-runtime')

SUMMARIES_BUCKET = os.environ['SUMMARIES_BUCKET']
EXPENSIVE_MODEL_ID = os.environ['EXPENSIVE_MODEL_ID']

FULL_REGEN_PROMPT = """\
Given the original summary and verified claim verdicts, rewrite the summary.

Original summary:
<summary>{original_summary}</summary>

Verified claims:
{verdicts_json}

Instructions:
1. Retain all supported claims verbatim where possible.
2. Remove or correct contradicted claims using only the quoted evidence. Do not paraphrase beyond what the evidence says.
3. Remove unverifiable claims or explicitly hedge them with language like "the document states" or "reportedly".
4. Preserve the original structure and tone.
5. Do not add any information not present in the quoted evidence.

Return the corrected summary only.\
"""

HEDGING_PROMPT = """\
The following medical summary contains a sentence that is unverifiable against the source \
document (no supporting passage was found). Rewrite the summary with that sentence hedged \
using language like "the document states" or "reportedly". Do not add any new information. \
Do not change any other sentence.

Full summary:
<summary>{summary}</summary>

Sentence to hedge:
{sentence}

Return the complete corrected summary only.\
"""

SPAN_REPLACEMENT_PROMPT = """\
The following medical summary contains a sentence that contradicts the source document. \
Rewrite the summary with that sentence corrected using ONLY the quoted evidence below. \
Do not add any information not present in the evidence. Do not change any other sentence.

Full summary:
<summary>{summary}</summary>

Sentence to correct:
{sentence}

Quoted evidence from source:
{evidence_quote}

Return the complete corrected summary only.\
"""


def _call_sonnet(prompt: str) -> str:
    response = bedrock_runtime.converse(
        modelId=EXPENSIVE_MODEL_ID,
        messages=[{'role': 'user', 'content': [{'text': prompt}]}],
        inferenceConfig={'maxTokens': 2048, 'temperature': 0},
    )
    return response['output']['message']['content'][0]['text'].strip()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    job_id = event['job_id']
    verdicts_key = event['verdicts_key']
    summary_key = event['summary_key']

    verdicts_obj = s3_client.get_object(Bucket=SUMMARIES_BUCKET, Key=verdicts_key)
    verdicts = json.loads(verdicts_obj['Body'].read())

    summary_obj = s3_client.get_object(Bucket=SUMMARIES_BUCKET, Key=summary_key)
    original_summary = summary_obj['Body'].read().decode('utf-8')

    n_contradicted = sum(1 for v in verdicts if v.get('verdict') == 'contradicted')
    n_unverifiable = sum(1 for v in verdicts if v.get('verdict') == 'unverifiable')
    n_bad = n_contradicted + n_unverifiable
    n_total = len(verdicts)
    n_supported = n_total - n_bad

    if n_bad == 0:
        corrected_text = original_summary

    elif n_bad >= 3:
        prompt = FULL_REGEN_PROMPT.format(
            original_summary=original_summary,
            verdicts_json=json.dumps(verdicts, indent=2),
        )
        corrected_text = _call_sonnet(prompt)

    else:
        corrected_text = original_summary
        bad_verdicts = [v for v in verdicts if v.get('verdict') in ('contradicted', 'unverifiable')]
        for verdict in bad_verdicts:
            claim = verdict['claim']
            if verdict['verdict'] == 'unverifiable':
                prompt = HEDGING_PROMPT.format(summary=corrected_text, sentence=claim)
            else:
                prompt = SPAN_REPLACEMENT_PROMPT.format(
                    summary=corrected_text,
                    sentence=claim,
                    evidence_quote=verdict.get('evidence_quote', ''),
                )
            corrected_text = _call_sonnet(prompt)

    validated_summary_key = f'summaries/{job_id}/validated_summary.txt'
    s3_client.put_object(
        Bucket=SUMMARIES_BUCKET,
        Key=validated_summary_key,
        Body=corrected_text.encode('utf-8'),
        ContentType='text/plain; charset=utf-8',
    )

    logger.info(json.dumps({
        'job_id': job_id,
        'action': 'summary_assembled',
        'n_total': n_total,
        'n_supported': n_supported,
        'n_contradicted': n_contradicted,
        'n_unverifiable': n_unverifiable,
    }))

    return {
        'validated_summary_key': validated_summary_key,
        'claim_stats': {
            'total': n_total,
            'supported': n_supported,
            'contradicted': n_contradicted,
            'unverifiable': n_unverifiable,
        },
    }
