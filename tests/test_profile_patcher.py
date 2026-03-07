import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_patch_profile_applies_adjustments_and_calls_put(tmp_path):
    """patch_profile fetches profile, applies adjustments, PUTs patched profile, and verifies."""
    import db
    db.DB_PATH = str(tmp_path / "test.db")
    await db.init_db()

    current_profile = {
        "name": "default",
        "steps": [
            {"name": "infuse", "pressure": 4.0, "flow": 2.0},
            {"name": "extract", "pressure": 9.0, "flow": 3.0},
        ],
    }

    adjustments = [
        {"step_name": "extract", "field": "pressure", "new_value": 8.5},
    ]

    # Build mock responses: GET (current), PUT, GET (verify)
    get_response_1 = AsyncMock()
    get_response_1.raise_for_status = MagicMock()
    get_response_1.json = AsyncMock(return_value=current_profile)

    put_response = AsyncMock()
    put_response.raise_for_status = MagicMock()

    verify_profile = json.loads(json.dumps(current_profile))
    verify_profile["steps"][1]["pressure"] = 8.5
    get_response_2 = AsyncMock()
    get_response_2.raise_for_status = MagicMock()
    get_response_2.json = AsyncMock(return_value=verify_profile)

    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=[
        _async_cm(get_response_1),
        _async_cm(get_response_2),
    ])
    mock_session.put = MagicMock(return_value=_async_cm(put_response))

    mock_client_session = MagicMock()
    mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_client_session):
        from profile_patcher import patch_profile
        result = await patch_profile(adjustments)

    assert result["success"] is True
    # PUT was called with the patched profile
    mock_session.put.assert_called_once()
    put_call_kwargs = mock_session.put.call_args
    patched_body = put_call_kwargs[1]["json"]
    extract_step = next(s for s in patched_body["steps"] if s["name"] == "extract")
    assert extract_step["pressure"] == 8.5


class _async_cm:
    """Minimal async context manager wrapping a mock response."""
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        return False
