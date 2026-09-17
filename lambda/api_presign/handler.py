import boto3
import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta

import boto3.session
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client(
    's3',
    config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'})
)


def _check_and_increment_quota(table, user_id, limit):
    """Atomically increment today's upload counter. Returns False if limit reached."""
    now = datetime.now(timezone.utc)
    today = now.strftime('%Y-%m-%d')
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        table.update_item(
            Key={'job_id': f'quota#{user_id}#{today}'},
            UpdateExpression='ADD #c :one SET #ttl = :ttl',
            ConditionExpression='attribute_not_exists(#c) OR #c < :limit',
            ExpressionAttributeNames={'#c': 'count', '#ttl': 'ttl'},
            ExpressionAttributeValues={
                ':one': 1,
                ':limit': limit,
                ':ttl': int(midnight.timestamp()),
            },
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            return False
        raise
    return True


def lambda_handler(event, context):
    # API Gateway v2 HTTP API JWT authorizer places claims here
    claims = event['requestContext']['authorizer']['jwt']['claims']
    user_id = claims['sub']

    body = json.loads(event.get('body') or '{}')
    filename = body.get('filename', 'document.txt')
    # Sanitize filename: strip path components
    filename = os.path.basename(filename) or 'document.txt'

    upload_bucket = os.environ['UPLOAD_BUCKET']
    jobs_table = os.environ['JOBS_TABLE']
    max_size = int(os.environ.get('UPLOAD_MAX_SIZE_BYTES', '10485760'))
    daily_limit = int(os.environ.get('DAILY_UPLOAD_LIMIT', '20'))

    table = dynamodb.Table(jobs_table)

    if not _check_and_increment_quota(table, user_id, daily_limit):
        logger.warning({'user_id': user_id, 'action': 'quota_exceeded', 'limit': daily_limit})
        return {
            'statusCode': 429,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Daily upload limit reached. Try again tomorrow.'}),
        }

    job_id = str(uuid.uuid4())

    # Write PENDING record before returning the presigned URL
    table.put_item(Item={
        'job_id': job_id,
        'user_id': user_id,
        'status': 'PENDING',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'filename': filename,
    })

    s3_key = f'uploads/{job_id}/{filename}'

    # Use starts-with condition to allow any content type.
    # This prevents 403s when browsers auto-detect types (e.g. application/pdf vs application/octet-stream).
    presigned = s3_client.generate_presigned_post(
        Bucket=upload_bucket,
        Key=s3_key,
        Fields={'Content-Type': 'application/octet-stream'},
        Conditions=[
            ['starts-with', '$Content-Type', ''],
            ['content-length-range', 1, max_size],
        ],
        ExpiresIn=300,
    )

    logger.info({'job_id': job_id, 'user_id': user_id, 'action': 'presign_created'})

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps({
            'job_id': job_id,
            'presign_url': presigned['url'],
            'presign_fields': presigned['fields'],
        }),
    }
