"""Unit tests for the fail_handler Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'fail_handler'

MOCK_ENV = {'JOBS_TABLE': 'test-jobs'}

_spec = importlib.util.spec_from_file_location('fail_handler_handler', HANDLER_DIR / 'handler.py')
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


class TestCauseParsing:
    def test_plain_string_cause_stored_directly(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            handler.lambda_handler(
                {'job_id': 'job-1', 'error': {'Cause': 'Something went wrong'}},
                None,
            )

            call_kwargs = mock_table.update_item.call_args[1]
            assert call_kwargs['ExpressionAttributeValues'][':e'] == 'Something went wrong'

    def test_json_cause_extracts_error_message(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            cause = json.dumps({'errorMessage': 'ValueError: unknown doc type', 'errorType': 'ValueError'})
            handler.lambda_handler(
                {'job_id': 'job-2', 'error': {'Cause': cause}},
                None,
            )

            call_kwargs = mock_table.update_item.call_args[1]
            assert 'ValueError: unknown doc type' in call_kwargs['ExpressionAttributeValues'][':e']

    def test_missing_error_key_uses_unknown(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            handler.lambda_handler({'job_id': 'job-3'}, None)

            call_kwargs = mock_table.update_item.call_args[1]
            assert 'Unknown error' in call_kwargs['ExpressionAttributeValues'][':e']


class TestDynamoDBUpdate:
    def test_status_set_to_failed(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            handler.lambda_handler(
                {'job_id': 'job-4', 'error': {'Cause': 'timeout'}},
                None,
            )

            call_kwargs = mock_table.update_item.call_args[1]
            assert call_kwargs['ExpressionAttributeValues'][':s'] == 'FAILED'
            assert call_kwargs['Key'] == {'job_id': 'job-4'}

    def test_return_value_includes_job_id_and_status(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            result = handler.lambda_handler(
                {'job_id': 'job-5', 'error': {'Cause': 'error'}},
                None,
            )

        assert result['job_id'] == 'job-5'
        assert result['status'] == 'FAILED'
