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
            self.send_json = AsyncMock()

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
        """When process.e becomes True, _fetch_and_process_shots should be called."""
        from monitor.poller import ShotPoller

        on_shot = AsyncMock()
        messages = [
            make_status_event(m=1, process={"a": True, "e": False}),   # shot active
            make_status_event(m=1, process={"a": False, "e": True}),   # shot ended
        ]

        ws = mock_ws_messages(messages)

        poller = ShotPoller(host=TEST_HOST, on_shot=on_shot)

        with patch.object(poller, "_fetch_and_process_shots", new_callable=AsyncMock) as mock_fetch:
            await poller._process_ws(ws)
            await asyncio.sleep(0)  # flush background tasks

        mock_fetch.assert_called_once_with(ws)

    @pytest.mark.asyncio
    async def test_fetch_triggered_on_shot_end(self):
        """_fetch_and_process_shots is dispatched as a background task on shot end."""
        from monitor.poller import ShotPoller

        on_shot = AsyncMock()
        messages = [
            make_status_event(m=1, process={"a": False, "e": True}),
        ]
        ws = mock_ws_messages(messages)

        poller = ShotPoller(host=TEST_HOST, on_shot=on_shot)

        with patch.object(poller, "_fetch_and_process_shots", new_callable=AsyncMock) as mock_fetch:
            await poller._process_ws(ws)
            await asyncio.sleep(0)

        mock_fetch.assert_called_once()


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

        with patch.object(poller, "_fetch_and_process_shots", new_callable=AsyncMock) as mock_fetch:
            await poller._process_ws(ws)
            await asyncio.sleep(0)

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

        with patch.object(poller, "_fetch_and_process_shots", new_callable=AsyncMock) as mock_fetch:
            await poller._process_ws(ws)
            await asyncio.sleep(0)

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

        with patch.object(poller, "_fetch_and_process_shots", new_callable=AsyncMock) as mock_fetch:
            await poller._process_ws(ws)
            await asyncio.sleep(0)

        mock_fetch.assert_not_called()


class TestWsResponseRouting:
    @pytest.mark.asyncio
    async def test_response_message_resolves_pending_future(self):
        """res:* messages with matching rid should resolve the pending future."""
        from monitor.poller import ShotPoller

        poller = ShotPoller(host=TEST_HOST, on_shot=AsyncMock())
        loop = asyncio.get_running_loop()

        rid = "test-rid-123"
        fut = loop.create_future()
        poller._pending[rid] = fut

        response = {"tp": "res:history:list", "rid": rid, "history": []}
        messages = [json.dumps(response)]
        ws = mock_ws_messages(messages)

        await poller._process_ws(ws)

        assert fut.done()
        assert fut.result() == response

    @pytest.mark.asyncio
    async def test_unknown_rid_not_routed(self):
        """Messages with unknown rid are treated as events, not responses."""
        from monitor.poller import ShotPoller

        poller = ShotPoller(host=TEST_HOST, on_shot=AsyncMock())

        # A response with a rid that is NOT in _pending — should not crash
        response = {"tp": "res:history:list", "rid": "unknown-rid", "history": []}
        messages = [json.dumps(response)]
        ws = mock_ws_messages(messages)

        # Should complete without error
        await poller._process_ws(ws)


class TestStartupSuppression:
    @pytest.mark.asyncio
    async def test_startup_done_set_after_first_fetch(self):
        """_startup_done becomes True after first successful fetch."""
        from monitor.poller import ShotPoller

        poller = ShotPoller(host=TEST_HOST, on_shot=AsyncMock())
        assert poller._startup_done is False

        history_resp = {"tp": "res:history:list", "rid": None, "history": []}

        async def fake_ws_request(ws, tp, params=None, timeout=15.0):
            return {"history": []}

        with patch.object(poller, "_ws_request", side_effect=fake_ws_request):
            with patch.object(poller, "_get_known_ids", new_callable=AsyncMock, return_value=set()):
                ws = mock_ws_messages([])
                await poller._fetch_and_process_shots(ws)

        assert poller._startup_done is True

    @pytest.mark.asyncio
    async def test_startup_done_set_even_on_timeout(self):
        """_startup_done is set True even when ws_request times out."""
        from monitor.poller import ShotPoller

        poller = ShotPoller(host=TEST_HOST, on_shot=AsyncMock())

        async def fake_ws_request_timeout(ws, tp, params=None, timeout=15.0):
            raise asyncio.TimeoutError()

        with patch.object(poller, "_ws_request", side_effect=fake_ws_request_timeout):
            ws = mock_ws_messages([])
            await poller._fetch_and_process_shots(ws)

        assert poller._startup_done is True


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

        # Verify execute was called (INSERT OR IGNORE)
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        sql = call_args[0][0]
        assert "shots" in sql.lower()
        assert "INSERT" in sql.upper()
