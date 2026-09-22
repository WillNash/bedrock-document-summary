"""Unit tests for the report_writer Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'report_writer'

MOCK_ENV = {
    'EXPERIMENTS_TABLE': 'test-experiments',
    'SUMMARIES_BUCKET': 'test-summaries',
}

_spec = importlib.util.spec_from_file_location('report_writer_handler', HANDLER_DIR / 'handler.py')
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)

EVENT = {
    'experiment_id': 'exp-001',
    'summaries_bucket': 'test-summaries',
    'doc_type': 'lab_result',
    'successful_n': 5,
    'config': {'description': 'test run'},
    'variance_results': {
        'embedding_cosine': {'mean': 0.95, 'std': 0.02, 'min': 0.91, 'max': 0.98, 'n_runs': 5, 'n_pairs': 10, 'variance': 0.0004, 'matrix': [], 'run_numbers': [1, 2, 3, 4, 5]},
        'tfidf_cosine': {'mean': 0.88, 'std': 0.05, 'min': 0.80, 'max': 0.93, 'n_runs': 5, 'n_pairs': 10, 'variance': 0.0025, 'matrix': [], 'run_numbers': [1, 2, 3, 4, 5]},
    },
    'gold_results': None,
    'report': {'narrative_md': '## Summary\n\nThe pipeline shows high consistency.'},
}


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


class TestReportWriter:
    def test_comparison_json_written(self):
        with mock.patch.object(handler, 's3_client') as mock_s3, \
             mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            handler.lambda_handler(EVENT, None)

        put_calls = {c.kwargs['Key']: c.kwargs for c in mock_s3.put_object.call_args_list}
        assert 'experiments/exp-001/report/comparison.json' in put_calls
        report = json.loads(put_calls['experiments/exp-001/report/comparison.json']['Body'])
        assert report['experiment_id'] == 'exp-001'
        assert report['successful_n'] == 5
        assert 'variance_results' in report

    def test_narrative_md_written(self):
        with mock.patch.object(handler, 's3_client') as mock_s3, \
             mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            handler.lambda_handler(EVENT, None)

        put_calls = {c.kwargs['Key']: c.kwargs for c in mock_s3.put_object.call_args_list}
        assert 'experiments/exp-001/report/narrative.md' in put_calls
        assert b'## Summary' in put_calls['experiments/exp-001/report/narrative.md']['Body']

    def test_experiments_table_updated_to_completed(self):
        with mock.patch.object(handler, 's3_client'), \
             mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            handler.lambda_handler(EVENT, None)

        call_kwargs = mock_table.update_item.call_args[1]
        assert call_kwargs['ExpressionAttributeValues'][':s'] == 'COMPLETED'
        assert call_kwargs['Key'] == {'experiment_id': 'exp-001'}

    def test_return_includes_experiment_id_and_report_prefix(self):
        with mock.patch.object(handler, 's3_client'), \
             mock.patch.object(handler, 'dynamodb') as mock_ddb:
            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table

            result = handler.lambda_handler(EVENT, None)

        assert result['experiment_id'] == 'exp-001'
        assert 'experiments/exp-001/report/' in result['report_prefix']
