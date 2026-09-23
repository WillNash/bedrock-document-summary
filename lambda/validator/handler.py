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

    base_result = {
        'job_id': job_id,
        'bucket': event['bucket'],
        'key': event['key'],
        'doc_type': doc_type,
        'experiment_id': event.get('experiment_id'),
        'run_number': event.get('run_number'),
        'extractor_model_id': event.get('extractor_model_id'),
        'temperature': event.get('temperature'),
        'usage_stats': event.get('usage_stats', {}),
    }
    if 'custom_schema' in event:
        base_result['custom_schema'] = event['custom_schema']
    if event.get('custom_prompt'):
        base_result['custom_prompt'] = event['custom_prompt']

    if 'extracted_text' in event:
        # Free-form path: no schema validation
        logger.info(json.dumps({'job_id': job_id, 'action': 'validation_skipped_freeform'}))
        return {**base_result, 'extracted_text': event['extracted_text']}

    extracted_data = event['extracted_data']

    if 'custom_schema' in event and event['custom_schema']:
        schema = json.loads(event['custom_schema'])
    else:
        schema = _load_schema(doc_type)

    jsonschema.validate(instance=extracted_data, schema=schema)
    logger.info(json.dumps({'job_id': job_id, 'doc_type': doc_type, 'action': 'validated'}))

    return {**base_result, 'validated_data': extracted_data}
