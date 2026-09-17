import boto3
import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')


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
    except s3_client.exceptions.NoSuchKey:
        logger.error({'job_id': job_id, 'error': 'Summary file missing from S3'})
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Summary file not found'}),
        }

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps({
            'job_id': job_id,
            'doc_type': item.get('doc_type', 'unknown'),
            'summary': summary_text,
        }),
    }
