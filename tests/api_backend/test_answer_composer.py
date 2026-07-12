from backend.app.questions.composer import AnswerComposer


def test_answer_composer_what_changed() -> None:
    response = AnswerComposer().compose(
        'what_changed',
        [
            {'id': 'a', 'signal_type': 'baseline_shift', 'severity': 'high', 'confidence': 0.9, 'importance_score': 0.9, 'evidence': {}},
            {'id': 'b', 'signal_type': 'trend', 'severity': 'medium', 'confidence': 0.8, 'importance_score': 0.8, 'evidence': {}},
        ],
    )
    assert response.question_id == 'what_changed'
    assert response.status == 'needs_attention'
    assert response.evidence_signal_ids
