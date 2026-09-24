"""Unit tests for the api_presign Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest
from botocore.exceptions import ClientError

HANDLER_DIR = Path(__file__).parent.parent / 'lambda' / 'api_presign'

MOCK_ENV = {
    'UPLOAD_BUCKET': 'test-uploads',
    'JOBS_TABLE': 'test-jobs',
    'UPLOAD_MAX_SIZE_BYTES': '10485760',
    'DAILY_UPLOAD_LIMIT': '5',
}

_spec = importlib.util.spec_from_file_location('api_presign_handler', HANDLER_DIR / 'handler.py')
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


def make_event(filename='test.pdf', user_id='user-abc'):
    return {
        'requestContext': {
            'authorizer': {
                'jwt': {'claims': {'sub': user_id}}
            }
        },
        'body': json.dumps({'filename': filename}),
    }


@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    for k, v in MOCK_ENV.items():
        monkeypatch.setenv(k, v)


class TestQuotaLogic:
    def test_allows_upload_when_under_limit(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_s3.generate_presigned_post.return_value = {
                'url': 'https://bucket.s3.amazonaws.com',
                'fields': {'key': 'uploads/job/test.pdf'},
            }

            result = handler.lambda_handler(make_event(), None)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert 'job_id' in body
        assert 'presign_url' in body

    def test_returns_429_when_limit_reached(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client'):

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.update_item.side_effect = ClientError(
                {'Error': {'Code': 'ConditionalCheckFailedException', 'Message': 'Condition failed'}},
                'UpdateItem',
            )

            result = handler.lambda_handler(make_event(), None)

        assert result['statusCode'] == 429
        body = json.loads(result['body'])
        assert 'error' in body

    def test_non_quota_dynamodb_error_propagates(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client'):

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_table.update_item.side_effect = ClientError(
                {'Error': {'Code': 'ProvisionedThroughputExceededException', 'Message': 'Throttled'}},
                'UpdateItem',
            )

            with pytest.raises(ClientError):
                handler.lambda_handler(make_event(), None)


class TestPresignedUrl:
    def test_response_includes_job_id_and_presign_fields(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_s3.generate_presigned_post.return_value = {
                'url': 'https://bucket.s3.amazonaws.com',
                'fields': {'Content-Type': 'application/octet-stream', 'key': 'uploads/job/f.pdf'},
            }

            result = handler.lambda_handler(make_event('report.pdf'), None)

        body = json.loads(result['body'])
        assert 'job_id' in body
        assert body['presign_url'] == 'https://bucket.s3.amazonaws.com'
        assert 'presign_fields' in body

    def test_validate_flag_written_to_dynamodb(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_s3.generate_presigned_post.return_value = {
                'url': 'https://bucket.s3.amazonaws.com',
                'fields': {},
            }
            event = {
                'requestContext': {'authorizer': {'jwt': {'claims': {'sub': 'user-abc'}}}},
                'body': json.dumps({'filename': 'test.pdf', 'validate': True}),
            }

            handler.lambda_handler(event, None)

            call_kwargs = mock_table.put_item.call_args[1]
            assert call_kwargs['Item']['validate'] is True

    def test_filename_path_components_stripped(self):
        with mock.patch.object(handler, 'dynamodb') as mock_ddb, \
             mock.patch.object(handler, 's3_client') as mock_s3:

            mock_table = mock.MagicMock()
            mock_ddb.Table.return_value = mock_table
            mock_s3.generate_presigned_post.return_value = {
                'url': 'https://bucket.s3.amazonaws.com',
                'fields': {},
            }

            handler.lambda_handler(make_event('../../../etc/passwd'), None)

            call_kwargs = mock_s3.generate_presigned_post.call_args[1]
            assert 'etc/passwd' not in call_kwargs['Key']
            assert call_kwargs['Key'].endswith('passwd')
