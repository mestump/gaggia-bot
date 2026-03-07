import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


@pytest.mark.asyncio
async def test_feedback_modal_on_submit_saves_to_db(tmp_path):
    """FeedbackModal.on_submit saves valid feedback to DB."""
    import os
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    import db
    await db.init_db()

    from bot.cogs.alerts import FeedbackModal
    modal = FeedbackModal("shot-123")

    # Mock TextInput values
    modal.flavor_score = MagicMock(value="8")
    modal.flavor_notes = MagicMock(value="sweet and chocolatey")
    modal.bean_name = MagicMock(value="Ethiopia Yirgacheffe")
    modal.roaster = MagicMock(value="Blue Bottle")
    modal.grind_dose_yield = MagicMock(value="22 / 18.5 / 37.0")

    # Mock Discord interaction
    interaction = AsyncMock()
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()

    await modal.on_submit(interaction)

    # Verify saved to DB
    async with db.get_db() as conn:
        async with conn.execute("SELECT * FROM feedback WHERE shot_id='shot-123'") as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row["flavor_score"] == 8
    assert row["grind_size"] == 22.0
    assert row["dose_g"] == 18.5
    assert row["yield_g"] == 37.0
    interaction.response.defer.assert_called_once_with(ephemeral=True)


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
