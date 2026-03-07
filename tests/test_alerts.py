import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_feedback_modal_on_submit_saves_to_db(tmp_path):
    """FeedbackModal.on_submit saves valid feedback to DB."""
    import db
    db.DB_PATH = str(tmp_path / "test.db")
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
    assert row["flavor_notes"] == "sweet and chocolatey"
    assert row["bean_name"] == "Ethiopia Yirgacheffe"
    assert row["roaster"] == "Blue Bottle"
    interaction.response.defer.assert_called_once_with(ephemeral=True)


@pytest.mark.asyncio
async def test_feedback_modal_invalid_score_rejected(tmp_path):
    """FeedbackModal.on_submit rejects scores outside 1-10."""
    import db
    db.DB_PATH = str(tmp_path / "test.db")
    await db.init_db()

    from bot.cogs.alerts import FeedbackModal
    modal = FeedbackModal("shot-999")
    modal.flavor_score = MagicMock(value="0")  # invalid
    modal.flavor_notes = MagicMock(value="")
    modal.bean_name = MagicMock(value="")
    modal.roaster = MagicMock(value="")
    modal.grind_dose_yield = MagicMock(value="")

    interaction = AsyncMock()
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()

    await modal.on_submit(interaction)

    # Should have sent an error, not saved to DB
    interaction.followup.send.assert_called_once()
    error_msg = interaction.followup.send.call_args[0][0]
    assert "1" in error_msg and "10" in error_msg  # mentions the valid range

    # Nothing saved to DB
    async with db.get_db() as conn:
        async with conn.execute("SELECT COUNT(*) FROM feedback WHERE shot_id='shot-999'") as cur:
            count = (await cur.fetchone())[0]
    assert count == 0


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
