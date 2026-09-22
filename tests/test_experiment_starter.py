"""Unit tests for the experiment_starter Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest
from botocore.exceptions import ClientError

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'experiment_starter'

MOCK_ENV = {
    'UPLOAD_BUCKET': 'test-uploads',
    'SUMMARIES_BUCKET': 'test-summaries',
    'JOBS_TABLE': 'test-jobs',
    'EXPERIMENTS_TABLE': 'test-experiments',
}

_spec = importlib.util.spec_from_file_location('experiment_starter_handler', HANDLER_DIR / 'handler.py')
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)

VALID_BODY = {
    'experiment_id': 'exp-001',
    'expected_n': 3,
    'source_document_key': 'uploads/job-src/doc.txt',
    'config': {'description': 'test run'},
}


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


def make_event(body):
    return {'body': json.dumps(body)}


def make_s3_ddb_mock(source_exists=True):
    mock_s3 = mock.MagicMock()
    mock_ddb = mock.MagicMock()
    mock_table = mock.MagicMock()
    mock_ddb.Table.return_value = mock_table

    if not source_exists:
        mock_s3.head_object.side_effect = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}}, 'HeadObject'
        )

    return mock_s3, mock_ddb, mock_table


class TestValidation:
    def test_missing_experiment_id_returns_400(self):
        with mock.patch.object(handler, 's3_client'), mock.patch.object(handler, 'dynamodb'):
            body = {**VALID_BODY, 'experiment_id': ''}
            result = handler.lambda_handler(make_event(body), None)
        assert result['statusCode'] == 400

    def test_missing_source_key_returns_400(self):
        with mock.patch.object(handler, 's3_client'), mock.patch.object(handler, 'dynamodb'):
            body = {**VALID_BODY, 'source_document_key': ''}
            result = handler.lambda_handler(make_event(body), None)
        assert result['statusCode'] == 400

    def test_expected_n_below_2_returns_400(self):
        with mock.patch.object(handler, 's3_client'), mock.patch.object(handler, 'dynamodb'):
            body = {**VALID_BODY, 'expected_n': 1}
            result = handler.lambda_handler(make_event(body), None)
        assert result['statusCode'] == 400

    def test_source_document_not_found_returns_404(self):
        mock_s3, mock_ddb, _ = make_s3_ddb_mock(source_exists=False)
        with mock.patch.object(handler, 's3_client', mock_s3), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):
            result = handler.lambda_handler(make_event(VALID_BODY), None)
        assert result['statusCode'] == 404


class TestHappyPath:
    def test_returns_experiment_id_and_job_ids(self):
        mock_s3, mock_ddb, _ = make_s3_ddb_mock()
        with mock.patch.object(handler, 's3_client', mock_s3), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):
            result = handler.lambda_handler(make_event(VALID_BODY), None)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['experiment_id'] == 'exp-001'
        assert len(body['job_ids']) == 3

    def test_copies_source_doc_n_times(self):
        mock_s3, mock_ddb, _ = make_s3_ddb_mock()
        with mock.patch.object(handler, 's3_client', mock_s3), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):
            handler.lambda_handler(make_event(VALID_BODY), None)

        assert mock_s3.copy_object.call_count == 3

    def test_gold_text_written_to_s3(self):
        mock_s3, mock_ddb, _ = make_s3_ddb_mock()
        body = {**VALID_BODY, 'gold_text': 'This is the reference summary.'}
        with mock.patch.object(handler, 's3_client', mock_s3), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):
            handler.lambda_handler(make_event(body), None)

        put_keys = [c.kwargs['Key'] for c in mock_s3.put_object.call_args_list]
        assert any('gold.txt' in k for k in put_keys)

    def test_experiments_table_item_written(self):
        mock_s3, mock_ddb, mock_table = make_s3_ddb_mock()
        with mock.patch.object(handler, 's3_client', mock_s3), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):
            handler.lambda_handler(make_event(VALID_BODY), None)

        # put_item called on both jobs table (3 times) and experiments table (1 time)
        assert mock_table.put_item.call_count == 4

    def test_jobs_table_items_have_experiment_context(self):
        mock_s3, mock_ddb, mock_table = make_s3_ddb_mock()
        with mock.patch.object(handler, 's3_client', mock_s3), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):
            handler.lambda_handler(make_event(VALID_BODY), None)

        job_put_calls = [
            c.kwargs['Item'] for c in mock_table.put_item.call_args_list
            if 'job_id' in c.kwargs.get('Item', {})
        ]
        assert len(job_put_calls) == 3
        run_numbers = sorted(int(item['run_number']) for item in job_put_calls)
        assert run_numbers == [1, 2, 3]
        assert all(item['experiment_id'] == 'exp-001' for item in job_put_calls)
