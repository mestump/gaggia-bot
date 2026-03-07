import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_enqueue_recommendation_adds_to_queue():
    """enqueue_recommendation puts an item on the rec_queue."""
    from bot.cogs.recommendations import Recommendations

    bot = MagicMock()
    cog = Recommendations.__new__(Recommendations)
    cog.bot = bot
    cog.rec_queue = asyncio.Queue()

    await cog.enqueue_recommendation("shot-1", "Ethiopia", {"id": "shot-1"}, {"name": "default"})

    assert cog.rec_queue.qsize() == 1
    item = await cog.rec_queue.get()
    assert item == ("shot-1", "Ethiopia", {"id": "shot-1"}, {"name": "default"})


@pytest.mark.asyncio
async def test_generate_and_post_returns_early_on_insufficient_data():
    """_generate_and_post returns early when compute_trends reports insufficient data."""
    from analysis.trends import TrendReport
    from bot.cogs.recommendations import Recommendations

    insufficient = TrendReport(
        bean_name="Ethiopia",
        n_shots=1,
        score_vs_ratio=None,
        score_vs_grind=None,
        score_vs_dose=None,
        duration_stddev=None,
        staleness_slope=None,
        insufficient_data=True,
    )

    bot = MagicMock()
    cog = Recommendations.__new__(Recommendations)
    cog.bot = bot
    cog.rec_queue = asyncio.Queue()

    with patch("bot.cogs.recommendations.compute_trends", new=AsyncMock(return_value=insufficient)):
        # Should return without error and without hitting DB
        result = await cog._generate_and_post("shot-1", "Ethiopia", {}, {})

    assert result is None  # early return
