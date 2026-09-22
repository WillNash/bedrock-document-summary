"""Unit tests for the fail_handler Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'fail_handler'

MOCK_ENV = {
    'JOBS_TABLE': 'test-jobs',
    'EXPERIMENTS_TABLE': 'test-experiments',
    'SUMMARIES_BUCKET': 'test-summaries',
    'COMPARISON_SM_ARN': 'arn:aws:states:us-east-1:123456789:stateMachine:test-comparison',
}

_spec = importlib.util.spec_from_file_location('fail_handler_handler', HANDLER_DIR / 'handler.py')
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


class TestCauseParsing:
    def test_plain_string_cause_stored_directly(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 'sfn_client'):
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            handler.lambda_handler(
                {'job_id': 'job-1', 'error': {'Cause': 'Something went wrong'}},
                None,
            )

            call_kwargs = mock_table.update_item.call_args[1]
            assert call_kwargs['ExpressionAttributeValues'][':e'] == 'Something went wrong'

    def test_json_cause_extracts_error_message(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 'sfn_client'):
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
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 'sfn_client'):
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            handler.lambda_handler({'job_id': 'job-3'}, None)

            call_kwargs = mock_table.update_item.call_args[1]
            assert 'Unknown error' in call_kwargs['ExpressionAttributeValues'][':e']


class TestDynamoDBUpdate:
    def test_status_set_to_failed(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 'sfn_client'):
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
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 'sfn_client'):
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            result = handler.lambda_handler(
                {'job_id': 'job-5', 'error': {'Cause': 'error'}},
                None,
            )

        assert result['job_id'] == 'job-5'
        assert result['status'] == 'FAILED'


class TestExperimentTracking:
    def _make_ddb_mock(self, completed_n, expected_n, successful_n=0):
        from decimal import Decimal
        mock_ddb = mock.MagicMock()
        mock_table = mock.MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_table.update_item.return_value = {
            'Attributes': {
                'completed_n': Decimal(str(completed_n)),
                'expected_n': Decimal(str(expected_n)),
                'successful_n': Decimal(str(successful_n)),
                'failed_n': Decimal('1'),
            }
        }
        return mock_ddb, mock_table

    def test_experiment_updates_experiments_table(self):
        mock_ddb, mock_table = self._make_ddb_mock(completed_n=3, expected_n=5)

        with mock.patch.object(handler, 'dynamodb', mock_ddb), \
             mock.patch.object(handler, 'sfn_client'):

            handler.lambda_handler(
                {'job_id': 'job-6', 'experiment_id': 'exp-001', 'run_number': 2},
                None,
            )

        # update_item called twice: once for jobs table, once for experiments table
        assert mock_table.update_item.call_count == 2

    def test_comparison_sm_started_when_all_runs_complete(self):
        mock_ddb, mock_table = self._make_ddb_mock(completed_n=5, expected_n=5, successful_n=4)

        with mock.patch.object(handler, 'dynamodb', mock_ddb), \
             mock.patch.object(handler, 'sfn_client') as mock_sfn:

            handler.lambda_handler(
                {'job_id': 'job-7', 'experiment_id': 'exp-002', 'run_number': 5},
                None,
            )

        mock_sfn.start_execution.assert_called_once()
        call_kwargs = mock_sfn.start_execution.call_args[1]
        assert call_kwargs['name'] == 'exp-002'

    def test_comparison_sm_not_started_when_runs_incomplete(self):
        mock_ddb, mock_table = self._make_ddb_mock(completed_n=3, expected_n=5)

        with mock.patch.object(handler, 'dynamodb', mock_ddb), \
             mock.patch.object(handler, 'sfn_client') as mock_sfn:

            handler.lambda_handler(
                {'job_id': 'job-8', 'experiment_id': 'exp-003', 'run_number': 3},
                None,
            )

        mock_sfn.start_execution.assert_not_called()

    def test_no_experiment_skips_experiment_tracking(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 'sfn_client') as mock_sfn:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            handler.lambda_handler({'job_id': 'job-9', 'error': {'Cause': 'err'}}, None)

        mock_sfn.start_execution.assert_not_called()
        # Only one update_item call (jobs table), not two
        assert mock_table.update_item.call_count == 1
