import boto3
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SCHEMA_DIR = Path(__file__).parent / 'schemas'

SCHEMA_FILES = {
    'lab_result': 'lab_result_schema.json',
    'doctors_notes': 'doctors_notes_schema.json',
    'injury_doc': 'injury_doc_schema.json',
    'visit_assessment': 'visit_assessment_schema.json',
    'psych_eval': 'psych_eval_schema.json',
}

bedrock_agent = boto3.client('bedrock-agent')
bedrock_runtime = boto3.client('bedrock-runtime')
s3_client = boto3.client('s3')

# Parsed once per Lambda execution context (cold start), not per invocation.
_PROMPT_ARNS: dict[str, str] | None = None
_PROMPT_VERSIONS: dict[str, str] | None = None


def _get_prompt_config() -> tuple[dict[str, str], dict[str, str]]:
    global _PROMPT_ARNS, _PROMPT_VERSIONS
    if _PROMPT_ARNS is None:
        _PROMPT_ARNS = json.loads(os.environ['PROMPT_ARNS_JSON'])
        _PROMPT_VERSIONS = json.loads(os.environ['PROMPT_VERSIONS_JSON'])
    return _PROMPT_ARNS, _PROMPT_VERSIONS


def _get_prompt_text(doc_type):
    arns, versions = _get_prompt_config()
    prompt_arn = arns[doc_type]
    prompt_version = versions[doc_type]
    response = bedrock_agent.get_prompt(
        promptIdentifier=prompt_arn,
        promptVersion=prompt_version,
    )
    variants = response.get('variants', [])
    if not variants:
        raise ValueError(f'No variants found in prompt for doc_type={doc_type}')
    content = variants[0].get('templateConfiguration', {}).get('text', {}).get('text', '')
    if not content:
        raise ValueError(f'Empty prompt text for doc_type={doc_type}')
    return content


def _load_schema(doc_type):
    schema_file = SCHEMA_DIR / SCHEMA_FILES[doc_type]
    with open(schema_file) as f:
        return json.load(f)


def lambda_handler(event, context):
    job_id = event['job_id']
    bucket = event['bucket']
    key = event['key']
    doc_type = event['doc_type']

    s3_response = s3_client.get_object(Bucket=bucket, Key=key)
    document_text = s3_response['Body'].read().decode('utf-8', errors='replace')

    # Mirror the validator's key-presence logic: absent → default, '' → free-form, str → custom
    if 'custom_schema' not in event:
        schema = _load_schema(doc_type)
    elif event['custom_schema']:
        schema = json.loads(event['custom_schema'])
    else:
        schema = None  # '' → free-form, no tool/schema constraint

    custom_prompt = event.get('custom_prompt')
    if custom_prompt:
        system_prompt = custom_prompt
        prompt_arn = ''
        prompt_version = ''
    else:
        system_prompt = _get_prompt_text(doc_type)
        arns, versions = _get_prompt_config()
        prompt_arn = arns[doc_type]
        prompt_version = versions[doc_type]

    model_id = event.get('extractor_model_id') or os.environ['BEDROCK_MODEL_ID']
    temperature = float(event['temperature']) if event.get('temperature') is not None else 0

    guardrail_config = {}
    if os.environ.get('GUARDRAIL_ID') and os.environ.get('GUARDRAIL_VERSION'):
        guardrail_config = {
            'guardrailIdentifier': os.environ['GUARDRAIL_ID'],
            'guardrailVersion': os.environ['GUARDRAIL_VERSION'],
            'trace': 'disabled',
        }

    if schema is not None:
        tool_def = {
            'toolSpec': {
                'name': 'extract_document',
                'description': f'Extract structured data from a {doc_type} medical document.',
                'inputSchema': {'json': schema},
            }
        }
        converse_kwargs = dict(
            modelId=model_id,
            system=[{'text': system_prompt}],
            messages=[{'role': 'user', 'content': [{'text': document_text}]}],
            toolConfig={
                'tools': [tool_def],
                'toolChoice': {'tool': {'name': 'extract_document'}},
            },
            inferenceConfig={'maxTokens': 4096, 'temperature': temperature},
        )
        if guardrail_config:
            converse_kwargs['guardrailConfig'] = guardrail_config
        response = bedrock_runtime.converse(**converse_kwargs)
        content_blocks = response['output']['message']['content']
        tool_use_block = next(
            (block['toolUse'] for block in content_blocks if 'toolUse' in block), None
        )
        if tool_use_block is None:
            raise ValueError('Bedrock response did not contain a toolUse block')
        extracted_data = tool_use_block['input']
    else:
        # Free-form: no tool constraint, raw text response becomes the summary
        converse_kwargs = dict(
            modelId=model_id,
            system=[{'text': system_prompt}],
            messages=[{'role': 'user', 'content': [{'text': document_text}]}],
            inferenceConfig={'maxTokens': 4096, 'temperature': temperature},
        )
        if guardrail_config:
            converse_kwargs['guardrailConfig'] = guardrail_config
        response = bedrock_runtime.converse(**converse_kwargs)
        extracted_data = response['output']['message']['content'][0]['text']

    usage = response.get('usage', {})
    logger.info(json.dumps({'job_id': job_id, 'doc_type': doc_type, 'action': 'extracted'}))

    result = {
        'job_id': job_id,
        'bucket': bucket,
        'key': key,
        'doc_type': doc_type,
        'experiment_id': event.get('experiment_id'),
        'run_number': event.get('run_number'),
        'extractor_model_id': event.get('extractor_model_id'),
        'temperature': event.get('temperature'),
        'validate': event.get('validate', False),
        'extracted_data': extracted_data,
        'usage_stats': {
            **event.get('usage_stats', {}),
            'extractor': {
                'model': model_id,
                'prompt_arn': prompt_arn,
                'prompt_version': prompt_version,
                'input_tokens': usage.get('inputTokens', 0),
                'output_tokens': usage.get('outputTokens', 0),
            },
        },
    }
    if event.get('custom_prompt'):
        result['custom_prompt'] = event['custom_prompt']
    if 'custom_schema' in event:
        result['custom_schema'] = event['custom_schema']
    return result
