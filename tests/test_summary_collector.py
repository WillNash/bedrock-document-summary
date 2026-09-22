"""Unit tests for the summary_collector Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest
from decimal import Decimal

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'summary_collector'

MOCK_ENV = {'EXPERIMENTS_TABLE': 'test-experiments'}

_spec = importlib.util.spec_from_file_location('summary_collector_handler', HANDLER_DIR / 'handler.py')
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


EVENT = {
    'experiment_id': 'exp-001',
    'summaries_bucket': 'test-summaries',
    'successful_n': 3,
}


def make_s3_listing(experiment_id, run_numbers):
    contents = []
    for rn in run_numbers:
        contents.append({'Key': f'experiments/{experiment_id}/runs/{rn}/summary.txt'})
        contents.append({'Key': f'experiments/{experiment_id}/runs/{rn}/metadata.json'})
    return [{'Contents': contents}]


def make_ddb_mock(gold_key=None):
    mock_ddb = mock.MagicMock()
    mock_table = mock.MagicMock()
    mock_ddb.Table.return_value = mock_table
    config = {'source_document_key': 'uploads/job-src/doc.txt'}
    if gold_key:
        config['gold_key'] = gold_key
    mock_table.get_item.return_value = {
        'Item': {'experiment_id': 'exp-001', 'expected_n': Decimal('5'), 'config': config}
    }
    return mock_ddb, mock_table


class TestRunDiscovery:
    def test_returns_manifests_for_all_successful_runs(self):
        mock_s3 = mock.MagicMock()
        paginator = mock.MagicMock()
        mock_s3.get_paginator.return_value = paginator
        paginator.paginate.return_value = make_s3_listing('exp-001', [1, 2, 3])

        mock_ddb, _ = make_ddb_mock()

        with mock.patch.object(handler, 's3_client', mock_s3), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):
            # Suppress metadata read for first run
            mock_s3.get_object.return_value = {
                'Body': mock.MagicMock(read=lambda: json.dumps({'doc_type': 'lab_result'}).encode())
            }
            result = handler.lambda_handler(EVENT, None)

        assert result['successful_n'] == 3
        assert len(result['run_manifests']) == 3
        run_numbers = sorted(m['run_number'] for m in result['run_manifests'])
        assert run_numbers == [1, 2, 3]

    def test_manifests_include_correct_s3_keys(self):
        mock_s3 = mock.MagicMock()
        paginator = mock.MagicMock()
        mock_s3.get_paginator.return_value = paginator
        paginator.paginate.return_value = make_s3_listing('exp-001', [1])
        mock_s3.get_object.return_value = {
            'Body': mock.MagicMock(read=lambda: json.dumps({'doc_type': 'lab_result'}).encode())
        }

        mock_ddb, _ = make_ddb_mock()

        with mock.patch.object(handler, 's3_client', mock_s3), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):
            result = handler.lambda_handler(EVENT, None)

        manifest = result['run_manifests'][0]
        assert manifest['summary_key'] == 'experiments/exp-001/runs/1/summary.txt'
        assert manifest['metadata_key'] == 'experiments/exp-001/runs/1/metadata.json'


class TestGoldDetection:
    def test_has_gold_true_when_gold_key_present(self):
        mock_s3 = mock.MagicMock()
        paginator = mock.MagicMock()
        mock_s3.get_paginator.return_value = paginator
        paginator.paginate.return_value = make_s3_listing('exp-001', [1])
        mock_s3.get_object.return_value = {
            'Body': mock.MagicMock(read=lambda: json.dumps({'doc_type': 'lab_result'}).encode())
        }

        mock_ddb, _ = make_ddb_mock(gold_key='experiments/exp-001/gold.txt')

        with mock.patch.object(handler, 's3_client', mock_s3), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):
            result = handler.lambda_handler(EVENT, None)

        assert result['has_gold'] is True
        assert result['gold_key'] == 'experiments/exp-001/gold.txt'

    def test_has_gold_false_when_no_gold_key(self):
        mock_s3 = mock.MagicMock()
        paginator = mock.MagicMock()
        mock_s3.get_paginator.return_value = paginator
        paginator.paginate.return_value = make_s3_listing('exp-001', [1])
        mock_s3.get_object.return_value = {
            'Body': mock.MagicMock(read=lambda: json.dumps({'doc_type': 'lab_result'}).encode())
        }

        mock_ddb, _ = make_ddb_mock(gold_key=None)

        with mock.patch.object(handler, 's3_client', mock_s3), \
             mock.patch.object(handler, 'dynamodb', mock_ddb):
            result = handler.lambda_handler(EVENT, None)

        assert result['has_gold'] is False
        assert result['gold_key'] is None
