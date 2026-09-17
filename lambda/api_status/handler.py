import boto3
import json
import logging
import os
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    job_id = event['pathParameters']['jobId']

    table = dynamodb.Table(os.environ['JOBS_TABLE'])
    response = table.get_item(Key={'job_id': job_id})
    item = response.get('Item')

    if not item:
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Job not found'}),
        }

    payload = {
        'job_id': item['job_id'],
        'status': item['status'],
    }
    if 'doc_type' in item:
        payload['doc_type'] = item['doc_type']
    if 'error_message' in item:
        payload['error_message'] = item['error_message']
    if 'completed_at' in item:
        payload['completed_at'] = item['completed_at']

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(payload),
    }
