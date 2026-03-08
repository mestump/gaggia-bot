import json
import asyncio
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

from monitor.fetcher import GaggiaMateClient
import db
import config
from bot.embeds import status_embed, shot_embed
from bot.cogs.alerts import RateShotView
from grapher.shot_graph import generate_shot_graph

logger = logging.getLogger(__name__)


class Commands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = GaggiaMateClient(config.GAGGIA_IP)
        self._on_feedback_saved = None  # wired by main.py

    def set_feedback_callback(self, callback):
        self._on_feedback_saved = callback

    @app_commands.command(name="status", description="Show GaggiaMate device status")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                data = await self.client.get_status(session)
            await interaction.followup.send(embed=status_embed(data))
        except Exception as e:
            await interaction.followup.send(f"Error reaching device: {e}", ephemeral=True)

    @app_commands.command(name="history", description="Show last N shots with graphs")
    @app_commands.describe(n="Number of shots (default 3, max 5)")
    async def history(self, interaction: discord.Interaction, n: int = 3):
        await interaction.response.defer()
        n = min(max(n, 1), 5)

        async with db.get_db() as conn:
            async with conn.execute(
                """SELECT s.id, s.timestamp, s.duration_s, s.profile_name,
                          s.raw_json, s.graph_path,
                          f.flavor_score, f.bean_name, f.dose_g, f.yield_g
                   FROM shots s
                   LEFT JOIN feedback f ON f.shot_id = s.id
                   ORDER BY s.timestamp DESC LIMIT ?""",
                (n,)
            ) as cur:
                rows = await cur.fetchall()

        if not rows:
            await interaction.followup.send("No shots recorded yet.")
            return

        loop = asyncio.get_running_loop()

        for row in reversed(rows):  # oldest first so Discord reads top-to-bottom
            shot_id = str(row["id"])

            # Reconstruct shot dict from DB row
            raw = json.loads(row["raw_json"] or "{}")
            shot = {
                "id":           shot_id,
                "timestamp":    row["timestamp"],
                "duration_s":   row["duration_s"],
                "profile_name": row["profile_name"] or "Unknown",
                "datapoints":   raw.get("datapoints", []),
            }

            feedback = None
            if row["flavor_score"] is not None:
                feedback = {
                    "flavor_score": row["flavor_score"],
                    "bean_name":    row["bean_name"],
                    "dose_g":       row["dose_g"],
                    "yield_g":      row["yield_g"],
                }

            # Reuse cached graph or generate a new one
            graph_path = None
            cached = row["graph_path"]
            if cached and Path(cached).exists():
                graph_path = Path(cached)
            else:
                try:
                    graph_path = await loop.run_in_executor(
                        None, generate_shot_graph, shot, feedback
                    )
                    async with db.get_db() as conn:
                        await conn.execute(
                            "UPDATE shots SET graph_path=? WHERE id=?",
                            (str(graph_path), shot_id)
                        )
                        await conn.commit()
                except Exception as e:
                    logger.error("Graph generation failed for shot %s: %s", shot_id, e)

            embed = shot_embed(shot, feedback)
            view = RateShotView(shot_id, on_feedback_saved=self._on_feedback_saved)

            if graph_path and graph_path.exists():
                file = discord.File(str(graph_path), filename="shot.png")
                embed.set_image(url="attachment://shot.png")
                await interaction.followup.send(embed=embed, file=file, view=view)
            else:
                await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="profile", description="Show current active profile name")
    async def profile(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                data = await self.client.get_status(session)
            profile_name = data.get("p", data.get("profile_name", "Unknown"))
            await interaction.followup.send(f"Active profile: **{profile_name}**")
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="set_channel", description="Set the channel for shot alerts")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        async with db.get_db() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES ('alert_channel_id', ?)",
                (str(channel.id),)
            )
            await conn.commit()
        await interaction.followup.send(
            f"Shot alerts will be posted to {channel.mention}", ephemeral=True
        )

    @app_commands.command(name="recommend", description="Force a recommendation based on recent shots")
    async def recommend(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Manual recommendations not yet implemented — feedback will trigger analysis automatically.",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Commands(bot))
