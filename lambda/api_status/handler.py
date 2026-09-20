import boto3
import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    claims = event['requestContext']['authorizer']['jwt']['claims']
    user_id = claims['sub']

    job_id = event['pathParameters']['jobId']

    table = dynamodb.Table(os.environ['JOBS_TABLE'])
    response = table.get_item(Key={'job_id': job_id})
    item = response.get('Item')

    # Return 404 for both missing jobs and jobs owned by another user —
    # a 403 would confirm the job exists to an unauthorised caller.
    if not item or item.get('user_id') != user_id:
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Job not found'}),
        }

    optional_keys = ('doc_type', 'error_message', 'completed_at')
    payload = {
        'job_id': item['job_id'],
        'status': item['status'],
        **{k: item[k] for k in optional_keys if k in item},
    }

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(payload),
    }
