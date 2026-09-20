import boto3
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TEMPLATE_DIR = Path(__file__).parent / 'templates'

TEMPLATE_FILES = {
    'lab_result': 'lab_result.j2',
    'doctors_notes': 'doctors_notes.j2',
    'injury_doc': 'injury_doc.j2',
    'visit_assessment': 'visit_assessment.j2',
    'psych_eval': 'psych_eval.j2',
}

# Autoescaping is intentionally disabled — all templates render plain text,
# not HTML. If an HTML template is ever added, create a separate Environment
# with autoescape=select_autoescape(['html']) rather than enabling it here.
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape([]),
    trim_blocks=True,
    lstrip_blocks=True,
)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    job_id = event['job_id']
    doc_type = event['doc_type']
    validated_data = event['validated_data']

    template = jinja_env.get_template(TEMPLATE_FILES[doc_type])
    summary_text = template.render(**validated_data)

    summaries_bucket = os.environ['SUMMARIES_BUCKET']
    summary_key = f'summaries/{job_id}/summary.txt'

    s3_client.put_object(
        Bucket=summaries_bucket,
        Key=summary_key,
        Body=summary_text.encode('utf-8'),
        ContentType='text/plain; charset=utf-8',
    )

    s3_client.put_object(
        Bucket=summaries_bucket,
        Key=f'summaries/{job_id}/usage.json',
        Body=json.dumps(event.get('usage_stats', {})).encode('utf-8'),
        ContentType='application/json',
    )

    completed_at = datetime.now(timezone.utc).isoformat()
    table = dynamodb.Table(os.environ['JOBS_TABLE'])
    table.update_item(
        Key={'job_id': job_id},
        UpdateExpression='SET #s = :s, doc_type = :dt, completed_at = :ca',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={
            ':s': 'COMPLETED',
            ':dt': doc_type,
            ':ca': completed_at,
        },
    )

    logger.info(json.dumps({'job_id': job_id, 'doc_type': doc_type, 'action': 'rendered', 'summary_key': summary_key}))

    return {
        'job_id': job_id,
        'summary_key': summary_key,
    }
