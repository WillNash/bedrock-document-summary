"""Unit tests for the claim_extractor Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

HANDLER_PATH = Path(__file__).parent.parent / 'lambda' / 'claim_extractor' / 'handler.py'
TEMPLATES_DIR = Path(__file__).parent.parent / 'templates'

_spec = importlib.util.spec_from_file_location('claim_extractor_handler', HANDLER_PATH)
claim_extractor_handler = importlib.util.module_from_spec(_spec)

with mock.patch.dict('os.environ', {
    'UPLOAD_BUCKET': 'upload-bucket',
    'SUMMARIES_BUCKET': 'summaries-bucket',
    'CHEAP_MODEL_ID': 'au.anthropic.claude-haiku-test',
    'EMBEDDING_MODEL_ID': 'amazon.titan-embed-text-v2:0',
    'DEDUP_SIMILARITY_THRESHOLD': '0.90',
}):
    _spec.loader.exec_module(claim_extractor_handler)


BASE_EVENT = {
    'job_id': 'job-test-001',
    'bucket': 'upload-bucket',
    'key': 'uploads/job-test-001/doc.txt',
    'doc_type': 'lab_result',
    'validated_data': {
        'patient_id': 'P-001',
        'test_date': '2025-01-15',
        'ordering_provider': 'Dr. Smith',
        'test_panels': [{'panel_name': 'CBC', 'results': [
            {'name': 'Hgb', 'value': '13.5', 'unit': 'g/dL', 'reference_range': '12-16', 'flag': None},
        ]}],
        'interpretation': None,
        'notes': None,
    },
}

VERIFIABLE_RESPONSE = json.dumps({'claim': 'Patient P-001 had Hgb of 13.5 g/dL.', 'type': 'verifiable', 'reason': 'checkable'})
NON_VERIFIABLE_RESPONSE = json.dumps({'claim': 'This is a summary.', 'type': 'non_verifiable', 'reason': 'meta'})

EMBEDDING_RESPONSE = json.dumps({'embedding': [0.1] * 1024})
NEAR_DUPLICATE_EMBEDDING = json.dumps({'embedding': [0.1] * 1024})
DISTINCT_EMBEDDING = json.dumps({'embedding': [0.0] + [0.1] * 1023})


def _make_bedrock_mock(converse_text, embed_body=EMBEDDING_RESPONSE):
    bedrock = mock.MagicMock()
    bedrock.converse.return_value = {
        'output': {'message': {'content': [{'text': converse_text}]}}
    }
    bedrock.invoke_model.return_value = {
        'body': mock.MagicMock(read=lambda: embed_body.encode())
    }
    return bedrock


def _make_s3_mock(source_text='Source document content.'):
    s3 = mock.MagicMock()
    s3.get_object.return_value = {
        'Body': mock.MagicMock(read=lambda: source_text.encode())
    }
    return s3


@pytest.fixture(autouse=True)
def patch_template_dir(monkeypatch):
    monkeypatch.setattr(claim_extractor_handler, 'TEMPLATE_DIR', TEMPLATES_DIR)
    import jinja2
    monkeypatch.setattr(
        claim_extractor_handler,
        'jinja_env',
        jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        ),
    )


class TestClaimExtractor:
    def test_jinja2_prerender_writes_to_s3(self):
        bedrock = _make_bedrock_mock(VERIFIABLE_RESPONSE)
        s3 = _make_s3_mock()

        with mock.patch.object(claim_extractor_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_extractor_handler, 's3_client', s3):
            result = claim_extractor_handler.lambda_handler(BASE_EVENT, None)

        put_calls = s3.put_object.call_args_list
        keys_written = [c.kwargs['Key'] for c in put_calls]
        assert 'summaries/job-test-001/pre_render.txt' in keys_written
        assert 'summaries/job-test-001/claims.json' in keys_written

    def test_non_verifiable_claims_filtered(self):
        bedrock = _make_bedrock_mock(NON_VERIFIABLE_RESPONSE)
        s3 = _make_s3_mock()

        with mock.patch.object(claim_extractor_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_extractor_handler, 's3_client', s3):
            result = claim_extractor_handler.lambda_handler(BASE_EVENT, None)

        claims_call = next(
            c for c in s3.put_object.call_args_list
            if c.kwargs['Key'] == 'summaries/job-test-001/claims.json'
        )
        claims = json.loads(claims_call.kwargs['Body'])
        assert claims == []

    def test_deduplication_removes_near_duplicate(self):
        bedrock = mock.MagicMock()
        bedrock.converse.return_value = {
            'output': {'message': {'content': [{'text': VERIFIABLE_RESPONSE}]}}
        }
        call_count = [0]

        def embed_side_effect(**kwargs):
            call_count[0] += 1
            body = NEAR_DUPLICATE_EMBEDDING if call_count[0] > 0 else DISTINCT_EMBEDDING
            return {'body': mock.MagicMock(read=lambda: body.encode())}

        bedrock.invoke_model.side_effect = embed_side_effect
        s3 = _make_s3_mock('Sentence one. Sentence two.')

        with mock.patch.object(claim_extractor_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_extractor_handler, 's3_client', s3):
            result = claim_extractor_handler.lambda_handler(BASE_EVENT, None)

        claims_call = next(
            c for c in s3.put_object.call_args_list
            if c.kwargs['Key'] == 'summaries/job-test-001/claims.json'
        )
        claims = json.loads(claims_call.kwargs['Body'])
        assert len(claims) == 1

    def test_cap_at_40_claims(self):
        responses = iter([VERIFIABLE_RESPONSE] * 50 + [NON_VERIFIABLE_RESPONSE] * 10)
        bedrock = mock.MagicMock()
        bedrock.converse.side_effect = lambda **kw: {
            'output': {'message': {'content': [{'text': next(responses)}]}}
        }
        call_count = [0]

        def embed_distinct(**kwargs):
            call_count[0] += 1
            emb = [float(call_count[0])] + [0.0] * 1023
            return {'body': mock.MagicMock(read=lambda: json.dumps({'embedding': emb}).encode())}

        bedrock.invoke_model.side_effect = embed_distinct
        s3 = _make_s3_mock('. '.join(f'Sentence {i}' for i in range(55)))

        with mock.patch.object(claim_extractor_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_extractor_handler, 's3_client', s3):
            result = claim_extractor_handler.lambda_handler(BASE_EVENT, None)

        claims_call = next(
            c for c in s3.put_object.call_args_list
            if c.kwargs['Key'] == 'summaries/job-test-001/claims.json'
        )
        claims = json.loads(claims_call.kwargs['Body'])
        assert len(claims) <= 40

    def test_claims_key_in_return(self):
        bedrock = _make_bedrock_mock(VERIFIABLE_RESPONSE)
        s3 = _make_s3_mock()

        with mock.patch.object(claim_extractor_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_extractor_handler, 's3_client', s3):
            result = claim_extractor_handler.lambda_handler(BASE_EVENT, None)

        assert 'claims_key' in result

    def test_summary_key_in_return(self):
        bedrock = _make_bedrock_mock(VERIFIABLE_RESPONSE)
        s3 = _make_s3_mock()

        with mock.patch.object(claim_extractor_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_extractor_handler, 's3_client', s3):
            result = claim_extractor_handler.lambda_handler(BASE_EVENT, None)

        assert 'summary_key' in result
        assert result['summary_key'].endswith('pre_render.txt')
