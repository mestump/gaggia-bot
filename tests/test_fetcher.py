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

def make_slog_binary(samples: list[dict]) -> bytes:
    """
    Build a minimal SLOG binary.
    Header: 512 bytes
      magic (4s), version (u16), profile_name (char[64]), pad to 512
    Sample: 26 bytes each (all u16 LE except t which is u32 LE)
      t(u32), tt(u16), ct(u16), tp(u16), cp(u16), fl(u16), tf(u16),
      pf(u16), vf(u16), v(u16), ev(u16), pr(u16)
    """
    profile_name_bytes = b"Test Profile\x00".ljust(64, b"\x00")
    header = b"SHOT" + struct.pack("<H", 5) + profile_name_bytes
    header += b"\x00" * (512 - len(header))
    assert len(header) == 512

    body = b""
    for s in samples:
        sample = struct.pack(
            "<IHHHHHHHHHHH",
            s.get("t", 0),              # u32 ms
            s.get("tt", 930),           # u16 target temp ×10
            s.get("ct", 930),           # u16 current temp ×10
            s.get("tp", 90),            # u16 target pressure ×10
            s.get("cp", 90),            # u16 current pressure ×10
            s.get("fl", 200),           # u16 flow limit ×100
            s.get("tf", 200),           # u16 target flow ×100
            s.get("pf", 200),           # u16 predicted flow ×100
            s.get("vf", 150),           # u16 volume flow ×100
            s.get("v", 100),            # u16 volume ×10
            s.get("ev", 100),           # u16 estimated volume ×10
            s.get("pr", 50),            # u16 pump ratio ×100
        )
        assert len(sample) == 26, f"Sample is {len(sample)} bytes, expected 26"
        body += sample

    return header + body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParseShotSlogBinary:
    def test_parse_returns_dict_with_datapoints(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        data = make_slog_binary([
            {"t": 0, "ct": 930, "cp": 90, "vf": 150},
            {"t": 250, "ct": 932, "cp": 92, "vf": 160},
        ])
        result = client._parse_shot_slog(data, shot_id=5)
        assert "datapoints" in result
        assert len(result["datapoints"]) == 2

    def test_parse_profile_name_empty(self):
        """profile_name is always empty string — filled later by WS req:history:list."""
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        data = make_slog_binary([{"t": 0}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert result["profile_name"] == ""

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

    def test_parse_flow_mls(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        # pf=200 → 2.0 ml/s (puck flow, not volume flow)
        data = make_slog_binary([{"t": 0, "pf": 200}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["flow_mls"] - 2.0) < 0.001

    def test_parse_t_ms_and_t_s(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        data = make_slog_binary([{"t": 1000}])
        result = client._parse_shot_slog(data, shot_id=5)
        dp = result["datapoints"][0]
        assert dp["t_ms"] == 1000
        assert abs(dp["t_s"] - 1.0) < 0.001

    def test_parse_duration_s(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        data = make_slog_binary([{"t": 0}, {"t": 5000}, {"t": 30000}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["duration_s"] - 30.0) < 0.001

    def test_parse_shot_id(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient(TEST_HOST)
        data = make_slog_binary([{"t": 0}])
        result = client._parse_shot_slog(data, shot_id=99)
        assert result["id"] == 99


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
            {"t": 250, "ct": 935, "cp": 92},
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
