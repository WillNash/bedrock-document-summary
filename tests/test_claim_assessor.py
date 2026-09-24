"""Unit tests for the claim_assessor Lambda handler."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

HANDLER_PATH = Path(__file__).parent.parent / 'lambda' / 'claim_assessor' / 'handler.py'

_spec = importlib.util.spec_from_file_location('claim_assessor_handler', HANDLER_PATH)
claim_assessor_handler = importlib.util.module_from_spec(_spec)

with mock.patch.dict('os.environ', {
    'SUMMARIES_BUCKET': 'summaries-bucket',
    'CHEAP_MODEL_ID': 'au.anthropic.claude-haiku-test',
    'EXPENSIVE_MODEL_ID': 'au.anthropic.claude-sonnet-test',
    'TRIAGE_SIMILARITY_THRESHOLD': '0.55',
}):
    _spec.loader.exec_module(claim_assessor_handler)


BASE_EVENT = {
    'job_id': 'job-assess-001',
    'bucket': 'upload-bucket',
    'key': 'uploads/job-assess-001/doc.txt',
    'summary_key': 'summaries/job-assess-001/pre_render.txt',
    'claims_key': 'summaries/job-assess-001/claims.json',
    'triage_key': 'summaries/job-assess-001/triage.json',
}

SONNET_VERDICT = json.dumps({'verdict': 'supported', 'evidence_quote': 'Hgb 13.5', 'reason': 'confirmed'})


def _make_s3_mock(triage_data):
    s3 = mock.MagicMock()

    def get_object_side_effect(Bucket, Key):
        if 'triage' in Key:
            return {'Body': mock.MagicMock(read=lambda: json.dumps(triage_data).encode())}
        return {'Body': mock.MagicMock(read=lambda: b'Source document content.')}

    s3.get_object.side_effect = get_object_side_effect
    return s3


def _make_bedrock_mock():
    bedrock = mock.MagicMock()
    bedrock.converse.return_value = {
        'output': {'message': {'content': [{'text': SONNET_VERDICT}]}}
    }
    return bedrock


class TestClaimAssessor:
    def test_contradicted_claim_escalated_to_sonnet(self):
        triage = [{'claim': 'Some claim.', 'verdict': 'contradicted', 'evidence_quote': 'evidence', 'reason': 'conflict', 'top_passage_similarity': 0.8}]
        bedrock = _make_bedrock_mock()
        s3 = _make_s3_mock(triage)

        with mock.patch.object(claim_assessor_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_assessor_handler, 's3_client', s3):
            claim_assessor_handler.lambda_handler(BASE_EVENT, None)

        calls = bedrock.converse.call_args_list
        assert any(c.kwargs['modelId'] == 'au.anthropic.claude-sonnet-test' for c in calls)

    def test_supported_high_similarity_not_escalated(self):
        triage = [{'claim': 'Good claim.', 'verdict': 'supported', 'evidence_quote': 'evidence', 'reason': 'ok', 'top_passage_similarity': 0.9}]
        bedrock = _make_bedrock_mock()
        s3 = _make_s3_mock(triage)

        with mock.patch.object(claim_assessor_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_assessor_handler, 's3_client', s3):
            claim_assessor_handler.lambda_handler(BASE_EVENT, None)

        assert bedrock.converse.call_count == 0

    def test_low_similarity_escalated_regardless_of_verdict(self):
        triage = [{'claim': 'Low-sim claim.', 'verdict': 'supported', 'evidence_quote': '', 'reason': 'maybe', 'top_passage_similarity': 0.40}]
        bedrock = _make_bedrock_mock()
        s3 = _make_s3_mock(triage)

        with mock.patch.object(claim_assessor_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_assessor_handler, 's3_client', s3):
            claim_assessor_handler.lambda_handler(BASE_EVENT, None)

        assert bedrock.converse.call_count == 1
        assert bedrock.converse.call_args.kwargs['modelId'] == 'au.anthropic.claude-sonnet-test'

    def test_verdicts_key_in_return(self):
        triage = [{'claim': 'A claim.', 'verdict': 'supported', 'evidence_quote': '', 'reason': 'ok', 'top_passage_similarity': 0.9}]
        bedrock = _make_bedrock_mock()
        s3 = _make_s3_mock(triage)

        with mock.patch.object(claim_assessor_handler, 'bedrock_runtime', bedrock), \
             mock.patch.object(claim_assessor_handler, 's3_client', s3):
            result = claim_assessor_handler.lambda_handler(BASE_EVENT, None)

        assert 'verdicts_key' in result
