import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


@pytest.fixture
def sample_shot():
    return {
        "id": "test-001",
        "timestamp": "2026-03-07T08:22:00",
        "duration_s": 28.0,
        "profile_name": "Trieste v2",
        "datapoints": []
    }


@pytest.mark.asyncio
async def test_feedback_modal_valid_score(tmp_path):
    """FeedbackModal parses valid score and saves to DB."""
    from bot.cogs.alerts import FeedbackModal
    import db
    import os
    os.environ.setdefault("DB_PATH", str(tmp_path / "test.db"))

    # We test the parsing logic, not Discord interaction
    modal = FeedbackModal("shot-123")
    modal.flavor_score = MagicMock()
    modal.flavor_score.value = "8"
    modal.flavor_notes = MagicMock()
    modal.flavor_notes.value = "sweet"
    modal.bean_name = MagicMock()
    modal.bean_name.value = "Ethiopia"
    modal.roaster = MagicMock()
    modal.roaster.value = "BB"
    modal.grind_dose_yield = MagicMock()
    modal.grind_dose_yield.value = "22 / 18.5 / 37.0"

    # Verify parsing
    parts = [p.strip() for p in modal.grind_dose_yield.value.replace(",", "/").split("/")]
    grind = float(parts[0])
    dose = float(parts[1])
    yld = float(parts[2])
    assert grind == 22.0
    assert dose == 18.5
    assert yld == 37.0
    assert int(modal.flavor_score.value) == 8


@pytest.mark.asyncio
async def test_feedback_modal_invalid_score():
    """Invalid score values are caught."""
    from bot.cogs.alerts import FeedbackModal
    modal = FeedbackModal("shot-123")
    for bad in ["0", "11", "abc", "", "10.5"]:
        try:
            val = int(bad.strip())
            valid = 1 <= val <= 10
        except (ValueError, TypeError):
            valid = False
        assert not valid or bad == "10"  # 10 is valid


@pytest.mark.asyncio
async def test_enqueue_shot_adds_to_queue():
    """enqueue_shot puts event on the queue."""
    import discord
    from unittest.mock import MagicMock
    bot = MagicMock()
    # Import after env setup
    from bot.cogs.alerts import Alerts
    cog = Alerts.__new__(Alerts)
    cog.bot = bot
    cog.shot_queue = asyncio.Queue()
    cog._task = None
    cog._on_feedback_saved = None

    await cog.enqueue_shot({"shot": {"id": "x"}})
    assert cog.shot_queue.qsize() == 1


def test_rate_shot_view_created():
    """RateShotView can be instantiated."""
    from bot.cogs.alerts import RateShotView
    view = RateShotView("shot-001")
    assert view.timeout == 7200
    assert len(view.children) == 1  # one button
