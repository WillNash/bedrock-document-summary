"""Unit tests for the api_status Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'api_status'

MOCK_ENV = {'JOBS_TABLE': 'test-jobs'}

_spec = importlib.util.spec_from_file_location('api_status_handler', HANDLER_DIR / 'handler.py')
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


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


class TestOwnershipCheck:
    def test_returns_200_for_owner(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.get_item.return_value = {
                'Item': {'job_id': 'job-123', 'user_id': 'user-abc', 'status': 'COMPLETED'}
            }

            result = handler.lambda_handler(make_event(), None)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['status'] == 'COMPLETED'

    def test_returns_404_for_different_user(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.get_item.return_value = {
                'Item': {'job_id': 'job-123', 'user_id': 'other-user', 'status': 'COMPLETED'}
            }

            result = handler.lambda_handler(make_event(), None)

        assert result['statusCode'] == 404

    def test_returns_404_for_missing_job(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.get_item.return_value = {}

            result = handler.lambda_handler(make_event(), None)

        assert result['statusCode'] == 404

    def test_optional_fields_included_when_present(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.get_item.return_value = {
                'Item': {
                    'job_id': 'job-123',
                    'user_id': 'user-abc',
                    'status': 'FAILED',
                    'doc_type': 'lab_result',
                    'error_message': 'Processing error',
                }
            }

            result = handler.lambda_handler(make_event(), None)

        body = json.loads(result['body'])
        assert body['doc_type'] == 'lab_result'
        assert body['error_message'] == 'Processing error'
