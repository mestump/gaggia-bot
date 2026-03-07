"""
Unit tests for monitor/fetcher.py — binary SIDX/SLOG parsing + HTTP client.
"""
import struct
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Helpers to build minimal valid binary blobs
# ---------------------------------------------------------------------------

def make_sidx_binary(records: list[dict]) -> bytes:
    """
    Build a minimal SIDX binary.
    Header: 32 bytes
      magic (4s), version (u32), count (u32), reserved (20s)
    Record: 128 bytes each
      id (u32), timestamp (u32), data_size (u32), flags (u16), pad (u16=0),
      profile_id (char[16]), profile_name (char[32]), reserved (68 bytes)
    """
    count = len(records)
    header = struct.pack(
        "<4sII20s",
        b"SIDX",
        1,
        count,
        b"\x00" * 20,
    )
    assert len(header) == 32

    body = b""
    for r in records:
        profile_id = r.get("profile_id", "prof1").encode("utf-8")[:16].ljust(16, b"\x00")
        profile_name = r.get("profile_name", "Test Profile").encode("utf-8")[:32].ljust(32, b"\x00")
        rec = struct.pack(
            "<IIIHHs16s32s68s",
            r["id"],
            r["timestamp"],
            r.get("data_size", 1024),
            r.get("flags", 1),   # bit0=completed
            0,                   # padding
            b"\x00",             # 1 spare byte to get alignment right
            profile_id,
            profile_name,
            b"\x00" * 68,
        )
        # struct above is 4+4+4+2+2+1+16+32+68 = 133 bytes — wrong; redo manually
        body += b""  # placeholder — will be overwritten below

    # Build records manually to be exactly 128 bytes each
    body = b""
    for r in records:
        profile_id_bytes = r.get("profile_id", "prof1").encode("utf-8")[:16].ljust(16, b"\x00")
        profile_name_bytes = r.get("profile_name", "Test Profile").encode("utf-8")[:32].ljust(32, b"\x00")
        rec = (
            struct.pack("<I", r["id"])            # 4  bytes
            + struct.pack("<I", r["timestamp"])   # 4  bytes
            + struct.pack("<I", r.get("data_size", 1024))  # 4 bytes
            + struct.pack("<H", r.get("flags", 1))         # 2 bytes
            + profile_id_bytes                    # 16 bytes
            + profile_name_bytes                  # 32 bytes
            # total so far: 62 bytes; pad to 128
        )
        rec += b"\x00" * (128 - len(rec))
        assert len(rec) == 128, f"Record is {len(rec)} bytes, expected 128"
        body += rec

    return header + body


