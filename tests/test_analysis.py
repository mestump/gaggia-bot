import pytest
from analysis.heuristics import diagnose_shot, ExtractionState


def test_under_extraction_by_notes():
    shot = {"duration_s": 28}
    feedback = {"flavor_score": 4, "flavor_notes": "very sour and thin", "dose_g": 18, "yield_g": 36}
    result = diagnose_shot(shot, feedback)
    assert result.extraction_state == ExtractionState.UNDER


def test_over_extraction_by_notes():
    shot = {"duration_s": 28}
    feedback = {"flavor_score": 4, "flavor_notes": "super bitter and harsh", "dose_g": 18, "yield_g": 36}
    result = diagnose_shot(shot, feedback)
    assert result.extraction_state == ExtractionState.OVER


def test_short_duration_flag():
    shot = {"duration_s": 17}
    feedback = {"flavor_score": 7, "flavor_notes": "ok", "dose_g": 18, "yield_g": 36}
    result = diagnose_shot(shot, feedback)
    assert "channeling" in " ".join(result.flags).lower() or "short" in " ".join(result.flags).lower()


def test_low_brew_ratio_flag():
    shot = {"duration_s": 28}
    feedback = {"flavor_score": 7, "flavor_notes": "ok", "dose_g": 18, "yield_g": 28}  # ratio 1.55
    result = diagnose_shot(shot, feedback)
    assert any("yield" in f.lower() or "ratio" in f.lower() for f in result.suggestions)
