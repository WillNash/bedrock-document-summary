"""
Step Functions task — CollectSummaries.

Lists the completed run directories for an experiment and returns a manifest
of S3 keys. Summary text is never loaded here; downstream scorers read from
S3 directly to avoid passing PHI through the Step Functions payload.

Input:  {"experiment_id": "...", "summaries_bucket": "...", "successful_n": N}
Output: {
  "experiment_id": "...",
  "summaries_bucket": "...",
  "run_manifests": [{"run_number": 1, "summary_key": "...", "metadata_key": "..."}],
  "config": {...},
  "has_gold": true,
  "gold_key": "experiments/.../gold.txt",
  "successful_n": N,
  "doc_type": "lab_result"
}
"""

import json
import logging
import os
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')


def _list_successful_runs(bucket, experiment_id):
    prefix = f'experiments/{experiment_id}/runs/'
    paginator = s3_client.get_paginator('list_objects_v2')
    run_manifests = []

    seen_runs = set()
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            key = obj['Key']
            # Key pattern: experiments/{id}/runs/{run_number}/summary.txt
            parts = key[len(prefix):].split('/')
            if len(parts) == 2 and parts[1] == 'summary.txt':
                run_number_str = parts[0]
                if not run_number_str.isdigit():
                    continue
                run_number = int(run_number_str)
                if run_number not in seen_runs:
                    seen_runs.add(run_number)
                    run_manifests.append({
                        'run_number': run_number,
                        'summary_key': f'{prefix}{run_number}/summary.txt',
                        'metadata_key': f'{prefix}{run_number}/metadata.json',
                    })

    return sorted(run_manifests, key=lambda r: r['run_number'])


def _read_doc_type_from_first_run(bucket, run_manifests):
    if not run_manifests:
        return None
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=run_manifests[0]['metadata_key'])
        metadata = json.loads(obj['Body'].read())
        return metadata.get('doc_type')
    except Exception:
        return None


def lambda_handler(event, context):
    experiment_id = event['experiment_id']
    summaries_bucket = event['summaries_bucket']
    successful_n = event.get('successful_n', 0)

    experiments_table = dynamodb.Table(os.environ['EXPERIMENTS_TABLE'])
    response = experiments_table.get_item(Key={'experiment_id': experiment_id})
    item = response.get('Item', {})
    config = item.get('config', {})
    gold_key = config.get('gold_key')
    has_gold = bool(gold_key)

    run_manifests = _list_successful_runs(summaries_bucket, experiment_id)
    doc_type = _read_doc_type_from_first_run(summaries_bucket, run_manifests)

    logger.info(json.dumps({
        'experiment_id': experiment_id,
        'action': 'summaries_collected',
        'run_count': len(run_manifests),
        'has_gold': has_gold,
    }))

    return {
        'experiment_id': experiment_id,
        'summaries_bucket': summaries_bucket,
        'run_manifests': run_manifests,
        'config': {k: str(v) if isinstance(v, Decimal) else v for k, v in config.items()},
        'has_gold': has_gold,
        'gold_key': gold_key,
        'successful_n': len(run_manifests),
        'doc_type': doc_type,
    }
