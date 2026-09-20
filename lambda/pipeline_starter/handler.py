import boto3
import json
import logging
import os

from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sfn_client = boto3.client('stepfunctions')
dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        # Key pattern: uploads/{job_id}/{filename}
        parts = key.split('/')
        if len(parts) < 3 or parts[0] != 'uploads':
            logger.warning(json.dumps({'action': 'skip_unexpected_key', 'key': key}))
            continue

        job_id = parts[1]
        state_machine_arn = os.environ['STATE_MACHINE_ARN']
        jobs_table = os.environ['JOBS_TABLE']

        execution_input = json.dumps({
            'job_id': job_id,
            'bucket': bucket,
            'key': key,
        })

        try:
            sfn_client.start_execution(
                stateMachineArn=state_machine_arn,
                name=job_id,
                input=execution_input,
            )
            logger.info(json.dumps({'job_id': job_id, 'action': 'execution_started', 'key': key}))
        except ClientError as e:
            if e.response['Error']['Code'] == 'ExecutionAlreadyExists':
                # S3 event retry — execution is already running. Fall through
                # to the DynamoDB update below in case the first delivery's
                # write failed before completing.
                logger.info(json.dumps({'job_id': job_id, 'action': 'execution_already_exists'}))
            else:
                raise

        # Update status to RUNNING. Use a condition so we never overwrite
        # a terminal status (COMPLETED/FAILED) if the pipeline has already
        # finished by the time a retry event arrives.
        table = dynamodb.Table(jobs_table)
        try:
            table.update_item(
                Key={'job_id': job_id},
                UpdateExpression='SET #s = :running',
                ConditionExpression='#s = :pending',
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':running': 'RUNNING', ':pending': 'PENDING'},
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                # Status has already been updated past PENDING — nothing to do.
                logger.info(json.dumps({'job_id': job_id, 'action': 'status_already_progressed'}))
            else:
                raise

    return {'statusCode': 200}
