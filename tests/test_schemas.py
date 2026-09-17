"""Validates JSON schemas against known-good and known-bad fixture documents."""
import json
from pathlib import Path

import jsonschema
import pytest

SCHEMAS_DIR = Path(__file__).parent.parent / 'schemas'


def load_schema(name):
    with open(SCHEMAS_DIR / name) as f:
        return json.load(f)


LAB_RESULT_VALID = {
    'patient_id': 'P-001',
    'test_date': '2025-01-15',
    'ordering_provider': 'Dr. Smith',
    'test_panels': [
        {
            'panel_name': 'Complete Blood Count',
            'results': [
                {'name': 'Hemoglobin', 'value': '13.5', 'unit': 'g/dL', 'reference_range': '12.0-16.0', 'flag': None},
                {'name': 'WBC', 'value': '11.2', 'unit': '10^3/uL', 'reference_range': '4.5-11.0', 'flag': 'H'},
            ],
        }
    ],
    'interpretation': 'Mild leukocytosis.',
    'notes': None,
}

INJURY_DOC_VALID = {
    'patient_id': 'P-002',
    'incident_date': '2025-03-10',
    'body_regions_affected': ['right knee', 'lower back'],
    'mechanism_of_injury': 'Slip and fall',
    'severity': 'moderate',
    'imaging_findings': 'No fracture identified on X-ray.',
    'treatment_plan': 'Rest, ice, anti-inflammatories.',
    'work_status': 'Light duty only.',
    'notes': None,
}

DOCTORS_NOTES_VALID = {
    'patient_id': 'P-003',
    'visit_date': '2025-04-01',
    'provider': 'Dr. Jones',
    'chief_complaint': 'Persistent cough for 2 weeks.',
    'history_of_present_illness': 'Patient reports productive cough beginning 2 weeks ago.',
    'physical_exam_findings': 'Mild crackles at left base.',
    'assessment': 'Community-acquired pneumonia.',
    'plan': 'Amoxicillin 500mg TID x 7 days.',
    'medications_changed': ['Added: Amoxicillin 500mg TID'],
    'follow_up': 'Return in 1 week if not improved.',
}

VISIT_ASSESSMENT_VALID = {
    'patient_id': 'P-004',
    'visit_date': '2025-05-20',
    'visit_type': 'follow_up',
    'functional_status': 'Ambulating without assist, mild limitations with stairs.',
    'pain_score': 3,
    'goals_progress': 'Achieved 80% of strength goals.',
    'barriers': None,
    'plan_updates': 'Progress to pool therapy next session.',
}

PSYCH_EVAL_VALID = {
    'patient_id': 'P-005',
    'eval_date': '2025-06-01',
    'evaluator': 'Dr. Brown, PsyD',
    'presenting_concerns': 'Referred for evaluation of depression and anxiety following workplace injury.',
    'mental_status_summary': 'Alert and oriented. Affect restricted. Mood dysthymic. Thought process linear.',
    'diagnostic_impressions': 'Major Depressive Disorder, moderate, F32.1. Adjustment Disorder with anxiety, F43.22.',
    'risk_assessment': 'Denies active suicidal or homicidal ideation. No plan or intent.',
    'recommendations': 'Weekly cognitive behavioral therapy. Psychiatric consultation for medication evaluation.',
}


class TestLabResultSchema:
    schema = load_schema('lab_result_schema.json')

    def test_valid_document(self):
        jsonschema.validate(LAB_RESULT_VALID, self.schema)

    def test_missing_required_patient_id(self):
        doc = {**LAB_RESULT_VALID}
        del doc['patient_id']
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_missing_required_test_panels(self):
        doc = {**LAB_RESULT_VALID}
        del doc['test_panels']
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_empty_panels_array_rejected(self):
        doc = {**LAB_RESULT_VALID, 'test_panels': []}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_null_interpretation_allowed(self):
        doc = {**LAB_RESULT_VALID, 'interpretation': None}
        jsonschema.validate(doc, self.schema)

    def test_additional_properties_rejected(self):
        doc = {**LAB_RESULT_VALID, 'unexpected_field': 'value'}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)


class TestInjuryDocSchema:
    schema = load_schema('injury_doc_schema.json')

    def test_valid_document(self):
        jsonschema.validate(INJURY_DOC_VALID, self.schema)

    def test_invalid_severity_enum(self):
        doc = {**INJURY_DOC_VALID, 'severity': 'catastrophic'}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_empty_body_regions_rejected(self):
        doc = {**INJURY_DOC_VALID, 'body_regions_affected': []}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_null_imaging_allowed(self):
        doc = {**INJURY_DOC_VALID, 'imaging_findings': None}
        jsonschema.validate(doc, self.schema)


class TestDoctorsNotesSchema:
    schema = load_schema('doctors_notes_schema.json')

    def test_valid_document(self):
        jsonschema.validate(DOCTORS_NOTES_VALID, self.schema)

    def test_null_medications_changed_allowed(self):
        doc = {**DOCTORS_NOTES_VALID, 'medications_changed': None}
        jsonschema.validate(doc, self.schema)

    def test_missing_plan_rejected(self):
        doc = {**DOCTORS_NOTES_VALID}
        del doc['plan']
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)


class TestVisitAssessmentSchema:
    schema = load_schema('visit_assessment_schema.json')

    def test_valid_document(self):
        jsonschema.validate(VISIT_ASSESSMENT_VALID, self.schema)

    def test_invalid_visit_type(self):
        doc = {**VISIT_ASSESSMENT_VALID, 'visit_type': 'emergency'}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_pain_score_out_of_range(self):
        doc = {**VISIT_ASSESSMENT_VALID, 'pain_score': 11}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_null_pain_score_allowed(self):
        doc = {**VISIT_ASSESSMENT_VALID, 'pain_score': None}
        jsonschema.validate(doc, self.schema)


class TestPsychEvalSchema:
    schema = load_schema('psych_eval_schema.json')

    def test_valid_document(self):
        jsonschema.validate(PSYCH_EVAL_VALID, self.schema)

    def test_null_risk_assessment_allowed(self):
        doc = {**PSYCH_EVAL_VALID, 'risk_assessment': None}
        jsonschema.validate(doc, self.schema)

    def test_missing_evaluator_rejected(self):
        doc = {**PSYCH_EVAL_VALID}
        del doc['evaluator']
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)
