import boto3
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from botocore.exceptions import ClientError

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

# Autoescaping is intentionally disabled — all templates render plain text,
# not HTML. If an HTML template is ever added, create a separate Environment
# with autoescape=select_autoescape(['html']) rather than enabling it here.
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape([]),
    trim_blocks=True,
    lstrip_blocks=True,
)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
sfn_client = boto3.client('stepfunctions')


def _parse_claim_output(event):
    raw = event.get('claim_validation', {}).get('output')
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _copy_claim_artifacts(job_id, run_prefix, summaries_bucket):
    artifacts = [
        (f'summaries/{job_id}/pre_render.txt',        f'{run_prefix}/pre_render.txt',        'text/plain; charset=utf-8'),
        (f'summaries/{job_id}/validated_summary.txt', f'{run_prefix}/validated_summary.txt', 'text/plain; charset=utf-8'),
        (f'summaries/{job_id}/claims.json',           f'{run_prefix}/claims.json',           'application/json'),
        (f'summaries/{job_id}/triage.json',           f'{run_prefix}/triage.json',           'application/json'),
        (f'summaries/{job_id}/verdicts.json',         f'{run_prefix}/verdicts.json',         'application/json'),
    ]
    for src_key, dst_key, content_type in artifacts:
        obj = s3_client.get_object(Bucket=summaries_bucket, Key=src_key)
        s3_client.put_object(
            Bucket=summaries_bucket,
            Key=dst_key,
            Body=obj['Body'].read(),
            ContentType=content_type,
        )


def _write_experiment_outputs(event, summary_text, summaries_bucket, completed_at):
    experiment_id = event['experiment_id']
    run_number = int(event['run_number'])
    job_id = event['job_id']
    run_prefix = f'experiments/{experiment_id}/runs/{run_number}'

    s3_client.put_object(
        Bucket=summaries_bucket,
        Key=f'{run_prefix}/summary.txt',
        Body=summary_text.encode('utf-8'),
        ContentType='text/plain; charset=utf-8',
    )

    s3_client.put_object(
        Bucket=summaries_bucket,
        Key=f'experiments/{experiment_id}/runs/{run_number}.json',
        Body=json.dumps({'completed_at': completed_at, 'job_id': job_id, 'doc_type': event['doc_type']}).encode('utf-8'),
        ContentType='application/json',
    )

    claim_validation = _parse_claim_output(event)
    if claim_validation:
        _copy_claim_artifacts(job_id, run_prefix, summaries_bucket)

    usage = event.get('usage_stats', {})
    classifier_stats = usage.get('classifier', {})
    extractor_stats = usage.get('extractor', {})

    metadata = {
        'experiment_id': experiment_id,
        'run_number': run_number,
        'job_id': job_id,
        'source_document_key': event['key'],
        'doc_type': event['doc_type'],
        'classification': {
            'model_id': classifier_stats.get('model', ''),
            'prompt_arn': classifier_stats.get('prompt_arn', ''),
            'prompt_version': classifier_stats.get('prompt_version', ''),
            'guardrail_id': classifier_stats.get('guardrail_id', ''),
            'guardrail_version': classifier_stats.get('guardrail_version', ''),
            'input_tokens': classifier_stats.get('input_tokens', 0),
            'output_tokens': classifier_stats.get('output_tokens', 0),
        },
        'extraction': {
            'model_id': extractor_stats.get('model', ''),
            'temperature': float(event['temperature']) if event.get('temperature') is not None else 0,
            'prompt_arn': extractor_stats.get('prompt_arn', ''),
            'prompt_version': extractor_stats.get('prompt_version', ''),
            'input_tokens': extractor_stats.get('input_tokens', 0),
            'output_tokens': extractor_stats.get('output_tokens', 0),
        },
        'timestamp': completed_at,
    }

    if claim_validation:
        metadata['claim_validation'] = {
            'stats': claim_validation.get('claim_stats', {}),
        }

    s3_client.put_object(
        Bucket=summaries_bucket,
        Key=f'{run_prefix}/metadata.json',
        Body=json.dumps(metadata).encode('utf-8'),
        ContentType='application/json',
    )

    logger.info(json.dumps({
        'job_id': event['job_id'],
        'experiment_id': experiment_id,
        'run_number': run_number,
        'action': 'experiment_run_written',
    }))


