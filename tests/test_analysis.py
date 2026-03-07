import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from analysis.heuristics import diagnose_shot, ExtractionState
from analysis.trends import _pearson, compute_trends
from analysis.llm import _clamp_adjustments


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


# --- _pearson tests ---

def test_pearson_fewer_than_3_returns_none():
    assert _pearson([1.0, 2.0], [3.0, 4.0]) is None


def test_pearson_correlated_returns_float():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [2.0, 4.0, 6.0, 8.0, 10.0]
    result = _pearson(x, y)
    assert isinstance(result, float)
    assert abs(result - 1.0) < 1e-6


# --- _clamp_adjustments tests ---

def test_clamp_adjustments_rejects_exceeding_delta():
    adj = [{"step_name": "Brew", "field": "pressure", "old_value": 6.0, "new_value": 9.0}]  # delta=3.0, limit=1.0
    result = _clamp_adjustments(adj)
    assert result == []


def test_clamp_adjustments_passes_safe_adjustment():
    adj = [{"step_name": "Brew", "field": "pressure", "old_value": 6.0, "new_value": 6.5}]  # delta=0.5, limit=1.0
    result = _clamp_adjustments(adj)
    assert result == adj


# --- compute_trends insufficient_data guard ---

@pytest.mark.asyncio
async def test_compute_trends_insufficient_data():
    mock_rows = [{"duration_s": 28, "flavor_score": 7, "brew_ratio": 2.0, "grind_size": 15, "dose_g": 18, "roast_date": None}]

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=mock_rows)
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=False)

    mock_conn = AsyncMock()
    mock_conn.execute = MagicMock(return_value=mock_cursor)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_db_cm = MagicMock()
    mock_db_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_db_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("db.get_db", return_value=mock_db_cm), \
         patch("config.MIN_SHOTS_FOR_RECOMMENDATION", 5):
        result = await compute_trends("TestBean")

    assert result.insufficient_data is True
    assert result.bean_name == "TestBean"
    assert result.n_shots == 1
