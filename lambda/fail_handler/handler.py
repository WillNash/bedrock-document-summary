import boto3
import contextlib
import json
import logging
import os
from decimal import Decimal
from typing import Final

from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
sfn_client = boto3.client('stepfunctions')

ERROR_MESSAGE_MAX_LEN: Final = 1000


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

    experiment_id = event.get('experiment_id')
    if experiment_id:
        summaries_bucket = os.environ.get('SUMMARIES_BUCKET', '')
        experiments_table = dynamodb.Table(os.environ['EXPERIMENTS_TABLE'])
        response = experiments_table.update_item(
            Key={'experiment_id': experiment_id},
            UpdateExpression='ADD completed_n :one, failed_n :one',
            ExpressionAttributeValues={':one': Decimal('1')},
            ReturnValues='ALL_NEW',
        )
        attrs = response['Attributes']
        completed_n = int(attrs['completed_n'])
        expected_n = int(attrs['expected_n'])
        successful_n = int(attrs.get('successful_n', 0))

        logger.info(json.dumps({
            'job_id': job_id,
            'experiment_id': experiment_id,
            'action': 'experiment_run_failed',
            'completed_n': completed_n,
            'expected_n': expected_n,
        }))

        if completed_n >= expected_n:
            _maybe_start_comparison(experiment_id, summaries_bucket, expected_n, successful_n)

    return {'job_id': job_id, 'status': 'FAILED'}
