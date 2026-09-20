"""Unit tests for the renderer Lambda handler (S3 and DynamoDB integration)."""
import importlib.util
from pathlib import Path
from unittest import mock

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'renderer'
TEMPLATES_DIR = Path(__file__).parent.parent / 'templates'

MOCK_ENV = {'SUMMARIES_BUCKET': 'test-summaries', 'JOBS_TABLE': 'test-jobs'}

_spec = importlib.util.spec_from_file_location('renderer_handler', HANDLER_DIR / 'handler.py')
renderer_handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(renderer_handler)

SAMPLE_EVENT = {
    'job_id': 'job-rdr-1',
    'doc_type': 'lab_result',
    'validated_data': {
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
    'usage_stats': {
        'classifier': {'model': 'us.anthropic.claude-haiku-4-5-20251001-v1:0', 'input_tokens': 100, 'output_tokens': 5},
        'extractor': {'model': 'us.anthropic.claude-sonnet-4-5-20250929-v1:0', 'input_tokens': 2000, 'output_tokens': 300},
    },
}


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture(autouse=True)
def patch_templates(monkeypatch):
    real_env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape([]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    monkeypatch.setattr(renderer_handler, 'jinja_env', real_env)


class TestRendererHandler:
    def test_s3_put_object_called_with_correct_key(self):
        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb') as mock_ddb:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            renderer_handler.lambda_handler(SAMPLE_EVENT, None)

            put_calls = {c.kwargs['Key']: c.kwargs for c in mock_s3.put_object.call_args_list}
            assert 'summaries/job-rdr-1/summary.txt' in put_calls
            assert put_calls['summaries/job-rdr-1/summary.txt']['Bucket'] == 'test-summaries'
            assert put_calls['summaries/job-rdr-1/summary.txt']['ContentType'] == 'text/plain; charset=utf-8'

    def test_usage_json_written_to_s3(self):
        import json as _json
        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb') as mock_ddb:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            renderer_handler.lambda_handler(SAMPLE_EVENT, None)

            put_calls = {c.kwargs['Key']: c.kwargs for c in mock_s3.put_object.call_args_list}
            assert 'summaries/job-rdr-1/usage.json' in put_calls
            usage_body = _json.loads(put_calls['summaries/job-rdr-1/usage.json']['Body'])
            assert usage_body['classifier']['input_tokens'] == 100
            assert usage_body['extractor']['output_tokens'] == 300

    def test_summary_body_contains_patient_data(self):
        with mock.patch.object(renderer_handler, 's3_client') as mock_s3, \
             mock.patch.object(renderer_handler, 'dynamodb') as mock_ddb:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            renderer_handler.lambda_handler(SAMPLE_EVENT, None)

            put_calls = {c.kwargs['Key']: c.kwargs for c in mock_s3.put_object.call_args_list}
            summary_body = put_calls['summaries/job-rdr-1/summary.txt']['Body']
            assert b'P-001' in summary_body

    def test_dynamodb_updated_to_completed(self):
        with mock.patch.object(renderer_handler, 's3_client'), \
             mock.patch.object(renderer_handler, 'dynamodb') as mock_ddb:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            renderer_handler.lambda_handler(SAMPLE_EVENT, None)

            mock_table.update_item.assert_called_once()
            call_kwargs = mock_table.update_item.call_args[1]
            assert call_kwargs['ExpressionAttributeValues'][':s'] == 'COMPLETED'
            assert call_kwargs['ExpressionAttributeValues'][':dt'] == 'lab_result'

    def test_return_value_includes_summary_key(self):
        with mock.patch.object(renderer_handler, 's3_client'), \
             mock.patch.object(renderer_handler, 'dynamodb') as mock_ddb:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            result = renderer_handler.lambda_handler(SAMPLE_EVENT, None)

        assert result['job_id'] == 'job-rdr-1'
        assert result['summary_key'] == 'summaries/job-rdr-1/summary.txt'
