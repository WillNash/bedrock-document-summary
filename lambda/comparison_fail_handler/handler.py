"""
Step Functions Catch target — MarkComparisonFailed.

Updates the experiment status to COMPARISON_FAILED and logs the error
so failures in the comparison SM are visible in DynamoDB.
"""

import contextlib
import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')

ERROR_MESSAGE_MAX_LEN = 1000


def lambda_handler(event, context):
    experiment_id = event.get('experiment_id', 'unknown')
    error_info = event.get('error', {})
    cause = error_info.get('Cause', 'Unknown error')

    error_message = cause
    with contextlib.suppress(json.JSONDecodeError, TypeError):
        cause_obj = json.loads(cause)
        if isinstance(cause_obj, dict):
            error_message = cause_obj.get('errorMessage', cause)

    experiments_table = dynamodb.Table(os.environ['EXPERIMENTS_TABLE'])
    experiments_table.update_item(
        Key={'experiment_id': experiment_id},
        UpdateExpression='SET #s = :s, error_message = :e',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={
            ':s': 'COMPARISON_FAILED',
            ':e': str(error_message)[:ERROR_MESSAGE_MAX_LEN],
        },
    )

    logger.info(json.dumps({
        'experiment_id': experiment_id,
        'status': 'COMPARISON_FAILED',
        'action': 'comparison_failure_recorded',
    }))

    return {'experiment_id': experiment_id, 'status': 'COMPARISON_FAILED'}
