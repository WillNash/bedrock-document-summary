"""Unit tests for the pipeline_starter Lambda handler."""
import importlib.util
from pathlib import Path
from unittest import mock

import pytest
from botocore.exceptions import ClientError

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'pipeline_starter'

MOCK_ENV = {
    'STATE_MACHINE_ARN': 'arn:aws:states:us-east-1:123456789:stateMachine:test-pipeline',
    'JOBS_TABLE': 'test-jobs',
}

_spec = importlib.util.spec_from_file_location('pipeline_starter_handler', HANDLER_DIR / 'handler.py')
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


def make_s3_event(key='uploads/job-abc/report.pdf', bucket='test-uploads'):
    return {
        'Records': [
            {
                's3': {
                    'bucket': {'name': bucket},
                    'object': {'key': key},
                }
            }
        ]
    }


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


class TestKeyParsing:
    def test_valid_key_starts_execution_with_job_id(self):
        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb') as mock_ddb:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            handler.lambda_handler(make_s3_event(), None)

            mock_sfn.start_execution.assert_called_once()
            call_kwargs = mock_sfn.start_execution.call_args[1]
            assert call_kwargs['name'] == 'job-abc'

    def test_unexpected_key_pattern_is_skipped(self):
        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb'):

            handler.lambda_handler(make_s3_event(key='other/path/file.pdf'), None)

            mock_sfn.start_execution.assert_not_called()


class TestExecutionAlreadyExists:
    def test_duplicate_s3_event_still_updates_dynamodb(self):
        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb') as mock_ddb:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_sfn.start_execution.side_effect = ClientError(
                {'Error': {'Code': 'ExecutionAlreadyExists', 'Message': 'Already running'}},
                'StartExecution',
            )

            handler.lambda_handler(make_s3_event(), None)

            mock_table.update_item.assert_called_once()

    def test_other_sfn_error_propagates(self):
        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb'):

            mock_sfn.start_execution.side_effect = ClientError(
                {'Error': {'Code': 'StateMachineDoesNotExist', 'Message': 'Not found'}},
                'StartExecution',
            )

            with pytest.raises(ClientError):
                handler.lambda_handler(make_s3_event(), None)


class TestConditionalStatusUpdate:
    def test_conditional_check_failure_suppressed(self):
        with mock.patch.object(handler, 'sfn_client'), \
             mock.patch.object(handler, 'dynamodb') as mock_ddb:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.update_item.side_effect = ClientError(
                {'Error': {'Code': 'ConditionalCheckFailedException', 'Message': 'Condition failed'}},
                'UpdateItem',
            )

            result = handler.lambda_handler(make_s3_event(), None)

        assert result['statusCode'] == 200

    def test_other_dynamodb_error_propagates(self):
        with mock.patch.object(handler, 'sfn_client'), \
             mock.patch.object(handler, 'dynamodb') as mock_ddb:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.update_item.side_effect = ClientError(
                {'Error': {'Code': 'ProvisionedThroughputExceededException', 'Message': 'Throttled'}},
                'UpdateItem',
            )

            with pytest.raises(ClientError):
                handler.lambda_handler(make_s3_event(), None)
