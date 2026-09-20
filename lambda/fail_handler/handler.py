import boto3
import contextlib
import json
import logging
import os
from typing import Final

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')

ERROR_MESSAGE_MAX_LEN: Final = 1000


def lambda_handler(event, context):
    # All Catch blocks use ResultPath: "$.error", which merges the error object into
    # the state input under event['error'] while preserving all original fields at the
    # top level (including job_id, bucket, key, doc_type from prior states).
    job_id = event['job_id']
    error_info = event.get('error', {})
    cause = error_info.get('Cause', 'Unknown error')

    # Cause is often a JSON-encoded string with errorMessage inside
    error_message = cause
    with contextlib.suppress(json.JSONDecodeError, TypeError):
        cause_obj = json.loads(cause)
        if isinstance(cause_obj, dict):
            error_message = cause_obj.get('errorMessage', cause)

    table = dynamodb.Table(os.environ['JOBS_TABLE'])
    table.update_item(
        Key={'job_id': job_id},
        UpdateExpression='SET #s = :s, error_message = :e',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={
            ':s': 'FAILED',
            ':e': str(error_message)[:ERROR_MESSAGE_MAX_LEN],
        },
    )

    logger.info(json.dumps({'job_id': job_id, 'status': 'FAILED', 'action': 'failure_recorded'}))
    return {'job_id': job_id, 'status': 'FAILED'}
