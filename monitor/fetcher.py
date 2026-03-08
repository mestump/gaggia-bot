"""
GaggiaMateClient — binary SLOG parser + async HTTP client.

Shot metadata (profile name, timestamp, duration) is fetched via the WebSocket
``req:history:list`` API, which returns clean UTF-8 JSON — no binary index
parsing needed.

Binary format (telemetry only) — reference: shot_log_format.h
  SLOG header: v4=128 bytes, v5+=512 bytes
  SLOG sample: 26 bytes = 13 fields × 2 bytes each (all uint16/int16)

Fields per sample (v5, fieldsMask=0x1FFF):
  t   (uint16) tick/sample index → ms = t × sampleInterval
  tt  (uint16) target temp × 10       → °C
  ct  (uint16) current temp × 10      → °C
  tp  (uint16) target pressure × 10   → bar
  cp  (uint16) current pressure × 10  → bar
  fl  (int16)  pump flow × 100        → ml/s
  tf  (int16)  target flow × 100      → ml/s
  pf  (int16)  puck flow × 100        → ml/s
  vf  (int16)  volumetric flow × 100  → ml/s
  v   (uint16) volumetric weight × 10 → g
  ev  (uint16) estimated weight × 10  → g
  pr  (uint16) puck resistance × 100
  si  (uint16) system info bitmask
"""

import asyncio
import logging
import struct
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# ── SLOG constants ────────────────────────────────────────────────────────────
_SLOG_MAGIC = 0x544F4853  # 'SHOT' as uint32 LE
_SLOG_HEADER_SIZE_V4 = 128
_SLOG_HEADER_SIZE_V5 = 512
_SLOG_DEFAULT_SAMPLE_INTERVAL_MS = 250

# v5 sample: 13 × uint16 = 26 bytes
# Fields: t(u16) tt(u16) ct(u16) tp(u16) cp(u16) fl(i16) tf(i16) pf(i16) vf(i16) v(u16) ev(u16) pr(u16) si(u16)
_SLOG_V5_SAMPLE_FMT = "<HHHHHhhhHHHHH"  # 5×uint16, 1×int16... wait, let me be precise
# Actually per shot_log_format.h:
#   t(u16) tt(u16) ct(u16) tp(u16) cp(u16) fl(i16) tf(i16) pf(i16) vf(i16) v(u16) ev(u16) pr(u16) si(u16)
# = HHHHHhhhhHHHH
_SLOG_V5_SAMPLE_FMT = "<HHHHHhhhhHHHH"
_SLOG_V5_SAMPLE_SIZE = struct.calcsize(_SLOG_V5_SAMPLE_FMT)  # should be 26

# Scale factors
_TEMP_SCALE = 10
_PRESSURE_SCALE = 10
_FLOW_SCALE = 100
_WEIGHT_SCALE = 10
_RESISTANCE_SCALE = 100

# Phase transition struct: 29 bytes each
# uint16 sampleIndex, uint8 phaseNumber, uint8 reserved, char[25] phaseName
_PHASE_TRANSITION_SIZE = 29
_MAX_PHASE_TRANSITIONS = 12


def _decode_cstring(data: bytes) -> str:
    """Decode a null-terminated C string from raw bytes."""
    try:
        null_idx = data.index(0)
        return data[:null_idx].decode("utf-8", errors="replace")
    except ValueError:
        return data.decode("utf-8", errors="replace")


