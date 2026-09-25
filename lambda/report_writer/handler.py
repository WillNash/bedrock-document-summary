"""
Step Functions task — WriteReport.

Assembles the full structured comparison report from accumulated state,
writes it to S3, and marks the experiment COMPLETED in DynamoDB.

Input:  accumulated Step Functions state
Output: {"experiment_id": "...", "report_prefix": "experiments/.../report/"}
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    experiment_id = event['experiment_id']
    summaries_bucket = event['summaries_bucket']
    report_prefix = f'experiments/{experiment_id}/report'
    completed_at = datetime.now(timezone.utc).isoformat()

    variance_results = event.get('variance_results') or {}
    comparison_report = {
        'experiment_id': experiment_id,
        'completed_at': completed_at,
        'doc_type': event.get('doc_type'),
        'successful_n': event.get('successful_n', 0),
        'validate': bool(event.get('config', {}).get('validate', False)),
        'config': event.get('config', {}),
        'variance_results': variance_results,
        'gold_results': event.get('gold_results'),
    }

    s3_client.put_object(
        Bucket=summaries_bucket,
        Key=f'{report_prefix}/comparison.json',
        Body=json.dumps(comparison_report, indent=2).encode('utf-8'),
        ContentType='application/json',
    )

    embeddings_doc = {
        'embedding_model': variance_results.get('embedding_model'),
        'embedding_dimensions': variance_results.get('embedding_dimensions'),
        'normalize': variance_results.get('embedding_normalize'),
        'run_references': [
            {'run_number': m['run_number'], 'summary_key': m['summary_key']}
            for m in event.get('run_manifests', [])
        ],
        'gold_key': event.get('gold_key'),
    }
    s3_client.put_object(
        Bucket=summaries_bucket,
        Key=f'experiments/{experiment_id}/embeddings/embeddings.json',
        Body=json.dumps(embeddings_doc, indent=2).encode('utf-8'),
        ContentType='application/json',
    )

    narrative_md = event.get('report', {}).get('narrative_md', '')
    s3_client.put_object(
        Bucket=summaries_bucket,
        Key=f'{report_prefix}/narrative.md',
        Body=narrative_md.encode('utf-8'),
        ContentType='text/markdown; charset=utf-8',
    )

    experiments_table = dynamodb.Table(os.environ['EXPERIMENTS_TABLE'])
    experiments_table.update_item(
        Key={'experiment_id': experiment_id},
        UpdateExpression='SET #s = :s, completed_at = :ca',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={
            ':s': 'COMPLETED',
            ':ca': completed_at,
        },
    )

    logger.info(json.dumps({
        'experiment_id': experiment_id,
        'action': 'report_written',
        'report_prefix': report_prefix,
    }))

    return {
        'experiment_id': experiment_id,
        'report_prefix': f'{report_prefix}/',
    }
