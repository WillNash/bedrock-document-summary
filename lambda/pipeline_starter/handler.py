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
        jobs_table_name = os.environ['JOBS_TABLE']

        # One extra read to fetch experiment context — keeps the S3 key pattern clean.
        # experiment_id and run_number are written by experiment_starter at job creation.
        jobs_table = dynamodb.Table(jobs_table_name)
        job_response = jobs_table.get_item(
            Key={'job_id': job_id},
            ProjectionExpression='experiment_id, run_number, extractor_model_id, temperature, #validate',
            ExpressionAttributeNames={'#validate': 'validate'},
            ConsistentRead=True,
        )
        job_item = job_response.get('Item', {})
        experiment_id = job_item.get('experiment_id')
        run_number = job_item.get('run_number')
        extractor_model_id = job_item.get('extractor_model_id')
        temperature = job_item.get('temperature')

        execution_input = {
            'job_id': job_id,
            'bucket': bucket,
            'key': key,
        }
        if experiment_id:
            execution_input['experiment_id'] = experiment_id
            execution_input['run_number'] = int(run_number)
        if extractor_model_id:
            execution_input['extractor_model_id'] = extractor_model_id
        if temperature is not None:
            execution_input['temperature'] = float(temperature)
        if job_item.get('validate'):
            execution_input['validate'] = True

        try:
            sfn_client.start_execution(
                stateMachineArn=state_machine_arn,
                name=job_id,
                input=json.dumps(execution_input),
            )
            logger.info(json.dumps({'job_id': job_id, 'action': 'execution_started', 'key': key}))
        except ClientError as e:
            if e.response['Error']['Code'] == 'ExecutionAlreadyExists':
                logger.info(json.dumps({'job_id': job_id, 'action': 'execution_already_exists'}))
            else:
                raise

        # Update status to RUNNING. Condition prevents overwriting a terminal status
        # if a retry event arrives after the pipeline has already finished.
        try:
            jobs_table.update_item(
                Key={'job_id': job_id},
                UpdateExpression='SET #s = :running',
                ConditionExpression='#s = :pending',
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':running': 'RUNNING', ':pending': 'PENDING'},
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                logger.info(json.dumps({'job_id': job_id, 'action': 'status_already_progressed'}))
            else:
                raise

    return {'statusCode': 200}
