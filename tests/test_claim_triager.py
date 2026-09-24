"""Unit tests for the claim_triager Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

HANDLER_PATH = Path(__file__).parent.parent / 'lambda' / 'claim_triager' / 'handler.py'

_spec = importlib.util.spec_from_file_location('claim_triager_handler', HANDLER_PATH)
claim_triager_handler = importlib.util.module_from_spec(_spec)

with mock.patch.dict('os.environ', {
    'UPLOAD_BUCKET': 'upload-bucket',
    'SUMMARIES_BUCKET': 'summaries-bucket',
    'CHEAP_MODEL_ID': 'au.anthropic.claude-haiku-test',
    'EMBEDDING_MODEL_ID': 'amazon.titan-embed-text-v2:0',
    'TRIAGE_SIMILARITY_THRESHOLD': '0.55',
}):
    _spec.loader.exec_module(claim_triager_handler)


BASE_EVENT = {
    'job_id': 'job-triage-001',
    'bucket': 'upload-bucket',
    'key': 'uploads/job-triage-001/doc.txt',
    'summary_key': 'summaries/job-triage-001/pre_render.txt',
    'claims_key': 'summaries/job-triage-001/claims.json',
}

CLAIMS = ['Patient P-001 had Hgb of 13.5 g/dL.', 'Test was ordered on 2025-01-15.', 'CBC panel was normal.']
SUPPORTED_VERDICT = json.dumps({'verdict': 'supported', 'evidence_quote': 'Hgb 13.5 g/dL', 'reason': 'matches'})
EMBEDDING = json.dumps({'embedding': [0.1] * 1024})


def _make_s3_mock(source_text='Source document. ' * 200, claims=None):
    if claims is None:
        claims = CLAIMS
    s3 = mock.MagicMock()

    def get_object_side_effect(Bucket, Key):
        if 'claims' in Key:
            return {'Body': mock.MagicMock(read=lambda: json.dumps(claims).encode())}
        return {'Body': mock.MagicMock(read=lambda: source_text.encode())}

    s3.get_object.side_effect = get_object_side_effect
    return s3


def _make_bedrock_mock():
    bedrock = mock.MagicMock()
    bedrock.converse.return_value = {
        'output': {'message': {'content': [{'text': SUPPORTED_VERDICT}]}}
    }
    bedrock.invoke_model.return_value = {
        'body': mock.MagicMock(read=lambda: EMBEDDING.encode())
    }
    return bedrock


class TestClaimTriager:
    def test_each_claim_gets_verdict(self):
        bedrock = _make_bedrock_mock()
        s3 = _make_s3_mock()

        with mock.patch.object(claim_triager_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_triager_handler, 's3_client', s3):
            result = claim_triager_handler.lambda_handler(BASE_EVENT, None)

        triage_call = next(
            c for c in s3.put_object.call_args_list
            if 'triage.json' in c.kwargs['Key']
        )
        verdicts = json.loads(triage_call.kwargs['Body'])
        assert len(verdicts) == len(CLAIMS)

    def test_top_passage_similarity_present(self):
        bedrock = _make_bedrock_mock()
        s3 = _make_s3_mock()

        with mock.patch.object(claim_triager_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_triager_handler, 's3_client', s3):
            claim_triager_handler.lambda_handler(BASE_EVENT, None)

        triage_call = next(
            c for c in s3.put_object.call_args_list
            if 'triage.json' in c.kwargs['Key']
        )
        verdicts = json.loads(triage_call.kwargs['Body'])
        for v in verdicts:
            assert 'top_passage_similarity' in v
            assert isinstance(v['top_passage_similarity'], float)

    def test_source_chunked_correctly(self):
        source_text = 'A' * 2000
        bedrock = _make_bedrock_mock()
        s3 = _make_s3_mock(source_text=source_text, claims=['One claim.'])

        with mock.patch.object(claim_triager_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_triager_handler, 's3_client', s3):
            claim_triager_handler.lambda_handler(BASE_EVENT, None)

        embed_calls = bedrock.invoke_model.call_args_list
        embed_texts = [json.loads(c.kwargs['body'])['inputText'] for c in embed_calls]
        passage_texts = [t for t in embed_texts if len(t) >= 100]
        assert len(passage_texts) >= 3

    def test_triage_key_in_return(self):
        bedrock = _make_bedrock_mock()
        s3 = _make_s3_mock()

        with mock.patch.object(claim_triager_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_triager_handler, 's3_client', s3):
            result = claim_triager_handler.lambda_handler(BASE_EVENT, None)

        assert 'triage_key' in result
