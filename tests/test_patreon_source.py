"""Tests for PatreonSource — auth, navigation, stealth parameters."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.sources.patreon import (
    PatreonSource,
    SCROLL_PX_MIN, SCROLL_PX_MAX,
    SCROLL_DELAY_MIN, SCROLL_DELAY_MAX,
    READING_PAUSE_CHANCE,
    MOUSE_MOVE_CHANCE,
)


@pytest.fixture
def cdp():
    mock = AsyncMock()
    mock.js = AsyncMock()
    mock.navigate = AsyncMock()
    mock.move_mouse = AsyncMock()
    return mock


async def test_authenticate_valid_session(cdp):
    cdp.js.return_value = False
    source = PatreonSource()
    result = await source.authenticate(cdp)
    assert result is True
    cdp.navigate.assert_any_call("https://www.patreon.com/home", wait=5.0)


async def test_authenticate_detects_login_and_fills_credentials(cdp):
    cdp.js.side_effect = [
        True,   # login form detected
        None,   # fill email
        None,   # click continue
        None,   # fill password
        None,   # submit
        False,  # login form gone = success
    ]
    with patch("src.capture.credentials.read_credential") as mock_cred:
        mock_cred.return_value = ("user@test.com", "pass123")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            source = PatreonSource()
            result = await source.authenticate(cdp)
    assert result is True


async def test_authenticate_fails_no_credentials(cdp):
    cdp.js.return_value = True
    with patch("src.capture.credentials.read_credential") as mock_cred:
        mock_cred.return_value = None
        source = PatreonSource()
        result = await source.authenticate(cdp)
    assert result is False


async def test_authenticate_fails_login_still_present(cdp):
    cdp.js.side_effect = [
        True,   # login form detected
        None,   # fill email
        None,   # click continue
        None,   # fill password
        None,   # submit
        True,   # login form still there = failure
    ]
    with patch("src.capture.credentials.read_credential") as mock_cred:
        mock_cred.return_value = ("user@test.com", "pass123")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            source = PatreonSource()
            result = await source.authenticate(cdp)
    assert result is False


async def test_navigate_to_calls_cdp_navigate(cdp):
    source = PatreonSource()
    with patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("random.random", return_value=0.99):
        await source.navigate_to(cdp, "https://patreon.com/post/123")
    cdp.navigate.assert_called_once_with("https://patreon.com/post/123", wait=8.0)


async def test_navigate_to_with_mouse_move(cdp):
    source = PatreonSource()
    with patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("random.random", return_value=0.1), \
         patch("random.randint", return_value=600), \
         patch("random.uniform", return_value=0.2):
        await source.navigate_to(cdp, "https://patreon.com/post/123")
    cdp.move_mouse.assert_called_once()


def test_stealth_parameters():
    assert SCROLL_PX_MIN == 600
    assert SCROLL_PX_MAX == 1000
    assert SCROLL_DELAY_MIN == 1.5
    assert SCROLL_DELAY_MAX == 5.0
    assert READING_PAUSE_CHANCE == 0.20
    assert MOUSE_MOVE_CHANCE == 0.65


async def test_get_posts_returns_empty(cdp):
    source = PatreonSource()
    posts = await source.get_posts(cdp)
    assert posts == []