class GaggiaMateClient:
    def __init__(self, host: str, max_retries: int = 3, retry_delay: float = 2.0):
        self.host = host
        self.base_url = f"http://{host}"
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    # ── Binary parser ─────────────────────────────────────────────────────────

    def _parse_shot_slog(self, data: bytes, shot_id: int) -> dict:
        """Parse raw SLOG binary → shot dict with datapoints list.

        Reference: shot_log_format.h and parseBinaryShot.js from GaggiaMate.

        Note: the profile_name field in the SLOG header may contain garbled
        data on some firmware versions.  Always override it with the clean
        ``profile`` value returned by ``req:history:list`` over WebSocket.
        """
        if len(data) < 16:
            raise ValueError(f"SLOG data too short: {len(data)} bytes")

        # ── Read magic and version ────────────────────────────────────────
        magic = struct.unpack_from("<I", data, 0)[0]
        if magic != _SLOG_MAGIC:
            raise ValueError(f"Bad SLOG magic: 0x{magic:08X} (expected 0x{_SLOG_MAGIC:08X})")

        version = data[4]
        device_sample_size = data[5]  # reserved0 holds sample size for diagnostics
        header_size_file = struct.unpack_from("<H", data, 6)[0]

        # Determine header size based on version
        if version <= 4:
            header_size = _SLOG_HEADER_SIZE_V4
        else:
            header_size = _SLOG_HEADER_SIZE_V5

        if len(data) < header_size:
            raise ValueError(
                f"SLOG data too short for v{version} header: "
                f"{len(data)} bytes < {header_size} required"
            )

        # ── Parse header fields ───────────────────────────────────────────
        sample_interval_ms = struct.unpack_from("<H", data, 8)[0]
        if sample_interval_ms == 0:
            sample_interval_ms = _SLOG_DEFAULT_SAMPLE_INTERVAL_MS

        # reserved1 at offset 10 (uint16)
        fields_mask = struct.unpack_from("<I", data, 12)[0]
        sample_count_header = struct.unpack_from("<I", data, 16)[0]
        duration_ms_header = struct.unpack_from("<I", data, 20)[0]
        start_epoch = struct.unpack_from("<I", data, 24)[0]

        profile_id_raw = data[28:60]
        profile_name_raw = data[60:108]
        final_weight_raw = struct.unpack_from("<H", data, 108)[0]

        profile_id = _decode_cstring(profile_id_raw)
        profile_name = _decode_cstring(profile_name_raw)

        # ── Parse phase transitions (v5+) ─────────────────────────────────
        phases = []
        if version >= 5:
            transitions_base = 110
            transition_count_offset = transitions_base + _MAX_PHASE_TRANSITIONS * _PHASE_TRANSITION_SIZE
            if transition_count_offset < len(data):
                transition_count = data[transition_count_offset]
                for i in range(min(transition_count, _MAX_PHASE_TRANSITIONS)):
                    t_offset = transitions_base + i * _PHASE_TRANSITION_SIZE
                    if t_offset + _PHASE_TRANSITION_SIZE <= len(data):
                        sample_index = struct.unpack_from("<H", data, t_offset)[0]
                        phase_number = data[t_offset + 2]
                        # reserved byte at t_offset + 3
                        phase_name = _decode_cstring(data[t_offset + 4 : t_offset + 29])
                        phases.append({
                            "sample_index": sample_index,
                            "phase_number": phase_number,
                            "name": phase_name,
                            "start_time_s": sample_index * sample_interval_ms / 1000.0,
                        })

        # ── Determine sample layout from fields_mask ──────────────────────
        # Count active fields to determine per-sample byte count
        field_count = bin(fields_mask).count("1")
        computed_sample_size = field_count * 2

        # Prefer device-reported sample size, fall back to computed
        if device_sample_size > 0:
            sample_size = device_sample_size
        elif computed_sample_size > 0:
            sample_size = computed_sample_size
        else:
            sample_size = _SLOG_V5_SAMPLE_SIZE

        # Build ordered list of which fields are present
        # Field bit positions match shot_log_format.h
        FIELD_NAMES = [
            (0, "t", "H"),      # tick/sample index
            (1, "tt", "H"),     # target temp
            (2, "ct", "H"),     # current temp
            (3, "tp", "H"),     # target pressure
            (4, "cp", "H"),     # current pressure
            (5, "fl", "h"),     # pump flow (signed)
            (6, "tf", "h"),     # target flow (signed)
            (7, "pf", "h"),     # puck flow (signed)
            (8, "vf", "h"),     # volumetric flow (signed)
            (9, "v", "H"),      # volumetric weight
            (10, "ev", "H"),    # estimated weight
            (11, "pr", "H"),    # puck resistance
            (12, "si", "H"),    # system info
        ]

        active_fields = []
        fmt_chars = "<"
        for bit, name, fmt_char in FIELD_NAMES:
            if fields_mask & (1 << bit):
                active_fields.append((name, fmt_char))
                fmt_chars += fmt_char

        fmt_size = struct.calcsize(fmt_chars)
        if fmt_size != sample_size:
            logger.warning(
                "Sample size mismatch: fields_mask says %d bytes, device says %d. Using device size.",
                fmt_size, sample_size,
            )

        # ── Parse samples ─────────────────────────────────────────────────
        data_bytes = len(data) - header_size
        num_samples = data_bytes // sample_size
        if sample_count_header > 0:
            num_samples = min(num_samples, sample_count_header)

        datapoints = []
        for i in range(num_samples):
            offset = header_size + i * sample_size
            if offset + fmt_size > len(data):
                break

            try:
                values = struct.unpack_from(fmt_chars, data, offset)
            except struct.error:
                break

            raw = dict(zip([f[0] for f in active_fields], values))

            # Convert tick to milliseconds using the sample interval from header
            t_tick = raw.get("t", i)
            t_ms = t_tick * sample_interval_ms

            dp = {
                "t_ms": t_ms,
                "t_s": t_ms / 1000.0,
                "temp_c": raw.get("ct", 0) / _TEMP_SCALE,
                "target_temp_c": raw.get("tt", 0) / _TEMP_SCALE,
                "pressure_bar": raw.get("cp", 0) / _PRESSURE_SCALE,
                "target_pressure_bar": raw.get("tp", 0) / _PRESSURE_SCALE,
                "flow_mls": raw.get("pf", 0) / _FLOW_SCALE,       # puck flow (through-puck)
                "pump_flow_mls": raw.get("fl", 0) / _FLOW_SCALE,  # pump flow
                "target_flow_mls": raw.get("tf", 0) / _FLOW_SCALE,
                "volume_ml": raw.get("ev", 0) / _WEIGHT_SCALE,    # estimated volume/weight
                "weight_g": raw.get("v", 0) / _WEIGHT_SCALE,      # scale weight
            }
            datapoints.append(dp)

        # Compute duration from last sample
        duration_s = datapoints[-1]["t_s"] if datapoints else 0.0

        return {
            "id": shot_id,
            "profile_name": profile_name,  # may be overridden by WS metadata
            "profile_id": profile_id,
            "duration_s": duration_s,
            "datapoints": datapoints,
            "phases": phases,
            "sample_interval_ms": sample_interval_ms,
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