def make_slog_binary(samples: list[dict]) -> bytes:
    """
    Build a minimal SLOG binary.
    Header: 512 bytes
      magic (4s), version (u16), profile_name (char[64]), pad to 512
    Sample: 26 bytes each (all u16 LE except t which is u32 LE)
      t(u32), tt(u16), ct(u16), tp(u16), cp(u16), fl(u16), tf(u16),
      pf(u16), vf(u16), v(u16), ev(u16), pr(u16), systemInfo(u16)
    """
    profile_name_bytes = b"Test Profile\x00".ljust(64, b"\x00")
    header = b"SHOT" + struct.pack("<H", 5) + profile_name_bytes
    header += b"\x00" * (512 - len(header))
    assert len(header) == 512

    body = b""
    for s in samples:
        sample = struct.pack(
            "<IHHHHHHHHHHHH",
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
            s.get("si", 0),             # u16 systemInfo
        )
        assert len(sample) == 28, f"Sample is {len(sample)} bytes, expected 28"
        body += sample

    return header + body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParseShotIndexBinary:
    def test_parse_returns_list(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        data = make_sidx_binary([
            {"id": 1, "timestamp": 1700000000, "profile_name": "Bloom", "flags": 1},
            {"id": 2, "timestamp": 1700001000, "profile_name": "Turbo", "flags": 3},
        ])
        result = client._parse_shot_index(data)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_parse_shot_ids(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        data = make_sidx_binary([
            {"id": 42, "timestamp": 1700000000, "profile_name": "X"},
        ])
        result = client._parse_shot_index(data)
        assert result[0]["id"] == 42

    def test_parse_timestamp_as_datetime(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        ts = 1700000000
        data = make_sidx_binary([{"id": 1, "timestamp": ts}])
        result = client._parse_shot_index(data)
        assert isinstance(result[0]["timestamp"], datetime)
        assert result[0]["timestamp"] == datetime.fromtimestamp(ts, tz=timezone.utc)

    def test_parse_profile_name(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        data = make_sidx_binary([{"id": 1, "timestamp": 1700000000, "profile_name": "Bloom & Ramp"}])
        result = client._parse_shot_index(data)
        assert result[0]["profile_name"] == "Bloom & Ramp"

    def test_parse_flags_completed(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        data = make_sidx_binary([{"id": 1, "timestamp": 1700000000, "flags": 1}])
        result = client._parse_shot_index(data)
        assert result[0]["flags"]["completed"] is True
        assert result[0]["flags"]["deleted"] is False
        assert result[0]["flags"]["hasNotes"] is False

    def test_parse_flags_all(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        data = make_sidx_binary([{"id": 1, "timestamp": 1700000000, "flags": 0b111}])
        result = client._parse_shot_index(data)
        assert result[0]["flags"]["completed"] is True
        assert result[0]["flags"]["deleted"] is True
        assert result[0]["flags"]["hasNotes"] is True


class TestParseShotSlogBinary:
    def test_parse_returns_dict_with_datapoints(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        data = make_slog_binary([
            {"t": 0, "ct": 930, "cp": 90, "vf": 150},
            {"t": 250, "ct": 932, "cp": 92, "vf": 160},
        ])
        result = client._parse_shot_slog(data, shot_id=5)
        assert "datapoints" in result
        assert len(result["datapoints"]) == 2

    def test_parse_profile_name_from_header(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        data = make_slog_binary([{"t": 0}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert result["profile_name"] == "Test Profile"

    def test_parse_pressure_bar(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        # cp=91 → 9.1 bar
        data = make_slog_binary([{"t": 0, "cp": 91}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["pressure_bar"] - 9.1) < 0.001

    def test_parse_temp_c(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        # ct=935 → 93.5°C
        data = make_slog_binary([{"t": 0, "ct": 935}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["temp_c"] - 93.5) < 0.001

    def test_parse_flow_mls(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        # vf=200 → 2.0 ml/s
        data = make_slog_binary([{"t": 0, "vf": 200}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["datapoints"][0]["flow_mls"] - 2.0) < 0.001

    def test_parse_t_ms_and_t_s(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        data = make_slog_binary([{"t": 1000}])
        result = client._parse_shot_slog(data, shot_id=5)
        dp = result["datapoints"][0]
        assert dp["t_ms"] == 1000
        assert abs(dp["t_s"] - 1.0) < 0.001

    def test_parse_duration_s(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        data = make_slog_binary([{"t": 0}, {"t": 5000}, {"t": 30000}])
        result = client._parse_shot_slog(data, shot_id=5)
        assert abs(result["duration_s"] - 30.0) < 0.001

    def test_parse_shot_id(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")
        data = make_slog_binary([{"t": 0}])
        result = client._parse_shot_slog(data, shot_id=99)
        assert result["id"] == 99


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_get_status_returns_dict(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")

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


class TestGetShotIndex:
    @pytest.mark.asyncio
    async def test_get_shot_index_parses_binary(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")

        binary_data = make_sidx_binary([
            {"id": 10, "timestamp": 1700000000, "profile_name": "Bloom"},
        ])

        mock_response = AsyncMock()
        mock_response.read = AsyncMock(return_value=binary_data)
        mock_response.raise_for_status = MagicMock()

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))

        result = await client.get_shot_index(mock_session)
        assert len(result) == 1
        assert result[0]["id"] == 10
        assert result[0]["profile_name"] == "Bloom"


class TestGetShot:
    @pytest.mark.asyncio
    async def test_get_shot_parses_slog(self):
        from monitor.fetcher import GaggiaMateClient
        client = GaggiaMateClient("192.168.4.253")

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
