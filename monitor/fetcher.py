"""
GaggiaMateClient — binary SIDX/SLOG parser + async HTTP client.

Binary formats:
  SIDX header: 32 bytes  (magic=SIDX, version u32, count u32, reserved 20 bytes)
  SIDX record: 128 bytes (id u32, timestamp u32, data_size u32, flags u16,
                           profile_id char[16], profile_name char[32], pad 62 bytes)

  SLOG header: 512 bytes (magic SHOT u32, version u16, profile_name char[64], pad)
  SLOG sample: 26 bytes  (t u32, tt u16, ct u16, tp u16, cp u16, fl u16, tf u16,
                           pf u16, vf u16, v u16, ev u16, pr u16, systemInfo u16)
"""

import asyncio
import logging
import struct
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# ── SIDX constants ────────────────────────────────────────────────────────────
_SIDX_MAGIC = b"SIDX"
_SIDX_HEADER_SIZE = 32
_SIDX_RECORD_SIZE = 128

# SIDX header layout: magic(4s) version(I) count(I) reserved(20s)
_SIDX_HEADER_FMT = "<4sII20s"

# SIDX record offsets (manually parsed for clarity)
#  0: id         u32  (4 bytes)
#  4: timestamp  u32  (4 bytes)
#  8: data_size  u32  (4 bytes)
# 12: flags      u16  (2 bytes)
# 14: profile_id char[16]
# 30: profile_name char[32]
# 62: pad to 128

# ── SLOG constants ────────────────────────────────────────────────────────────
_SLOG_MAGIC = b"SHOT"
_SLOG_HEADER_SIZE = 512
_SLOG_SAMPLE_SIZE = 28   # t(u32) + 12×u16 = 4 + 24 = 28 bytes
_SLOG_SAMPLE_FMT = "<IHHHHHHHHHHHH"   # t(u32) + 12×u16


def _null_str(b: bytes) -> str:
    return b.rstrip(b"\x00").decode("utf-8", errors="replace")


class GaggiaMateClient:
    def __init__(self, host: str, max_retries: int = 3, retry_delay: float = 2.0):
        self.host = host
        self.base_url = f"http://{host}"
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    # ── Binary parsers ────────────────────────────────────────────────────────

    def _parse_shot_index(self, data: bytes) -> list[dict]:
        """Parse raw SIDX binary → list of shot metadata dicts."""
        if len(data) < _SIDX_HEADER_SIZE:
            raise ValueError(f"SIDX data too short: {len(data)} bytes")

        magic, version, count, _ = struct.unpack_from(_SIDX_HEADER_FMT, data, 0)
        if magic != _SIDX_MAGIC:
            raise ValueError(f"Bad SIDX magic: {magic!r}")

        records = []
        for i in range(count):
            offset = _SIDX_HEADER_SIZE + i * _SIDX_RECORD_SIZE
            if offset + _SIDX_RECORD_SIZE > len(data):
                logger.warning("SIDX: truncated at record %d", i)
                break

            shot_id = struct.unpack_from("<I", data, offset)[0]
            timestamp_raw = struct.unpack_from("<I", data, offset + 4)[0]
            # data_size = struct.unpack_from("<I", data, offset + 8)[0]
            flags_raw = struct.unpack_from("<H", data, offset + 12)[0]
            profile_id_bytes = data[offset + 14: offset + 30]
            profile_name_bytes = data[offset + 30: offset + 62]

            records.append({
                "id": shot_id,
                "timestamp": datetime.fromtimestamp(timestamp_raw, tz=timezone.utc),
                "profile_id": _null_str(profile_id_bytes),
                "profile_name": _null_str(profile_name_bytes),
                "flags": {
                    "completed": bool(flags_raw & 0x01),
                    "deleted":   bool(flags_raw & 0x02),
                    "hasNotes":  bool(flags_raw & 0x04),
                },
            })

        return records

    def _parse_shot_slog(self, data: bytes, shot_id: int) -> dict:
        """Parse raw SLOG binary → shot dict with datapoints list."""
        if len(data) < _SLOG_HEADER_SIZE:
            raise ValueError(f"SLOG data too short: {len(data)} bytes")

        magic = data[:4]
        if magic != _SLOG_MAGIC:
            raise ValueError(f"Bad SLOG magic: {magic!r}")

        version = struct.unpack_from("<H", data, 4)[0]
        profile_name = _null_str(data[6:70])   # char[64] at offset 6

        num_samples = (len(data) - _SLOG_HEADER_SIZE) // _SLOG_SAMPLE_SIZE
        datapoints = []
        for i in range(num_samples):
            offset = _SLOG_HEADER_SIZE + i * _SLOG_SAMPLE_SIZE
            (t, tt, ct, tp, cp, fl, tf, pf, vf, v, ev, pr_ratio, sys_info) = struct.unpack_from(
                _SLOG_SAMPLE_FMT, data, offset
            )
            datapoints.append({
                "t_ms":         t,
                "t_s":          t / 1000.0,
                "temp_c":       ct / 10.0,
                "target_temp_c": tt / 10.0,
                "pressure_bar": cp / 10.0,
                "target_pressure_bar": tp / 10.0,
                "flow_mls":     vf / 100.0,       # volume flow
                "target_flow_mls": tf / 100.0,
                "volume_ml":    v / 10.0,
                "weight_g":     0.0,               # not in SLOG; filled externally if needed
            })

        duration_s = datapoints[-1]["t_s"] if datapoints else 0.0

        return {
            "id": shot_id,
            "profile_name": profile_name,
            "duration_s": duration_s,
            "datapoints": datapoints,
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
                logger.warning("GET %s failed (attempt %d/%d): %s", url, attempt + 1, self.max_retries, exc)
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
                logger.warning("GET %s failed (attempt %d/%d): %s", url, attempt + 1, self.max_retries, exc)
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
        logger.error("GET %s exhausted retries", url)
        raise last_exc  # type: ignore[misc]

    async def get_shot_index(self, session: aiohttp.ClientSession) -> list[dict]:
        """Fetch /api/history/index.bin and parse SIDX binary."""
        url = f"{self.base_url}/api/history/index.bin"
        data = await self._get_bytes(session, url)
        return self._parse_shot_index(data)

    async def get_shot(self, session: aiohttp.ClientSession, shot_id: int) -> dict:
        """Fetch /api/history/{shot_id:06d}.slog and parse SLOG binary."""
        url = f"{self.base_url}/api/history/{shot_id:06d}.slog"
        data = await self._get_bytes(session, url)
        return self._parse_shot_slog(data, shot_id)

    async def get_status(self, session: aiohttp.ClientSession) -> dict:
        """GET /api/status → raw JSON dict."""
        url = f"{self.base_url}/api/status"
        return await self._get_json(session, url)
