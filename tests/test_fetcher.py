"""
Unit tests for monitor/fetcher.py — binary SLOG parsing + HTTP client.
"""
import struct
import asyncio

TEST_HOST = "192.168.1.100"
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Helpers to build minimal valid binary blobs
# ---------------------------------------------------------------------------

def make_slog_binary(samples: list[dict], version: int = 5,
                     sample_interval_ms: int = 250,
                     fields_mask: int = 0x1FFF) -> bytes:
    """
    Build a minimal SLOG v5 binary.
    Header: 512 bytes (shot_log_format.h)
    Sample: 26 bytes each = 13 × uint16 (all fields present when mask=0x1FFF)
      t(u16) tt(u16) ct(u16) tp(u16) cp(u16) fl(i16) tf(i16) pf(i16) vf(i16) v(u16) ev(u16) pr(u16) si(u16)
    """
    header = bytearray(512)

    # Magic: SHOT = 0x544F4853
    struct.pack_into("<I", header, 0, 0x544F4853)
    # Version
    header[4] = version
    # reserved0 = sample size (26 for v5 with all fields)
    header[5] = 26
    # Header size
    struct.pack_into("<H", header, 6, 512)
    # Sample interval
    struct.pack_into("<H", header, 8, sample_interval_ms)
    # reserved1
    struct.pack_into("<H", header, 10, 0)
    # Fields mask
    struct.pack_into("<I", header, 12, fields_mask)
    # Sample count (0 = infer from file size)
    struct.pack_into("<I", header, 16, len(samples))
    # Duration (0 = compute from last sample)
    struct.pack_into("<I", header, 20, 0)
    # Start epoch
    struct.pack_into("<I", header, 24, 1709827200)

    # Profile ID at offset 28, 32 bytes
    pid = b"test_profile\x00"
    header[28:28+len(pid)] = pid
    # Profile name at offset 60, 48 bytes
    pname = b"Test Profile\x00"
    header[60:60+len(pname)] = pname
    # Final weight at offset 108
    struct.pack_into("<H", header, 108, 0)

    # Phase transitions (offset 110, 12×29 bytes)
    # Phase transition count at offset 110 + 12*29 = 458
    header[458] = 0  # no phases in test

    body = b""
    for s in samples:
        # 13 fields, all uint16/int16
        sample = struct.pack(
            "<HHHHHhhhhHHHH",
            s.get("t", 0),       # u16 tick (sample index, NOT ms)
            s.get("tt", 930),    # u16 target temp ×10
            s.get("ct", 930),    # u16 current temp ×10
            s.get("tp", 90),     # u16 target pressure ×10
            s.get("cp", 90),     # u16 current pressure ×10
            s.get("fl", 200),    # i16 pump flow ×100
            s.get("tf", 200),    # i16 target flow ×100
            s.get("pf", 200),    # i16 puck flow ×100
            s.get("vf", 150),    # i16 volumetric flow ×100
            s.get("v", 100),     # u16 volumetric weight ×10
            s.get("ev", 100),    # u16 estimated weight ×10
            s.get("pr", 50),     # u16 puck resistance ×100
            s.get("si", 0),      # u16 system info
        )
        assert len(sample) == 26, f"Sample is {len(sample)} bytes, expected 26"
        body += sample

    return bytes(header) + body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParseShotSlogBinary:
    def test_parse_returns_dict_with_datapoints(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        data = make_slog_binary([
            {"t": 0, "ct": 930, "cp": 90, "pf": 150},
            {"t": 1, "ct": 932, "cp": 92, "pf": 160},
        ])
        result = client._parse_shot_slog(data, shot_id=5)
        assert "datapoints" in result
        assert len(result["datapoints"]) == 2

    def test_parse_profile_name_from_header(self):
        """profile_name is read from the SLOG header."""
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        data = make_slog_binary([{"t": 0}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert result["profile_name"] == "Test Profile"

    def test_parse_pressure_bar(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        # cp=91 → 9.1 bar
        data = make_slog_binary([{"t": 0, "cp": 91}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["pressure_bar"] - 9.1) < 0.001

    def test_parse_temp_c(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        # ct=935 → 93.5°C
        data = make_slog_binary([{"t": 0, "ct": 935}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["temp_c"] - 93.5) < 0.001

    def test_parse_puck_flow_mls(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        # pf=200 → 2.0 ml/s (puck flow)
        data = make_slog_binary([{"t": 0, "pf": 200}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["flow_mls"] - 2.0) < 0.001

    def test_parse_pump_flow_mls(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        # fl=350 → 3.5 ml/s (pump flow)
        data = make_slog_binary([{"t": 0, "fl": 350}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["pump_flow_mls"] - 3.5) < 0.001

    def test_parse_target_pressure(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        # tp=95 → 9.5 bar
        data = make_slog_binary([{"t": 0, "tp": 95}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["target_pressure_bar"] - 9.5) < 0.001

    def test_parse_target_temp(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        # tt=930 → 93.0°C
        data = make_slog_binary([{"t": 0, "tt": 930}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["target_temp_c"] - 93.0) < 0.001

    def test_parse_t_tick_to_ms(self):
        """t field is a tick/sample index, converted via sampleInterval."""
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        # t=4 ticks × 250ms interval = 1000ms = 1.0s
        data = make_slog_binary([{"t": 4}], sample_interval_ms=250)
        result = client._parse_shot_slog(data, shot_id=5)
        dp = result["datapoints"][0]
        assert dp["t_ms"] == 1000
        assert abs(dp["t_s"] - 1.0) < 0.001

    def test_parse_duration_s(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        # 3 samples: tick 0, 20, 120 → last tick 120 × 250ms = 30000ms = 30s
        data = make_slog_binary([{"t": 0}, {"t": 20}, {"t": 120}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["duration_s"] - 30.0) < 0.001

    def test_parse_shot_id(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        data = make_slog_binary([{"t": 0}])
        result = client._parse_shot_slog(data, shot_id=99)
        assert result["id"] == 99

    def test_parse_weight_g(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        # v=370 → 37.0g (scale weight)
        data = make_slog_binary([{"t": 0, "v": 370}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["weight_g"] - 37.0) < 0.001

    def test_parse_negative_flow(self):
        """Flow fields are int16 and can be negative."""
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        # fl=-50 → -0.5 ml/s (negative pump flow during backflush etc.)
        data = make_slog_binary([{"t": 0, "fl": -50}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["pump_flow_mls"] - (-0.5)) < 0.001

    def test_phases_parsed(self):
        """Phase transitions are parsed from v5 headers."""
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)

        data = bytearray(make_slog_binary([{"t": 0}, {"t": 40}]))

        # Write phase transition at offset 110
        struct.pack_into("<H", data, 110, 0)  # sampleIndex = 0
        data[112] = 0  # phaseNumber = 0
        data[113] = 0  # reserved
        name = b"Prefill\x00"
        data[114:114+len(name)] = name

        # Second phase at offset 110 + 29 = 139
        struct.pack_into("<H", data, 139, 20)  # sampleIndex = 20
        data[141] = 1  # phaseNumber = 1
        data[142] = 0  # reserved
        name2 = b"Extraction\x00"
        data[143:143+len(name2)] = name2

        # Phase count at offset 458
        data[458] = 2

        result = client._parse_shot_slog(bytes(data), shot_id=5)
        assert len(result["phases"]) == 2
        assert result["phases"][0]["name"] == "Prefill"
        assert result["phases"][1]["name"] == "Extraction"
        assert result["phases"][1]["sample_index"] == 20


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_get_status_returns_dict(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)

        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"ct": 93.5, "pr": 0.0, "m": 0})
        mock_response.raise_for_status = MagicMock()

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))

        result = await client.get_status(mock_session)
        assert isinstance(result, dict)
        assert result["ct"] == 93.5


class TestGetShot:
    @pytest.mark.asyncio
    async def test_get_shot_parses_slog(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)

        binary_data = make_slog_binary([
            {"t": 0, "ct": 930, "cp": 90},
            {"t": 1, "ct": 935, "cp": 92},
        ])

        mock_response = AsyncMock()
        mock_response.read = AsyncMock(return_value=binary_data)
        mock_response.raise_for_status = MagicMock()

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))

        result = await client.get_shot(mock_session, shot_id=7)
        assert result["id"] == 7
        assert len(result["datapoints"]) == 2
        # Verify field values are correctly parsed
        assert abs(result["datapoints"][0]["temp_c"] - 93.0) < 0.001
        assert abs(result["datapoints"][0]["pressure_bar"] - 9.0) < 0.001
