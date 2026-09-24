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


def make_ddb_mock(experiment_id=None, run_number=None):
    mock_ddb = mock.MagicMock()
    mock_table = mock.MagicMock()
    mock_ddb.Table.return_value = mock_table
    item = {}
    if experiment_id:
        item['experiment_id'] = experiment_id
        item['run_number'] = run_number
    mock_table.get_item.return_value = {'Item': item} if item else {}
    return mock_ddb, mock_table


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


class TestKeyParsing:
    def test_valid_key_starts_execution_with_job_id(self):
        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb') as mock_ddb:

            mock_ddb, mock_table = make_ddb_mock()
            mock.patch.object(handler, 'dynamodb', mock_ddb).start()

            handler.lambda_handler(make_s3_event(), None)

            mock_sfn.start_execution.assert_called_once()
            call_kwargs = mock_sfn.start_execution.call_args[1]
            assert call_kwargs['name'] == 'job-abc'

    def test_unexpected_key_pattern_is_skipped(self):
        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb'):

            handler.lambda_handler(make_s3_event(key='other/path/file.pdf'), None)

            mock_sfn.start_execution.assert_not_called()


class TestExperimentContext:
    def test_experiment_id_and_run_number_added_to_execution_input(self):
        mock_ddb, mock_table = make_ddb_mock(experiment_id='exp-001', run_number=3)
        import json

        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            handler.lambda_handler(make_s3_event(), None)

            call_kwargs = mock_sfn.start_execution.call_args[1]
            payload = json.loads(call_kwargs['input'])
            assert payload['experiment_id'] == 'exp-001'
            assert payload['run_number'] == 3

    def test_no_experiment_context_omits_experiment_fields(self):
        mock_ddb, mock_table = make_ddb_mock()
        import json

        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            handler.lambda_handler(make_s3_event(), None)

            call_kwargs = mock_sfn.start_execution.call_args[1]
            payload = json.loads(call_kwargs['input'])
            assert 'experiment_id' not in payload
            assert 'run_number' not in payload


class TestExecutionAlreadyExists:
    def test_duplicate_s3_event_still_updates_dynamodb(self):
        mock_ddb, mock_table = make_ddb_mock()

        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            mock_sfn.start_execution.side_effect = ClientError(
                {'Error': {'Code': 'ExecutionAlreadyExists', 'Message': 'Already running'}},
                'StartExecution',
            )

            handler.lambda_handler(make_s3_event(), None)

            mock_table.update_item.assert_called_once()

    def test_other_sfn_error_propagates(self):
        mock_ddb, mock_table = make_ddb_mock()

        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            mock_sfn.start_execution.side_effect = ClientError(
                {'Error': {'Code': 'StateMachineDoesNotExist', 'Message': 'Not found'}},
                'StartExecution',
            )

            with pytest.raises(ClientError):
                handler.lambda_handler(make_s3_event(), None)


class TestValidateFlag:
    def test_validate_flag_threaded_from_dynamodb(self):
        mock_ddb, mock_table = make_ddb_mock()
        mock_table.get_item.return_value = {'Item': {'validate': True}}
        import json

        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            handler.lambda_handler(make_s3_event(), None)

            call_kwargs = mock_sfn.start_execution.call_args[1]
            payload = json.loads(call_kwargs['input'])
            assert payload.get('validate') is True

    def test_validate_reserved_word_alias_used(self):
        mock_ddb, mock_table = make_ddb_mock()

        with mock.patch.object(handler, 'sfn_client'), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            handler.lambda_handler(make_s3_event(), None)

            get_item_kwargs = mock_table.get_item.call_args[1]
            assert 'ExpressionAttributeNames' in get_item_kwargs
            assert get_item_kwargs['ExpressionAttributeNames'].get('#validate') == 'validate'
            assert '#validate' in get_item_kwargs['ProjectionExpression']

    def test_validate_absent_from_dynamodb_not_in_sfn_input(self):
        mock_ddb, mock_table = make_ddb_mock()
        mock_table.get_item.return_value = {'Item': {}}
        import json

        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            handler.lambda_handler(make_s3_event(), None)

            call_kwargs = mock_sfn.start_execution.call_args[1]
            payload = json.loads(call_kwargs['input'])
            assert 'validate' not in payload


class TestDocTypeBypassFields:
    def test_doc_type_read_from_dynamodb_and_forwarded(self):
        mock_ddb, mock_table = make_ddb_mock()
        mock_table.get_item.return_value = {'Item': {'doc_type': 'lab_result'}}
        import json

        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            handler.lambda_handler(make_s3_event(), None)

            payload = json.loads(mock_sfn.start_execution.call_args[1]['input'])
            assert payload['doc_type'] == 'lab_result'

    def test_custom_prompt_forwarded_when_present(self):
        mock_ddb, mock_table = make_ddb_mock()
        mock_table.get_item.return_value = {'Item': {'custom_prompt': 'Extract carefully.'}}
        import json

        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            handler.lambda_handler(make_s3_event(), None)

            payload = json.loads(mock_sfn.start_execution.call_args[1]['input'])
            assert payload['custom_prompt'] == 'Extract carefully.'

    def test_custom_schema_empty_string_forwarded(self):
        mock_ddb, mock_table = make_ddb_mock()
        mock_table.get_item.return_value = {'Item': {'custom_schema': ''}}
        import json

        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            handler.lambda_handler(make_s3_event(), None)

            payload = json.loads(mock_sfn.start_execution.call_args[1]['input'])
            assert payload['custom_schema'] == ''

    def test_doc_type_absent_not_forwarded(self):
        mock_ddb, mock_table = make_ddb_mock()
        mock_table.get_item.return_value = {'Item': {}}
        import json

        with mock.patch.object(handler, 'sfn_client') as mock_sfn, \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            handler.lambda_handler(make_s3_event(), None)

            payload = json.loads(mock_sfn.start_execution.call_args[1]['input'])
            assert 'doc_type' not in payload
            assert 'custom_prompt' not in payload
            assert 'custom_schema' not in payload

    def test_doc_type_included_in_projection_expression(self):
        mock_ddb, mock_table = make_ddb_mock()

        with mock.patch.object(handler, 'sfn_client'), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            handler.lambda_handler(make_s3_event(), None)

            get_item_kwargs = mock_table.get_item.call_args[1]
            proj = get_item_kwargs['ProjectionExpression']
            assert 'doc_type' in proj
            assert 'custom_prompt' in proj
            assert 'custom_schema' in proj


class TestConditionalStatusUpdate:
    def test_conditional_check_failure_suppressed(self):
        mock_ddb, mock_table = make_ddb_mock()
        mock_table.update_item.side_effect = ClientError(
            {'Error': {'Code': 'ConditionalCheckFailedException', 'Message': 'Condition failed'}},
            'UpdateItem',
        )

        with mock.patch.object(handler, 'sfn_client'), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            result = handler.lambda_handler(make_s3_event(), None)

        assert result['statusCode'] == 200

    def test_other_dynamodb_error_propagates(self):
        mock_ddb, mock_table = make_ddb_mock()
        mock_table.update_item.side_effect = ClientError(
            {'Error': {'Code': 'ProvisionedThroughputExceededException', 'Message': 'Throttled'}},
            'UpdateItem',
        )

        with mock.patch.object(handler, 'sfn_client'), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):

            with pytest.raises(ClientError):
                handler.lambda_handler(make_s3_event(), None)
