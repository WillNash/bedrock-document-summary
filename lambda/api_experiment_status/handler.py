import boto3
import json
import logging
import os
from decimal import Decimal

from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')


def _dec(v):
    return int(v) if isinstance(v, Decimal) else v


def _read_s3_json(bucket, key):
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    return json.loads(obj['Body'].read())


def _read_s3_text(bucket, key):
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    return obj['Body'].read().decode('utf-8')


def lambda_handler(event, context):
    experiment_id = event['pathParameters']['experimentId']
    summaries_bucket = os.environ['SUMMARIES_BUCKET']

    table = dynamodb.Table(os.environ['EXPERIMENTS_TABLE'])
    response = table.get_item(Key={'experiment_id': experiment_id})
    item = response.get('Item')

    if not item:
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Experiment not found'}),
        }

    payload = {
        'experiment_id': experiment_id,
        'status': item['status'],
        'expected_n': _dec(item.get('expected_n')),
        'completed_n': _dec(item.get('completed_n', 0)),
        'successful_n': _dec(item.get('successful_n', 0)),
        'created_at': item.get('created_at'),
    }

    if 'completed_at' in item:
        payload['completed_at'] = item['completed_at']

    if 'error_message' in item:
        payload['error_message'] = item['error_message']

    if item['status'] == 'COMPLETED':
        report_prefix = f'experiments/{experiment_id}/report'
        try:
            payload['report'] = _read_s3_json(summaries_bucket, f'{report_prefix}/comparison.json')
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchKey':
                raise

        try:
            payload['narrative'] = _read_s3_text(summaries_bucket, f'{report_prefix}/narrative.md')
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchKey':
                raise

    logger.info(json.dumps({
        'experiment_id': experiment_id,
        'status': item['status'],
        'action': 'status_fetched',
    }))

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(payload),
    }
