import json
import logging
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

    raw_custom_schema = event.get('custom_schema')
    if 'custom_schema' not in event:
        jsonschema.validate(instance=extracted_data, schema=_load_schema(doc_type))
    elif raw_custom_schema:
        jsonschema.validate(instance=extracted_data, schema=json.loads(raw_custom_schema))
    # else: custom_schema == '' → skip validation

    logger.info(json.dumps({'job_id': job_id, 'doc_type': doc_type, 'action': 'validated'}))

    result = {
        'job_id': job_id,
        'bucket': event['bucket'],
        'key': event['key'],
        'doc_type': doc_type,
        'experiment_id': event.get('experiment_id'),
        'run_number': event.get('run_number'),
        'extractor_model_id': event.get('extractor_model_id'),
        'temperature': event.get('temperature'),
        'validated_data': extracted_data,
        'validate': event.get('validate', False),
        'usage_stats': event.get('usage_stats', {}),
    }
    if 'custom_schema' in event:
        result['custom_schema'] = event['custom_schema']
    return result
