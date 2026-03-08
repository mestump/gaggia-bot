import asyncio
import argparse
import logging
import logging.handlers
import os
import signal
import aiohttp
import config
import db
from monitor.poller import ShotPoller
from bot.client import create_bot, load_cogs

os.makedirs("./data", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            "./data/gaggia-bot.log", maxBytes=10*1024*1024, backupCount=5
        )
    ]
)
logger = logging.getLogger(__name__)

async def run():
    await db.init_db()
    bot = create_bot()
    await load_cogs(bot)

    # Wire feedback callback: alerts → recommendations
    alerts_cog = bot.get_cog("Alerts")
    recs_cog = bot.get_cog("Recommendations")

    async def on_feedback_saved(shot_id: str):
        """Called after feedback is saved — fetches context and enqueues recommendation."""
        try:
            async with db.get_db() as conn:
                # Get shot data
                async with conn.execute(
                    "SELECT id, duration_s, profile_name, timestamp FROM shots WHERE id=?",
                    (shot_id,)
                ) as cur:
                    shot_row = await cur.fetchone()
                # Get feedback for bean_name
                async with conn.execute(
                    "SELECT bean_name FROM feedback WHERE shot_id=?",
                    (shot_id,)
                ) as cur:
                    fb_row = await cur.fetchone()

            if not shot_row or not fb_row or not fb_row["bean_name"]:
                logger.debug("Skipping recommendation: missing shot or feedback for %s", shot_id)
                return

            last_shot = dict(shot_row)
            bean_name = fb_row["bean_name"]

            # Fetch current device profile (best-effort, empty dict on failure)
            profile = {}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://{config.GAGGIA_IP}/api/profile",
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        if resp.status == 200:
                            profile = await resp.json()
            except Exception:
                pass  # profile stays {}

            if recs_cog:
                await recs_cog.enqueue_recommendation(shot_id, bean_name, last_shot, profile)
        except Exception as e:
            logger.error("on_feedback_saved failed for shot %s: %s", shot_id, e)

    commands_cog = bot.get_cog("Commands")
    if alerts_cog and recs_cog:
        alerts_cog.set_feedback_callback(on_feedback_saved)
        if commands_cog:
            commands_cog.set_feedback_callback(on_feedback_saved)
    else:
        logger.warning("Could not wire feedback callback — alerts_cog=%s, recs_cog=%s", alerts_cog, recs_cog)

    async def on_new_shot(event: dict):
        alerts_cog = bot.get_cog("Alerts")
        if alerts_cog:
            await alerts_cog.enqueue_shot(event)

    poller = ShotPoller(config.GAGGIA_IP, on_shot=on_new_shot)

    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    poller_task = asyncio.create_task(poller.run())
    bot_task = asyncio.create_task(bot.start(config.DISCORD_BOT_TOKEN))
    stop_task = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        [poller_task, bot_task, stop_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    poller.stop()
    await bot.close()
    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    logger.info("GaggiaMate bot shut down cleanly.")

async def check_mode():
    await db.init_db()
    print(f"[OK] DB initialized at {config.DB_PATH}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{config.GAGGIA_IP}/api/status",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                print(f"[OK] Device reachable: HTTP {resp.status}")
    except Exception as e:
        print(f"[WARN] Device not reachable: {e}")
    print("[OK] Config loaded — all checks complete")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        asyncio.run(check_mode())
    else:
        asyncio.run(run())
