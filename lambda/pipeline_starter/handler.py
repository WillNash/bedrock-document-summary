import boto3
import json
import logging
import os

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
            logger.warning({'action': 'skip_unexpected_key', 'key': key})
            continue

        job_id = parts[1]
        state_machine_arn = os.environ['STATE_MACHINE_ARN']
        jobs_table = os.environ['JOBS_TABLE']

        execution_input = json.dumps({
            'job_id': job_id,
            'bucket': bucket,
            'key': key,
        })

        sfn_client.start_execution(
            stateMachineArn=state_machine_arn,
            name=job_id,
            input=execution_input,
        )

        table = dynamodb.Table(jobs_table)
        table.update_item(
            Key={'job_id': job_id},
            UpdateExpression='SET #s = :s',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': 'RUNNING'},
        )

        logger.info({'job_id': job_id, 'action': 'execution_started', 'key': key})

    return {'statusCode': 200}
