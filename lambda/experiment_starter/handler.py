"""
POST /experiments — register an experiment and kick off N pipeline runs.

The source document (already in the uploads bucket) is copied N times under
new job IDs. Each copy triggers an S3 ObjectCreated event → pipeline_starter →
the existing summarisation state machine. pipeline_starter reads experiment_id
and run_number from the jobs table to include them in the pipeline execution.

Request body:
{
  "experiment_id": "variance-test-001",   // unique, used as S3 prefix and SM name
  "expected_n": 10,                        // number of runs
  "source_document_key": "uploads/job-xyz/report.txt",
  "gold_text": "optional reference summary",
  "config": {"description": "..."}        // arbitrary metadata stored with experiment
}

Response: {"experiment_id": "...", "job_ids": [...], "expected_n": 10}
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

MAX_RUNS = 100


def _ok(body):
    return {'statusCode': 200, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps(body)}


def _err(status, message):
    return {'statusCode': status, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps({'error': message})}


def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body') or '{}')
    except (json.JSONDecodeError, TypeError):
        return _err(400, 'Invalid JSON body')

    experiment_id = body.get('experiment_id', '').strip()
    expected_n = body.get('expected_n')
    source_document_key = body.get('source_document_key', '').strip()
    gold_text = body.get('gold_text')
    config = body.get('config') or {}
    extractor_model_id = config.get('extractor_model_id') or None
    raw_temp = config.get('temperature')
    temperature = float(raw_temp) if raw_temp is not None else None

    if not experiment_id:
        return _err(400, 'experiment_id is required')
    if not isinstance(expected_n, int) or expected_n < 2 or expected_n > MAX_RUNS:
        return _err(400, f'expected_n must be an integer between 2 and {MAX_RUNS}')
    if not source_document_key:
        return _err(400, 'source_document_key is required')

    upload_bucket = os.environ['UPLOAD_BUCKET']
    summaries_bucket = os.environ['SUMMARIES_BUCKET']
    jobs_table_name = os.environ['JOBS_TABLE']
    experiments_table_name = os.environ['EXPERIMENTS_TABLE']

    # Verify source document exists before creating anything
    try:
        s3_client.head_object(Bucket=upload_bucket, Key=source_document_key)
    except ClientError as e:
        if e.response['Error']['Code'] in ('404', 'NoSuchKey'):
            return _err(404, f'source_document_key not found: {source_document_key}')
        raise

    created_at = datetime.now(timezone.utc).isoformat()
    source_filename = source_document_key.split('/')[-1]

    gold_key = None
    if gold_text:
        gold_key = f'experiments/{experiment_id}/gold.txt'
        s3_client.put_object(
            Bucket=summaries_bucket,
            Key=gold_key,
            Body=gold_text.encode('utf-8'),
            ContentType='text/plain; charset=utf-8',
        )

    experiment_config = {
        **config,
        'source_document_key': source_document_key,
        'gold_key': gold_key,
    }
    if 'temperature' in experiment_config:
        experiment_config['temperature'] = Decimal(str(experiment_config['temperature']))

    s3_client.put_object(
        Bucket=summaries_bucket,
        Key=f'experiments/{experiment_id}/config.json',
        Body=json.dumps({
            'experiment_id': experiment_id,
            'expected_n': expected_n,
            'config': experiment_config,
            'created_at': created_at,
        }).encode('utf-8'),
        ContentType='application/json',
    )

    experiments_table = dynamodb.Table(experiments_table_name)
    experiments_table.put_item(Item={
        'experiment_id': experiment_id,
        'expected_n': Decimal(str(expected_n)),
        'completed_n': Decimal('0'),
        'successful_n': Decimal('0'),
        'failed_n': Decimal('0'),
        'status': 'PENDING',
        'config': experiment_config,
        'created_at': created_at,
    })

    jobs_table = dynamodb.Table(jobs_table_name)
    job_ids = []

    for run_number in range(1, expected_n + 1):
        job_id = str(uuid.uuid4())
        copy_key = f'uploads/{job_id}/{source_filename}'

        job_item = {
            'job_id': job_id,
            'experiment_id': experiment_id,
            'run_number': Decimal(str(run_number)),
            'status': 'PENDING',
            'created_at': created_at,
            'user_id': 'experiment',
        }
        if extractor_model_id:
            job_item['extractor_model_id'] = extractor_model_id
        if temperature is not None:
            job_item['temperature'] = Decimal(str(temperature))
        jobs_table.put_item(Item=job_item)

        # Copy triggers S3 ObjectCreated → pipeline_starter → pipeline SM
        s3_client.copy_object(
            CopySource={'Bucket': upload_bucket, 'Key': source_document_key},
            Bucket=upload_bucket,
            Key=copy_key,
        )

        job_ids.append(job_id)
        logger.info(json.dumps({
            'experiment_id': experiment_id,
            'run_number': run_number,
            'job_id': job_id,
            'action': 'run_started',
        }))

    logger.info(json.dumps({
        'experiment_id': experiment_id,
        'expected_n': expected_n,
        'action': 'experiment_created',
    }))

    return _ok({
        'experiment_id': experiment_id,
        'job_ids': job_ids,
        'expected_n': expected_n,
    })