def _record_experiment_success(experiment_id, summaries_bucket):
    experiments_table = dynamodb.Table(os.environ['EXPERIMENTS_TABLE'])
    response = experiments_table.update_item(
        Key={'experiment_id': experiment_id},
        UpdateExpression='ADD completed_n :one, successful_n :one',
        ExpressionAttributeValues={':one': Decimal('1')},
        ReturnValues='ALL_NEW',
    )
    attrs = response['Attributes']
    completed_n = int(attrs['completed_n'])
    expected_n = int(attrs['expected_n'])
    successful_n = int(attrs.get('successful_n', 0))

    if completed_n >= expected_n:
        _maybe_start_comparison(experiment_id, summaries_bucket, expected_n, successful_n)


def _maybe_start_comparison(experiment_id, summaries_bucket, expected_n, successful_n):
    try:
        sfn_client.start_execution(
            stateMachineArn=os.environ['COMPARISON_SM_ARN'],
            name=experiment_id,
            input=json.dumps({
                'experiment_id': experiment_id,
                'summaries_bucket': summaries_bucket,
                'expected_n': expected_n,
                'successful_n': successful_n,
            }),
        )
        logger.info(json.dumps({
            'experiment_id': experiment_id,
            'action': 'comparison_sm_started',
            'successful_n': successful_n,
            'expected_n': expected_n,
        }))
    except ClientError as e:
        if e.response['Error']['Code'] == 'ExecutionAlreadyExists':
            logger.info(json.dumps({'experiment_id': experiment_id, 'action': 'comparison_already_started'}))
        else:
            raise


def lambda_handler(event, context):
    job_id = event['job_id']
    doc_type = event['doc_type']
    validated_data = event['validated_data']

    validated_summary_key = _parse_claim_output(event).get('validated_summary_key')
    if validated_summary_key:
        obj = s3_client.get_object(Bucket=os.environ['SUMMARIES_BUCKET'], Key=validated_summary_key)
        summary_text = obj['Body'].read().decode('utf-8')
    else:
        template = jinja_env.get_template(TEMPLATE_FILES[doc_type])
        summary_text = template.render(**validated_data)

    summaries_bucket = os.environ['SUMMARIES_BUCKET']
    summary_key = f'summaries/{job_id}/summary.txt'

    s3_client.put_object(
        Bucket=summaries_bucket,
        Key=summary_key,
        Body=summary_text.encode('utf-8'),
        ContentType='text/plain; charset=utf-8',
    )

    s3_client.put_object(
        Bucket=summaries_bucket,
        Key=f'summaries/{job_id}/usage.json',
        Body=json.dumps(event.get('usage_stats', {})).encode('utf-8'),
        ContentType='application/json',
    )

    completed_at = datetime.now(timezone.utc).isoformat()

    table = dynamodb.Table(os.environ['JOBS_TABLE'])
    table.update_item(
        Key={'job_id': job_id},
        UpdateExpression='SET #s = :s, doc_type = :dt, completed_at = :ca',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={
            ':s': 'COMPLETED',
            ':dt': doc_type,
            ':ca': completed_at,
        },
    )

    logger.info(json.dumps({'job_id': job_id, 'doc_type': doc_type, 'action': 'rendered', 'summary_key': summary_key}))

    experiment_id = event.get('experiment_id')
    if experiment_id:
        _write_experiment_outputs(event, summary_text, summaries_bucket, completed_at)
        _record_experiment_success(experiment_id, summaries_bucket)

    return {
        'job_id': job_id,
        'summary_key': summary_key,
    }
