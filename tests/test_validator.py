"""Unit tests for the validator Lambda handler."""
import sys
from pathlib import Path
from unittest import mock

import jsonschema
import pytest

VALIDATOR_DIR = Path(__file__).parent.parent / 'lambda' / 'validator'
SCHEMAS_DIR = Path(__file__).parent.parent / 'schemas'
sys.path.insert(0, str(VALIDATOR_DIR))

with mock.patch.dict('os.environ', {'JOBS_TABLE': 'test-jobs'}):
    import handler as validator_handler


@pytest.fixture(autouse=True)
def patch_schema_dir(monkeypatch):
    monkeypatch.setattr(validator_handler, 'SCHEMA_DIR', SCHEMAS_DIR)


VALID_LAB_RESULT_EVENT = {
    'job_id': 'job-123',
    'bucket': 'test-bucket',
    'key': 'uploads/job-123/test.txt',
    'doc_type': 'lab_result',
    'extracted_data': {
        'patient_id': 'P-001',
        'test_date': '2025-01-15',
        'ordering_provider': 'Dr. Smith',
        'test_panels': [
            {
                'panel_name': 'CBC',
                'results': [
                    {'name': 'Hgb', 'value': '13.5', 'unit': 'g/dL', 'reference_range': '12-16', 'flag': None},
                ],
            }
        ],
        'interpretation': None,
        'notes': None,
    },
}

VALID_INJURY_DOC_EVENT = {
    'job_id': 'job-456',
    'bucket': 'test-bucket',
    'key': 'uploads/job-456/injury.txt',
    'doc_type': 'injury_doc',
    'extracted_data': {
        'patient_id': 'P-002',
        'incident_date': '2025-03-10',
        'body_regions_affected': ['lower back'],
        'mechanism_of_injury': 'Fall',
        'severity': 'minor',
        'imaging_findings': None,
        'treatment_plan': 'Rest.',
        'work_status': None,
        'notes': None,
    },
}


class TestValidatorLambdaHandler:
    def test_valid_lab_result_passes(self):
        result = validator_handler.lambda_handler(VALID_LAB_RESULT_EVENT, None)
        assert result['job_id'] == 'job-123'
        assert result['doc_type'] == 'lab_result'
        assert 'validated_data' in result

    def test_valid_injury_doc_passes(self):
        result = validator_handler.lambda_handler(VALID_INJURY_DOC_EVENT, None)
        assert result['doc_type'] == 'injury_doc'
        assert 'validated_data' in result

    def test_missing_required_field_raises(self):
        event = {**VALID_LAB_RESULT_EVENT}
        extracted = {**event['extracted_data']}
        del extracted['patient_id']
        event = {**event, 'extracted_data': extracted}

        with pytest.raises(jsonschema.ValidationError):
            validator_handler.lambda_handler(event, None)

    def test_invalid_severity_raises(self):
        event = {**VALID_INJURY_DOC_EVENT}
        extracted = {**event['extracted_data'], 'severity': 'extreme'}
        event = {**event, 'extracted_data': extracted}

        with pytest.raises(jsonschema.ValidationError):
            validator_handler.lambda_handler(event, None)

    def test_validated_data_equals_extracted_data(self):
        result = validator_handler.lambda_handler(VALID_LAB_RESULT_EVENT, None)
        assert result['validated_data'] == VALID_LAB_RESULT_EVENT['extracted_data']

    def test_bucket_and_key_passed_through(self):
        result = validator_handler.lambda_handler(VALID_LAB_RESULT_EVENT, None)
        assert result['bucket'] == 'test-bucket'
        assert result['key'] == 'uploads/job-123/test.txt'
