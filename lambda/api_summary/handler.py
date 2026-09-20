import boto3
import json
import logging
import os

from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')


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

    if item['status'] != 'COMPLETED':
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Summary not yet available', 'status': item['status']}),
        }

    summaries_bucket = os.environ['SUMMARIES_BUCKET']
    summary_key = f'summaries/{job_id}/summary.txt'

    try:
        s3_response = s3_client.get_object(Bucket=summaries_bucket, Key=summary_key)
        summary_text = s3_response['Body'].read().decode('utf-8')
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            logger.error({'job_id': job_id, 'error': 'Summary file missing from S3'})
            return {
                'statusCode': 500,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Summary file not found'}),
            }
        raise

    usage_stats = {}
    try:
        usage_response = s3_client.get_object(Bucket=summaries_bucket, Key=f'summaries/{job_id}/usage.json')
        usage_stats = json.loads(usage_response['Body'].read().decode('utf-8'))
    except ClientError as e:
        if e.response['Error']['Code'] != 'NoSuchKey':
            raise

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps({
            'job_id': job_id,
            'doc_type': item.get('doc_type', 'unknown'),
            'summary': summary_text,
            'usage': usage_stats,
        }),
    }
