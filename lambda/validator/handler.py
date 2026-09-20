import json
import logging
import os
from pathlib import Path

import jsonschema

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SCHEMA_DIR = Path(__file__).parent / 'schemas'

SCHEMA_FILES = {
    'lab_result': 'lab_result_schema.json',
    'doctors_notes': 'doctors_notes_schema.json',
    'injury_doc': 'injury_doc_schema.json',
    'visit_assessment': 'visit_assessment_schema.json',
    'psych_eval': 'psych_eval_schema.json',
}


def _load_schema(doc_type):
    schema_file = SCHEMA_DIR / SCHEMA_FILES[doc_type]
    with open(schema_file) as f:
        return json.load(f)


def lambda_handler(event, context):
    job_id = event['job_id']
    doc_type = event['doc_type']
    extracted_data = event['extracted_data']

    schema = _load_schema(doc_type)
    jsonschema.validate(instance=extracted_data, schema=schema)

    logger.info(json.dumps({'job_id': job_id, 'doc_type': doc_type, 'action': 'validated'}))

    return {
        'job_id': job_id,
        'bucket': event['bucket'],
        'key': event['key'],
        'doc_type': doc_type,
        'validated_data': extracted_data,
        'usage_stats': event.get('usage_stats', {}),
    }
