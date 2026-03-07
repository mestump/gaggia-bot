"""
Unit tests for monitor/poller.py — WebSocket shot detection.
"""
import asyncio
import json

TEST_HOST = "192.168.1.100"
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_status_event(**kwargs) -> str:
    """Build a JSON evt:status message."""
    base = {
        "tp": "evt:status",
        "m": 0,
        "ct": 93.5,
        "pr": 0.0,
        "p": "Test Profile",
        "puid": "abc123",
    }
    base.update(kwargs)
    return json.dumps(base)


def mock_ws_messages(messages: list[str]):
    """
    Return an async iterable of mocked WS messages.
    Each message has a .data attribute.
    """
    class FakeMsg:
        def __init__(self, data):
            self.data = data
            self.type = 1  # aiohttp.WSMsgType.TEXT

    class FakeWS:
        def __init__(self, msgs):
            self._msgs = [FakeMsg(m) for m in msgs]
            self._idx = 0
            self.closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._idx >= len(self._msgs):
                raise StopAsyncIteration
            msg = self._msgs[self._idx]
            self._idx += 1
            return msg

        async def close(self):
            self.closed = True

    return FakeWS(messages)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestShotDetectedOnProcessEnd:
    @pytest.mark.asyncio
    async def test_shot_detected_when_process_e_true(self):
        """When process.e becomes True, on_shot should be called."""
        from monitor.poller import ShotPoller

        on_shot = AsyncMock()
        mock_shot = {
            "id": 1,
            "timestamp": datetime.now(tz=timezone.utc),
            "duration_s": 28.0,
            "profile_name": "Test",
            "datapoints": [],
        }
        mock_index = [{"id": 1, "timestamp": datetime.now(tz=timezone.utc), "flags": {"completed": True, "deleted": False, "hasNotes": False}}]

        messages = [
            make_status_event(m=1, process={"a": True, "e": False}),   # shot active
            make_status_event(m=1, process={"a": False, "e": True}),   # shot ended
        ]

        ws = mock_ws_messages(messages)

        poller = ShotPoller(host=TEST_HOST, on_shot=on_shot)

        with patch.object(poller, "_fetch_new_shots", new_callable=AsyncMock) as mock_fetch:
            with patch.object(poller, "_get_known_ids", return_value={}) as mock_known:
                await poller._process_ws(ws)

        mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_shot_called_with_shot_data(self):
        """on_shot callback receives the shot dict returned by fetcher."""
        from monitor.poller import ShotPoller

        on_shot = AsyncMock()
        mock_shot = {
            "id": 52,
            "timestamp": datetime.now(tz=timezone.utc),
            "duration_s": 30.0,
            "profile_name": "Bloom",
            "datapoints": [{"t_ms": 0, "t_s": 0.0, "pressure_bar": 9.0, "temp_c": 93.0, "flow_mls": 2.0, "weight_g": 0.0}],
        }
        mock_index = [
            {"id": 52, "timestamp": mock_shot["timestamp"], "flags": {"completed": True, "deleted": False, "hasNotes": False}},
        ]

        messages = [
            make_status_event(m=1, process={"a": False, "e": True}),
        ]
        ws = mock_ws_messages(messages)

        poller = ShotPoller(host=TEST_HOST, on_shot=on_shot)

        with patch.object(poller, "_fetch_new_shots", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = [mock_shot]
            with patch.object(poller, "_get_known_ids", return_value=set()):
                await poller._process_ws(ws)

        on_shot.assert_called_once_with(mock_shot)


class TestFallbackModeTransition:
    @pytest.mark.asyncio
    async def test_fallback_m1_to_m0_triggers_fetch(self):
        """When process field absent, m=1→m=0 transition should trigger fetch."""
        from monitor.poller import ShotPoller

        on_shot = AsyncMock()
        messages = [
            make_status_event(m=1),   # no process field
            make_status_event(m=0),   # transition to standby
        ]
        ws = mock_ws_messages(messages)

        poller = ShotPoller(host=TEST_HOST, on_shot=on_shot)

        with patch.object(poller, "_fetch_new_shots", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            with patch.object(poller, "_get_known_ids", return_value=set()):
                await poller._process_ws(ws)

        mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_fetch_when_no_transition(self):
        """m=0→m=0 (no brew) should not trigger fetch."""
        from monitor.poller import ShotPoller

        on_shot = AsyncMock()
        messages = [
            make_status_event(m=0),
            make_status_event(m=0),
            make_status_event(m=2),  # steam, not brew
            make_status_event(m=0),
        ]
        ws = mock_ws_messages(messages)

        poller = ShotPoller(host=TEST_HOST, on_shot=on_shot)

        with patch.object(poller, "_fetch_new_shots", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            with patch.object(poller, "_get_known_ids", return_value=set()):
                await poller._process_ws(ws)

        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_field_takes_priority(self):
        """
        If process.e is present and False but m transitions 1→0,
        don't double-trigger (process field is authoritative).
        """
        from monitor.poller import ShotPoller

        on_shot = AsyncMock()
        messages = [
            make_status_event(m=1, process={"a": True, "e": False}),
            # process.e=False but m goes to 0 — with process present, fallback disabled
            make_status_event(m=0, process={"a": False, "e": False}),
        ]
        ws = mock_ws_messages(messages)

        poller = ShotPoller(host=TEST_HOST, on_shot=on_shot)

        with patch.object(poller, "_fetch_new_shots", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            with patch.object(poller, "_get_known_ids", return_value=set()):
                await poller._process_ws(ws)

        mock_fetch.assert_not_called()


class TestGetKnownIds:
    @pytest.mark.asyncio
    async def test_get_known_ids_returns_set(self):
        """_get_known_ids should query DB and return a set of int IDs."""
        from monitor.poller import ShotPoller

        poller = ShotPoller(host=TEST_HOST, on_shot=AsyncMock())

        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[(1,), (2,), (52,)])
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        with patch("monitor.poller.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await poller._get_known_ids()

        assert result == {1, 2, 52}


class TestSaveShot:
    @pytest.mark.asyncio
    async def test_save_shot_writes_to_db(self):
        """_save_shot should insert a row into the shots table."""
        from monitor.poller import ShotPoller
        import json as json_mod

        poller = ShotPoller(host=TEST_HOST, on_shot=AsyncMock())

        shot_data = {
            "id": 99,
            "timestamp": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "duration_s": 28.5,
            "profile_name": "Test Profile",
            "datapoints": [{"t_ms": 0, "pressure_bar": 9.0}],
        }

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("monitor.poller.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_get_db.return_value.__aexit__ = AsyncMock(return_value=False)
            await poller._save_shot(shot_data)

        # Verify execute was called (INSERT or INSERT OR IGNORE)
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        sql = call_args[0][0]
        assert "shots" in sql.lower()
        assert "INSERT" in sql.upper()
