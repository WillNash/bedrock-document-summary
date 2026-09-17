"""Unit tests for Jinja2 summary templates."""
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent.parent / 'templates'

# Mirrors the handler's Environment config — autoescaping disabled for plain text.
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape([]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name, data):
    return jinja_env.get_template(template_name).render(**data)


class TestLabResultTemplate:
    DATA = {
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

    def test_contains_patient_id(self):
        out = render('lab_result.j2', self.DATA)
        assert 'P-001' in out

    def test_contains_panel_name(self):
        out = render('lab_result.j2', self.DATA)
        assert 'COMPLETE BLOOD COUNT' in out.upper()

    def test_contains_result_value(self):
        out = render('lab_result.j2', self.DATA)
        assert '13.5' in out

    def test_flag_displayed(self):
        out = render('lab_result.j2', self.DATA)
        assert '[H]' in out

    def test_null_notes_shows_none(self):
        out = render('lab_result.j2', self.DATA)
        assert 'None.' in out

    def test_section_headers_present(self):
        out = render('lab_result.j2', self.DATA)
        assert 'INTERPRETATION' in out
        assert 'NOTES' in out


class TestInjuryDocTemplate:
    DATA = {
        'patient_id': 'P-002',
        'incident_date': '2025-03-10',
        'body_regions_affected': ['right knee', 'lower back'],
        'mechanism_of_injury': 'Slip and fall',
        'severity': 'moderate',
        'imaging_findings': None,
        'treatment_plan': 'Rest and ice.',
        'work_status': None,
        'notes': None,
    }

    def test_contains_mechanism(self):
        out = render('injury_doc.j2', self.DATA)
        assert 'Slip and fall' in out

    def test_body_regions_listed(self):
        out = render('injury_doc.j2', self.DATA)
        assert 'right knee' in out
        assert 'lower back' in out

    def test_null_imaging_shows_not_documented(self):
        out = render('injury_doc.j2', self.DATA)
        assert 'No imaging performed' in out

    def test_section_headers(self):
        out = render('injury_doc.j2', self.DATA)
        assert 'INCIDENT OVERVIEW' in out
        assert 'TREATMENT PLAN' in out


class TestDoctorsNotesTemplate:
    DATA = {
        'patient_id': 'P-003',
        'visit_date': '2025-04-01',
        'provider': 'Dr. Jones',
        'chief_complaint': 'Persistent cough.',
        'history_of_present_illness': 'Two weeks of productive cough.',
        'physical_exam_findings': 'Crackles at left base.',
        'assessment': 'Pneumonia.',
        'plan': 'Antibiotics.',
        'medications_changed': ['Added: Amoxicillin'],
        'follow_up': 'Return in 1 week.',
    }

    def test_chief_complaint_present(self):
        out = render('doctors_notes.j2', self.DATA)
        assert 'Persistent cough.' in out

    def test_medications_listed(self):
        out = render('doctors_notes.j2', self.DATA)
        assert 'Amoxicillin' in out

    def test_section_headers(self):
        out = render('doctors_notes.j2', self.DATA)
        assert 'CHIEF COMPLAINT' in out
        assert 'ASSESSMENT' in out
        assert 'PLAN' in out


class TestVisitAssessmentTemplate:
    DATA = {
        'patient_id': 'P-004',
        'visit_date': '2025-05-20',
        'visit_type': 'follow_up',
        'functional_status': 'Ambulating without assist.',
        'pain_score': 3,
        'goals_progress': 'Good progress.',
        'barriers': None,
        'plan_updates': 'Progress to pool therapy.',
    }

    def test_pain_score_displayed(self):
        out = render('visit_assessment.j2', self.DATA)
        assert '3/10' in out

    def test_visit_type_formatted(self):
        out = render('visit_assessment.j2', self.DATA)
        assert 'Follow Up' in out

    def test_null_barriers_shows_not_documented(self):
        out = render('visit_assessment.j2', self.DATA)
        assert 'No barriers documented' in out

    def test_null_pain_score_shows_not_recorded(self):
        data = {**self.DATA, 'pain_score': None}
        out = render('visit_assessment.j2', data)
        assert 'not recorded' in out


class TestPsychEvalTemplate:
    DATA = {
        'patient_id': 'P-005',
        'eval_date': '2025-06-01',
        'evaluator': 'Dr. Brown, PsyD',
        'presenting_concerns': 'Depression following injury.',
        'mental_status_summary': 'Alert, restricted affect.',
        'diagnostic_impressions': 'Major Depressive Disorder.',
        'risk_assessment': 'Denies SI/HI.',
        'recommendations': 'Weekly CBT.',
    }

    def test_evaluator_present(self):
        out = render('psych_eval.j2', self.DATA)
        assert 'Dr. Brown, PsyD' in out

    def test_section_headers(self):
        out = render('psych_eval.j2', self.DATA)
        assert 'PRESENTING CONCERNS' in out
        assert 'RISK ASSESSMENT' in out
        assert 'RECOMMENDATIONS' in out

    def test_null_risk_shows_not_documented(self):
        data = {**self.DATA, 'risk_assessment': None}
        out = render('psych_eval.j2', data)
        assert 'No formal risk assessment documented' in out
