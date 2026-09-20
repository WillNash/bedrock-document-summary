"""Unit tests for the api_summary Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest
from botocore.exceptions import ClientError

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'api_summary'

MOCK_ENV = {'JOBS_TABLE': 'test-jobs', 'SUMMARIES_BUCKET': 'test-summaries'}

_spec = importlib.util.spec_from_file_location('api_summary_handler', HANDLER_DIR / 'handler.py')
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


def make_event(job_id='job-123', user_id='user-abc'):
    return {
        'requestContext': {
            'authorizer': {
                'jwt': {'claims': {'sub': user_id}}
            }
        },
        'pathParameters': {'jobId': job_id},
    }


def make_completed_item(job_id='job-123', user_id='user-abc'):
    return {'job_id': job_id, 'user_id': user_id, 'status': 'COMPLETED', 'doc_type': 'lab_result'}


def make_s3_body(text='Summary text.'):
    body_mock = mock.MagicMock()
    body_mock.read.return_value = text.encode('utf-8')
    return {'Body': body_mock}


SAMPLE_USAGE = {
    'classifier': {'model': 'us.anthropic.claude-haiku-4-5-20251001-v1:0', 'input_tokens': 100, 'output_tokens': 5},
    'extractor': {'model': 'us.anthropic.claude-sonnet-4-5-20250929-v1:0', 'input_tokens': 2000, 'output_tokens': 300},
}


def s3_side_effect(summary_text='Patient summary here.'):
    """Return a side_effect list: summary.txt first, usage.json second."""
    return [make_s3_body(summary_text), make_s3_body(json.dumps(SAMPLE_USAGE))]


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


class TestOwnershipAndAvailability:
    def test_returns_404_for_different_user(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client'):

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.get_item.return_value = {
                'Item': {'job_id': 'job-123', 'user_id': 'other-user', 'status': 'COMPLETED'}
            }

            result = handler.lambda_handler(make_event(), None)

        assert result['statusCode'] == 404

    def test_returns_404_when_job_not_completed(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client'):

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.get_item.return_value = {
                'Item': {'job_id': 'job-123', 'user_id': 'user-abc', 'status': 'RUNNING'}
            }

            result = handler.lambda_handler(make_event(), None)

        assert result['statusCode'] == 404

    def test_returns_500_when_s3_key_missing(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.get_item.return_value = {'Item': make_completed_item()}
            mock_s3.get_object.side_effect = ClientError(
                {'Error': {'Code': 'NoSuchKey', 'Message': 'Not found'}},
                'GetObject',
            )

            result = handler.lambda_handler(make_event(), None)

        assert result['statusCode'] == 500

    def test_returns_200_with_summary_text(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.get_item.return_value = {'Item': make_completed_item()}
            mock_s3.get_object.side_effect = s3_side_effect('Patient summary here.')

            result = handler.lambda_handler(make_event(), None)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['summary'] == 'Patient summary here.'
        assert body['job_id'] == 'job-123'
        assert body['usage']['classifier']['input_tokens'] == 100
        assert body['usage']['extractor']['output_tokens'] == 300

    def test_returns_200_with_empty_usage_when_usage_json_missing(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.get_item.return_value = {'Item': make_completed_item()}
            mock_s3.get_object.side_effect = [
                make_s3_body('Summary text.'),
                ClientError({'Error': {'Code': 'NoSuchKey', 'Message': 'Not found'}}, 'GetObject'),
            ]

            result = handler.lambda_handler(make_event(), None)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['usage'] == {}

    def test_non_nosuchkey_s3_error_propagates(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.get_item.return_value = {'Item': make_completed_item()}
            mock_s3.get_object.side_effect = ClientError(
                {'Error': {'Code': 'AccessDenied', 'Message': 'Denied'}},
                'GetObject',
            )

            with pytest.raises(ClientError):
                handler.lambda_handler(make_event(), None)
