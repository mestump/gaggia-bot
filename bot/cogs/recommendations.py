import asyncio
import json
import logging

import discord
from discord import ui
from discord.ext import commands

import config
import db
from analysis.trends import compute_trends
from analysis.heuristics import diagnose_shot
from analysis.llm import generate_recommendation
from bot.embeds import recommendation_embed
from profile_patcher import patch_profile

logger = logging.getLogger(__name__)


class ConfirmApplyView(ui.View):
    """Two-button confirmation before writing a profile change to the device."""

    def __init__(self, adjustments: list, rec_id: int):
        super().__init__(timeout=300)
        self.adjustments = adjustments
        self.rec_id = rec_id

    @ui.button(label="Confirm — Apply Changes", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        try:
            await patch_profile(self.adjustments)
            async with db.get_db() as conn:
                await conn.execute(
                    "UPDATE recommendations SET applied=1, applied_at=datetime('now') WHERE id=?",
                    (self.rec_id,),
                )
                await conn.commit()
            await interaction.followup.send("Profile updated on GaggiaMate.")
        except Exception as e:
            logger.error("Failed to apply profile: %s", e)
            await interaction.followup.send(
                f"Failed to apply profile: {e}", ephemeral=True
            )
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Cancelled.", ephemeral=True)
        self.stop()


class ApplyOrSkipView(ui.View):
    """Top-level buttons shown with a recommendation — apply or dismiss."""

    def __init__(self, adjustments: list, rec_id: int):
        super().__init__(timeout=3600)
        self.adjustments = adjustments
        self.rec_id = rec_id

    @ui.button(label="Apply Profile Change", style=discord.ButtonStyle.primary)
    async def apply(self, interaction: discord.Interaction, button: ui.Button):
        view = ConfirmApplyView(self.adjustments, self.rec_id)
        await interaction.response.send_message(
            "This will modify your GaggiaMate profile. Are you sure?",
            view=view,
            ephemeral=True,
        )
        self.stop()

    @ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Recommendation noted but not applied.", ephemeral=True
        )
        self.stop()


class Recommendations(commands.Cog):
    """Cog that consumes an async queue of shot data and posts AI recommendations."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rec_queue: asyncio.Queue = asyncio.Queue()

    async def cog_load(self):
        self._task = asyncio.create_task(self._process_recs())

    async def cog_unload(self):
        self._task.cancel()

    async def enqueue_recommendation(
        self, shot_id: str, bean_name: str, last_shot: dict, profile: dict
    ):
        """Put a new shot onto the recommendation queue."""
        await self.rec_queue.put((shot_id, bean_name, last_shot, profile))

    async def _process_recs(self):
        while True:
            shot_id, bean_name, last_shot, profile = await self.rec_queue.get()
            try:
                await self._generate_and_post(shot_id, bean_name, last_shot, profile)
            except Exception as e:
                logger.error("Recommendation processing failed: %s", e)
            finally:
                self.rec_queue.task_done()

    async def _generate_and_post(self, shot_id, bean_name, last_shot, profile):
        trend = await compute_trends(bean_name)
        if trend.insufficient_data:
            return  # not enough shots yet

        async with db.get_db() as conn:
            async with conn.execute(
                "SELECT f.*, s.duration_s FROM feedback f JOIN shots s ON s.id=f.shot_id WHERE f.shot_id=?",
                (shot_id,),
            ) as cur:
                fb_row = await cur.fetchone()

        if not fb_row:
            logger.warning("No feedback found for shot %s, skipping recommendation", shot_id)
            return

        diagnosis = diagnose_shot(last_shot, dict(fb_row))
        rec = await generate_recommendation(trend, diagnosis, [last_shot], profile)

        async with db.get_db() as conn:
            cur = await conn.execute(
                "INSERT INTO recommendations (shot_id, recommendation, adjustments_json) VALUES (?,?,?)",
                (shot_id, rec["prose"], json.dumps(rec.get("adjustments", []))),
            )
            rec_id = cur.lastrowid
            await conn.commit()

        async with db.get_db() as conn:
            async with conn.execute(
                "SELECT value FROM config WHERE key='alert_channel_id'"
            ) as c:
                row = await c.fetchone()
        ch_id = int(row["value"]) if row else (config.DISCORD_ALERT_CHANNEL_ID or 0)
        channel = self.bot.get_channel(ch_id)
        if not channel:
            return

        embed = recommendation_embed(rec["prose"], rec.get("adjustments", []))
        adjustments = rec.get("adjustments", [])
        if adjustments:
            view = ApplyOrSkipView(adjustments, rec_id)
            await channel.send(embed=embed, view=view)
        else:
            await channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Recommendations(bot))
