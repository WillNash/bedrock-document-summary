import boto3
import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

VALID_DOC_TYPES = {'lab_result', 'doctors_notes', 'injury_doc', 'visit_assessment', 'psych_eval'}

bedrock_agent = boto3.client('bedrock-agent')
bedrock_runtime = boto3.client('bedrock-runtime')
s3_client = boto3.client('s3')


def _get_prompt_text():
    prompt_arn = os.environ['CLASSIFIER_PROMPT_ARN']
    prompt_version = os.environ['CLASSIFIER_PROMPT_VERSION']
    response = bedrock_agent.get_prompt(
        promptIdentifier=prompt_arn,
        promptVersion=prompt_version,
    )
    variants = response.get('variants', [])
    if not variants:
        raise ValueError('No variants found in classifier prompt')
    content = variants[0].get('templateConfiguration', {}).get('text', {}).get('text', '')
    if not content:
        raise ValueError('Empty prompt text in classifier prompt variant')
    return content


def lambda_handler(event, context):
    job_id = event['job_id']
    bucket = event['bucket']
    key = event['key']

    s3_response = s3_client.get_object(Bucket=bucket, Key=key)
    document_text = s3_response['Body'].read().decode('utf-8', errors='replace')

    system_prompt = _get_prompt_text()
    model_id = os.environ['BEDROCK_CLASSIFIER_MODEL_ID']
    prompt_arn = os.environ['CLASSIFIER_PROMPT_ARN']
    prompt_version = os.environ['CLASSIFIER_PROMPT_VERSION']

    guardrail_config = {}
    guardrail_id = os.environ.get('GUARDRAIL_ID', '')
    guardrail_version = os.environ.get('GUARDRAIL_VERSION', '')
    if guardrail_id and guardrail_version:
        guardrail_config = {
            'guardrailIdentifier': guardrail_id,
            'guardrailVersion': guardrail_version,
            'trace': 'disabled',
        }

    converse_kwargs = dict(
        modelId=model_id,
        system=[{'text': system_prompt}],
        messages=[{'role': 'user', 'content': [{'text': document_text}]}],
        inferenceConfig={'maxTokens': 20, 'temperature': 0},
    )
    if guardrail_config:
        converse_kwargs['guardrailConfig'] = guardrail_config

    response = bedrock_runtime.converse(**converse_kwargs)

    raw_label = response['output']['message']['content'][0]['text'].strip().lower()

    if raw_label not in VALID_DOC_TYPES:
        raise ValueError(f'Classifier returned unknown doc type: {raw_label!r}')

    usage = response.get('usage', {})
    logger.info(json.dumps({'job_id': job_id, 'doc_type': raw_label, 'action': 'classified'}))

    return {
        'job_id': job_id,
        'bucket': bucket,
        'key': key,
        'doc_type': raw_label,
        'experiment_id': event.get('experiment_id'),
        'run_number': event.get('run_number'),
        'extractor_model_id': event.get('extractor_model_id'),
        'temperature': event.get('temperature'),
        'validate': event.get('validate', False),
        'usage_stats': {
            'classifier': {
                'model': model_id,
                'prompt_arn': prompt_arn,
                'prompt_version': prompt_version,
                'guardrail_id': guardrail_id,
                'guardrail_version': guardrail_version,
                'input_tokens': usage.get('inputTokens', 0),
                'output_tokens': usage.get('outputTokens', 0),
            },
        },
    }
