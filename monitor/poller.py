"""
ShotPoller — WebSocket listener for GaggiaMate shot detection.

Detection logic:
  Primary:  process.e == True in evt:status payload
  Fallback: mode transition m==1 (Brew) → m==0 (Standby) when process field absent

On shot detected: fetches new SIDX entries not already in DB, saves each, calls on_shot.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional

import aiohttp

from db import get_db
from monitor.fetcher import GaggiaMateClient

logger = logging.getLogger(__name__)

# Mode constants
MODE_STANDBY = 0
MODE_BREW = 1


class ShotPoller:
    def __init__(
        self,
        host: str,
        on_shot: Callable[[dict], Awaitable[None]],
        reconnect_delay: float = 5.0,
    ):
        self.host = host
        self.ws_url = f"ws://{host}/ws"
        self.on_shot = on_shot
        self.reconnect_delay = reconnect_delay
        self._running = False
        self._client = GaggiaMateClient(host)
        self._fetch_lock = asyncio.Lock()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run(self):
        """Connect to WebSocket with reconnect loop."""
        self._running = True
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.ws_url) as ws:
                        logger.info("WebSocket connected to %s", self.ws_url)
                        await self._process_ws(ws)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                if not self._running:
                    break
                logger.warning("WebSocket disconnected: %s — reconnecting in %.1fs", exc, self.reconnect_delay)
                await asyncio.sleep(self.reconnect_delay)
            except Exception as exc:
                if not self._running:
                    break
                logger.error("Unexpected WebSocket error: %s", exc, exc_info=True)
                await asyncio.sleep(self.reconnect_delay)

    def stop(self):
        """Signal the run loop to stop."""
        self._running = False

    # ── Internal WebSocket processor ──────────────────────────────────────────

    async def _process_ws(self, ws) -> None:
        """
        Process messages from an open WebSocket connection.
        Handles both process.e detection and fallback m=1→m=0.
        """
        prev_mode: Optional[int] = None

        async for msg in ws:
            # Support both aiohttp WSMessage objects and plain strings (for tests)
            raw = msg.data if hasattr(msg, "data") else msg
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            if event.get("tp") != "evt:status":
                continue

            current_mode = event.get("m", MODE_STANDBY)
            process = event.get("process", {})
            has_process = "process" in event

            shot_ended = False

            if has_process:
                # Primary detection: process.e flag
                if process.get("e", False):
                    shot_ended = True
                    logger.info("Shot ended (process.e=True)")
            else:
                # Fallback: mode transition 1→0 when process absent
                if prev_mode == MODE_BREW and current_mode == MODE_STANDBY:
                    shot_ended = True
                    logger.info("Shot ended (fallback m=%d→m=%d)", prev_mode, current_mode)

            if shot_ended:
                new_shots = await self._fetch_new_shots()
                for shot in new_shots:
                    await self.on_shot(shot)

            prev_mode = current_mode

    # ── Shot fetching ─────────────────────────────────────────────────────────

    async def _fetch_new_shots(self) -> list[dict]:
        """
        Fetch SIDX index, find IDs not in DB, fetch + save each.
        Returns list of newly saved shot dicts.
        """
        async with self._fetch_lock:
            try:
                async with aiohttp.ClientSession() as session:
                    index = await self._client.get_shot_index(session)
                    known_ids = await self._get_known_ids()

                    new_shots = []
                    for entry in index:
                        if entry["id"] in known_ids:
                            continue
                        if entry["flags"]["deleted"]:
                            continue
                        try:
                            shot = await self._client.get_shot(session, entry["id"])
                            # Fill in timestamp from index if not in slog header
                            shot.setdefault("timestamp", entry["timestamp"])
                            await self._save_shot(shot)
                            new_shots.append(shot)
                            logger.info("Saved new shot id=%d profile=%s", shot["id"], shot.get("profile_name"))
                        except Exception as exc:
                            logger.error("Failed to fetch/save shot %d: %s", entry["id"], exc, exc_info=True)

                    return new_shots
            except Exception as exc:
                logger.error("_fetch_new_shots failed: %s", exc, exc_info=True)
                return []

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def _get_known_ids(self) -> set[int]:
        """Return set of shot IDs already in the shots table."""
        async with get_db() as db:
            cursor = await db.execute("SELECT id FROM shots")
            rows = await cursor.fetchall()
            return {int(row[0]) for row in rows}

    async def _save_shot(self, shot_data: dict) -> None:
        """Insert a shot into the shots table (ignore duplicates)."""
        ts = shot_data.get("timestamp")
        if isinstance(ts, datetime):
            ts_str = ts.isoformat()
        else:
            ts_str = str(ts) if ts else datetime.now(tz=timezone.utc).isoformat()

        raw_json = json.dumps({
            "datapoints": shot_data.get("datapoints", []),
        }, default=str)

        async with get_db() as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO shots (id, timestamp, duration_s, profile_name, raw_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(shot_data["id"]),
                    ts_str,
                    shot_data.get("duration_s"),
                    shot_data.get("profile_name"),
                    raw_json,
                ),
            )
            await db.commit()
