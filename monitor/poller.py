"""
ShotPoller — WebSocket listener for GaggiaMate shot detection.

Detection logic:
  Primary:  process.e == True in evt:status payload
  Fallback: mode transition m==1 (Brew) → m==0 (Standby) when process field absent

On shot detected:
  1. Sends ``req:history:list`` over the same WS connection to get clean metadata
     (profile name, timestamp, duration) for every shot not yet in the DB.
  2. Fetches SLOG binary via HTTP for telemetry datapoints.
  3. Saves to DB and calls on_shot for each new shot.

Startup suppression:
  On the first fetch (cold-start), shots older than STARTUP_ALERT_WINDOW_MINUTES
  are saved silently without triggering a Discord alert.  This prevents bulk-spam
  when the bot starts with an empty DB and ingests historical shots all at once.

WS request/response:
  ``_ws_request()`` sends a typed request on the active WS connection and awaits
  the matching response by ``rid``.  ``_process_ws()`` routes incoming ``res:*``
  messages to waiting futures while continuing to read ``evt:status`` events.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable, Optional

import aiohttp

from db import get_db
from monitor.fetcher import GaggiaMateClient

logger = logging.getLogger(__name__)

# Mode constants
MODE_STANDBY = 0
MODE_BREW = 1

# Only alert for shots newer than this window on the first startup fetch.
# Prevents bulk-spamming Discord when the bot cold-starts with an empty DB.
STARTUP_ALERT_WINDOW_MINUTES = 5


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
        # WS request/response tracking
        self._pending: dict[str, asyncio.Future] = {}
        self._ws: Optional[object] = None
        # Startup suppression flag — False until first fetch completes
        self._startup_done = False

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
                logger.warning("WebSocket disconnected: %s — reconnecting in %.1fs",
                               exc, self.reconnect_delay)
                await asyncio.sleep(self.reconnect_delay)
            except Exception as exc:
                if not self._running:
                    break
                logger.error("Unexpected WebSocket error: %s", exc, exc_info=True)
                await asyncio.sleep(self.reconnect_delay)

    def stop(self):
        """Signal the run loop to stop."""
        self._running = False

    # ── WS request/response ────────────────────────────────────────────────────

    async def _ws_request(self, ws, tp: str, params: Optional[dict] = None,
                          timeout: float = 15.0) -> dict:
        """Send a typed WS request and await the matching response by ``rid``."""
        rid = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[rid] = fut
        msg: dict = {"tp": tp, "rid": rid}
        if params:
            msg.update(params)
        try:
            await ws.send_json(msg)
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("WS request %s timed out after %.1fs", tp, timeout)
            raise
        finally:
            self._pending.pop(rid, None)

    # ── Internal WebSocket processor ──────────────────────────────────────────

    async def _process_ws(self, ws) -> None:
        """
        Process messages from an open WebSocket connection.

        Routes ``res:*`` messages to pending request futures.
        Handles both process.e shot detection and fallback m=1→m=0 transition.
        Shot fetches are dispatched as background tasks so the message loop
        keeps running and can deliver the ``res:history:list`` response.
        """
        self._ws = ws
        prev_mode: Optional[int] = None

        try:
            async for msg in ws:
                # Support both aiohttp WSMessage objects and plain strings (tests)
                raw = msg.data if hasattr(msg, "data") else msg
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                # Route response messages to pending request futures
                rid = event.get("rid")
                if rid and rid in self._pending:
                    fut = self._pending[rid]
                    if not fut.done():
                        fut.set_result(event)
                    continue   # not an event — don't process further

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
                    # Run as a task so the message loop keeps running and can
                    # deliver the res:history:list response to _ws_request.
                    asyncio.create_task(self._fetch_and_process_shots(ws))

                prev_mode = current_mode
        finally:
            self._ws = None

    # ── Shot fetching ─────────────────────────────────────────────────────────

    async def _fetch_and_process_shots(self, ws) -> None:
        """
        Fetch new shots via WS ``req:history:list`` (clean metadata) and
        SLOG binary HTTP (telemetry datapoints), save to DB, and alert.
        """
        async with self._fetch_lock:
            try:
                # --- Step 1: get metadata list from device over WS ---
                resp = await self._ws_request(ws, "req:history:list")
                items = resp.get("history", [])
                if not isinstance(items, list):
                    logger.warning("req:history:list returned unexpected type: %s",
                                   type(items).__name__)
                    return

                known_ids = await self._get_known_ids()
                startup_cutoff = (datetime.now(tz=timezone.utc)
                                  - timedelta(minutes=STARTUP_ALERT_WINDOW_MINUTES))
                is_startup_batch = not self._startup_done

                new_shots: list[dict] = []

                async with aiohttp.ClientSession() as session:
                    for item in items:
                        shot_id_str = item.get("id", "")
                        try:
                            shot_id = int(shot_id_str)
                        except (ValueError, TypeError):
                            logger.warning("Skipping shot with invalid id: %r", shot_id_str)
                            continue

                        if shot_id in known_ids:
                            continue

                        try:
                            # --- Step 2: fetch SLOG binary for telemetry ---
                            shot = await self._client.get_shot(session, shot_id)

                            # --- Step 3: overlay clean WS metadata ---
                            shot["profile_name"] = item.get("profile", "")
                            shot["profile_id"]   = item.get("profileId", "")
                            ts_raw = item.get("timestamp", 0)
                            shot["timestamp"]    = datetime.fromtimestamp(
                                ts_raw, tz=timezone.utc
                            )
                            duration_ms = item.get("duration", 0)
                            shot["duration_s"]   = duration_ms / 1000.0

                            await self._save_shot(shot)
                            new_shots.append(shot)
                            logger.info(
                                "Saved new shot id=%d profile=%r duration=%.1fs",
                                shot_id, shot["profile_name"], shot["duration_s"],
                            )
                        except Exception as exc:
                            logger.error("Failed to fetch/save shot %d: %s",
                                         shot_id, exc, exc_info=True)

                # Mark startup complete before alerting so re-entrant calls
                # during the same session don't suppress real new shots.
                self._startup_done = True

                # --- Step 4: alert (suppress old shots on startup) ---
                for shot in new_shots:
                    shot_ts = shot.get("timestamp")
                    if (is_startup_batch
                            and isinstance(shot_ts, datetime)
                            and shot_ts < startup_cutoff):
                        logger.debug(
                            "Suppressing startup alert for old shot %s (%s)",
                            shot["id"], shot_ts,
                        )
                        continue
                    await self.on_shot({"shot": shot})

            except asyncio.TimeoutError:
                logger.error("Timed out waiting for req:history:list response")
                self._startup_done = True   # avoid permanent suppression on failure
            except Exception as exc:
                logger.error("_fetch_and_process_shots failed: %s", exc, exc_info=True)
                self._startup_done = True

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
