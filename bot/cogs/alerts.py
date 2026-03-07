import discord
from discord.ext import commands
from discord import ui
import asyncio
import logging
from bot.embeds import shot_embed
from grapher.shot_graph import generate_shot_graph
import db
import config

logger = logging.getLogger(__name__)


class FeedbackModal(ui.Modal, title="Rate This Shot"):
    flavor_score = ui.TextInput(
        label="Flavor Score (1-10)",
        placeholder="8",
        max_length=2,
        required=True,
    )
    flavor_notes = ui.TextInput(
        label="Tasting Notes",
        placeholder="Sweet, chocolate, mild acidity",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=500,
    )
    bean_name = ui.TextInput(
        label="Bean Name",
        placeholder="Ethiopia Yirgacheffe",
        required=False,
        max_length=100,
    )
    grind_dose_yield = ui.TextInput(
        label="Grind / Dose (g) / Yield (g)",
        placeholder="22 / 18.5 / 37.0",
        required=False,
        max_length=30,
    )
    roaster = ui.TextInput(
        label="Roaster",
        placeholder="Blue Bottle",
        required=False,
        max_length=100,
    )

    def __init__(self, shot_id: str, on_feedback_saved=None):
        super().__init__()
        self.shot_id = shot_id
        self.on_feedback_saved = on_feedback_saved  # optional async callback

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Validate score
        try:
            score = int(self.flavor_score.value.strip())
            if not (1 <= score <= 10):
                raise ValueError("out of range")
        except (ValueError, TypeError):
            await interaction.followup.send(
                "Flavor score must be a number between 1 and 10.", ephemeral=True
            )
            return

        # Parse grind/dose/yield — format: "grind / dose / yield" (flexible)
        grind, dose, yld = None, None, None
        gdystr = self.grind_dose_yield.value.strip()
        if gdystr:
            parts = [p.strip() for p in gdystr.replace(",", "/").split("/")]
            try:
                if len(parts) >= 1 and parts[0]:
                    grind = float(parts[0])
                if len(parts) >= 2 and parts[1]:
                    dose = float(parts[1])
                if len(parts) >= 3 and parts[2]:
                    yld = float(parts[2])
            except ValueError:
                pass  # non-fatal — save what we can

        async with db.get_db() as conn:
            await conn.execute(
                """INSERT INTO feedback
                   (shot_id, flavor_score, flavor_notes, bean_name, roaster, grind_size, dose_g, yield_g)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.shot_id,
                    score,
                    self.flavor_notes.value.strip() or None,
                    self.bean_name.value.strip() or None,
                    self.roaster.value.strip() or None,
                    grind,
                    dose,
                    yld,
                )
            )
            await conn.commit()

        await interaction.followup.send(
            f"Thanks! Score **{score}/10** saved. Analysis will run automatically.",
            ephemeral=True,
        )

        # Non-blocking analysis trigger
        if self.on_feedback_saved:
            asyncio.create_task(self._trigger_analysis())

    async def _trigger_analysis(self):
        try:
            if self.on_feedback_saved:
                await self.on_feedback_saved(self.shot_id)
        except Exception as e:
            logger.error("Analysis trigger failed for shot %s: %s", self.shot_id, e)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error("FeedbackModal error for shot %s: %s", self.shot_id, error)
        try:
            await interaction.followup.send("An error occurred saving feedback.", ephemeral=True)
        except Exception:
            pass


class RateShotView(ui.View):
    def __init__(self, shot_id: str, on_feedback_saved=None):
        super().__init__(timeout=7200)  # 2 hour window to rate
        self.shot_id = shot_id
        self.on_feedback_saved = on_feedback_saved

    @ui.button(label="Rate This Shot", style=discord.ButtonStyle.primary)
    async def rate(self, interaction: discord.Interaction, button: ui.Button):
        modal = FeedbackModal(self.shot_id, on_feedback_saved=self.on_feedback_saved)
        await interaction.response.send_modal(modal)

    async def on_timeout(self):
        # Disable button after timeout — view persists but button greys out
        for item in self.children:
            item.disabled = True


class Alerts(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.shot_queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._on_feedback_saved = None  # set by main.py to wire recommendations

    async def cog_load(self):
        self._task = asyncio.create_task(self._process_shots())

    async def cog_unload(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def enqueue_shot(self, event: dict):
        """Called by the poller when a new shot is detected."""
        await self.shot_queue.put(event)

    def set_feedback_callback(self, callback):
        """Wire in a callback to trigger analysis after feedback saved."""
        self._on_feedback_saved = callback

    async def _get_alert_channel(self) -> discord.TextChannel | None:
        # DB config takes priority over env var
        try:
            async with db.get_db() as conn:
                async with conn.execute(
                    "SELECT value FROM config WHERE key='alert_channel_id'"
                ) as cur:
                    row = await cur.fetchone()
            if row and row["value"]:
                ch_id = int(row["value"])
                return self.bot.get_channel(ch_id)
        except Exception as e:
            logger.warning("Could not read alert channel from DB: %s", e)

        # Fallback to env var
        if config.DISCORD_ALERT_CHANNEL_ID:
            return self.bot.get_channel(config.DISCORD_ALERT_CHANNEL_ID)
        return None

    async def _process_shots(self):
        while True:
            event = await self.shot_queue.get()
            try:
                await self._post_shot_alert(event)
            except Exception as e:
                logger.error("Failed to post shot alert: %s", e, exc_info=True)
            finally:
                self.shot_queue.task_done()

    async def _post_shot_alert(self, event: dict):
        shot = event.get("shot", event)  # support both {shot: ...} and bare shot dict
        shot_id = str(shot.get("id", "unknown"))

        channel = await self._get_alert_channel()
        if not channel:
            logger.warning("No alert channel configured — shot %s not posted", shot_id)
            return

        # Generate graph in thread pool to avoid blocking event loop
        loop = asyncio.get_running_loop()
        try:
            graph_path = await loop.run_in_executor(None, generate_shot_graph, shot)
        except Exception as e:
            logger.error("Graph generation failed for shot %s: %s", shot_id, e)
            graph_path = None

        # Update graph_path in DB
        if graph_path:
            async with db.get_db() as conn:
                await conn.execute(
                    "UPDATE shots SET graph_path=? WHERE id=?",
                    (str(graph_path), shot_id)
                )
                await conn.commit()

        embed = shot_embed(shot)
        view = RateShotView(shot_id, on_feedback_saved=self._on_feedback_saved)

        if graph_path and graph_path.exists():
            file = discord.File(str(graph_path), filename="shot.png")
            embed.set_image(url="attachment://shot.png")
            msg = await channel.send(embed=embed, file=file, view=view)
        else:
            msg = await channel.send(embed=embed, view=view)

        # Record posted_at
        async with db.get_db() as conn:
            await conn.execute(
                "UPDATE shots SET posted_at=datetime('now') WHERE id=?",
                (shot_id,)
            )
            await conn.commit()

        logger.info("Shot alert posted for shot %s (msg=%s)", shot_id, msg.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Alerts(bot))
