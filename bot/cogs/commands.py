import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
from monitor.fetcher import GaggiaMateClient
import db
import config
from bot.embeds import status_embed

class Commands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = GaggiaMateClient(config.GAGGIA_IP)

    @app_commands.command(name="status", description="Show GaggiaMate device status")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                data = await self.client.get_status(session)
            await interaction.followup.send(embed=status_embed(data))
        except Exception as e:
            await interaction.followup.send(f"Error reaching device: {e}", ephemeral=True)

    @app_commands.command(name="history", description="Show last N shots")
    @app_commands.describe(n="Number of shots (default 5, max 20)")
    async def history(self, interaction: discord.Interaction, n: int = 5):
        await interaction.response.defer()
        n = min(max(n, 1), 20)
        async with db.get_db() as conn:
            async with conn.execute(
                "SELECT id, timestamp, duration_s, profile_name FROM shots ORDER BY timestamp DESC LIMIT ?", (n,)
            ) as cur:
                rows = await cur.fetchall()
        if not rows:
            await interaction.followup.send("No shots recorded yet.")
            return
        lines = [
            f"`{str(r['id'])[:8]}` | {str(r['timestamp'])[:16]} | {r['duration_s']}s | {r['profile_name'] or 'Unknown'}"
            for r in rows
        ]
        await interaction.followup.send("**Recent Shots:**\n" + "\n".join(lines))

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
