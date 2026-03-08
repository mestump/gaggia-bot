"""
GaggiaMateClient — binary SLOG parser + async HTTP client.

Shot metadata (profile name, timestamp, duration) is fetched via the WebSocket
``req:history:list`` API, which returns clean UTF-8 JSON — no binary index
parsing needed.

Binary format (telemetry only):
  SLOG header: 512 bytes (magic SHOT u32, version u16, profile_name char[64], pad)
  SLOG sample: 26 bytes  (t u32, tt u16, ct u16, tp u16, cp u16, fl u16, tf u16,
                           pf u16, vf u16, v u16, ev u16, pr u16)
"""

import asyncio
import logging
import struct
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# ── SLOG constants ────────────────────────────────────────────────────────────
_SLOG_MAGIC = b"SHOT"
_SLOG_HEADER_SIZE = 512
_SLOG_SAMPLE_SIZE = 26   # t(u32) + 11×u16 = 4 + 22 = 26 bytes
_SLOG_SAMPLE_FMT = "<IHHHHHHHHHHH"   # t(u32) + 11×u16


class GaggiaMateClient:
    def __init__(self, host: str, max_retries: int = 3, retry_delay: float = 2.0):
        self.host = host
        self.base_url = f"http://{host}"
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    # ── Binary parser ─────────────────────────────────────────────────────────

    def _parse_shot_slog(self, data: bytes, shot_id: int) -> dict:
        """Parse raw SLOG binary → shot dict with datapoints list.

        Note: the profile_name field in the SLOG header is unreliable binary
        data on many firmware versions.  Always override it with the clean
        ``profile`` value returned by ``req:history:list`` over WebSocket.
        """
        if len(data) < _SLOG_HEADER_SIZE:
            raise ValueError(f"SLOG data too short: {len(data)} bytes")

        magic = data[:4]
        if magic != _SLOG_MAGIC:
            raise ValueError(f"Bad SLOG magic: {magic!r}")

        num_samples = (len(data) - _SLOG_HEADER_SIZE) // _SLOG_SAMPLE_SIZE
        datapoints = []
        for i in range(num_samples):
            offset = _SLOG_HEADER_SIZE + i * _SLOG_SAMPLE_SIZE
            (t, tt, ct, tp, cp, fl, tf, pf, vf, v, ev, pr_ratio) = struct.unpack_from(
                _SLOG_SAMPLE_FMT, data, offset
            )
            datapoints.append({
                "t_ms":              t,
                "t_s":               t / 1000.0,
                "temp_c":            ct / 10.0,
                "target_temp_c":     tt / 10.0,
                "pressure_bar":      cp / 10.0,
                "target_pressure_bar": tp / 10.0,
                "flow_mls":          pf / 100.0,   # puck flow (actual through-puck flow)
                "target_flow_mls":   tf / 100.0,
                "volume_ml":         v / 10.0,
                "weight_g":          0.0,   # not stored in SLOG
            })

        duration_s = datapoints[-1]["t_s"] if datapoints else 0.0

        return {
            "id":           shot_id,
            "profile_name": "",   # filled by WS req:history:list metadata
            "duration_s":   duration_s,
            "datapoints":   datapoints,
        }

    # ── HTTP methods ──────────────────────────────────────────────────────────

    async def _get_bytes(self, session: aiohttp.ClientSession, url: str) -> bytes:
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    return await resp.read()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                logger.warning("GET %s failed (attempt %d/%d): %s",
                               url, attempt + 1, self.max_retries, exc)
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
        logger.error("GET %s exhausted retries", url)
        raise last_exc  # type: ignore[misc]

    async def _get_json(self, session: aiohttp.ClientSession, url: str) -> dict:
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    return await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                logger.warning("GET %s failed (attempt %d/%d): %s",
                               url, attempt + 1, self.max_retries, exc)
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
        logger.error("GET %s exhausted retries", url)
        raise last_exc  # type: ignore[misc]

    async def get_shot(self, session: aiohttp.ClientSession, shot_id: int) -> dict:
        """Fetch /api/history/{shot_id:06d}.slog and parse SLOG binary for telemetry."""
        url = f"{self.base_url}/api/history/{shot_id:06d}.slog"
        data = await self._get_bytes(session, url)
        return self._parse_shot_slog(data, shot_id)

    async def get_status(self, session: aiohttp.ClientSession) -> dict:
        """GET /api/status → raw JSON dict."""
        url = f"{self.base_url}/api/status"
        return await self._get_json(session, url)
