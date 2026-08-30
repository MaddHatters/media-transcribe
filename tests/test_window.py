"""Tests for Win32 window management — platform-conditional."""
from unittest.mock import patch, MagicMock

from src.capture.window import focus_chrome, find_window, maximize_window, minimize_window


def test_focus_chrome_non_windows():
    with patch("src.capture.window.IS_WINDOWS", False):
        assert focus_chrome() is False


def test_find_window_non_windows():
    with patch("src.capture.window.IS_WINDOWS", False):
        assert find_window(class_name="Chrome_WidgetWin_1") is None


def test_maximize_window_non_windows():
    with patch("src.capture.window.IS_WINDOWS", False):
        maximize_window(12345)


def test_minimize_window_non_windows():
    with patch("src.capture.window.IS_WINDOWS", False):
        minimize_window(12345)


def test_focus_chrome_win32_calls():
    mock_user32 = MagicMock()
    mock_user32.FindWindowW.return_value = 12345

    mock_ctypes = MagicMock()
    mock_ctypes.windll.user32 = mock_user32

    with patch("src.capture.window.IS_WINDOWS", True), \
         patch.dict("sys.modules", {"ctypes": mock_ctypes}), \
         patch("src.capture.window._focus_chrome_win32") as mock_focus:
        mock_focus.return_value = True
        result = focus_chrome()
    assert result is True


def test_focus_chrome_window_not_found():
    with patch("src.capture.window.IS_WINDOWS", True), \
         patch("src.capture.window._focus_chrome_win32") as mock_focus:
        mock_focus.return_value = False
        result = focus_chrome()
    assert result is False


def test_maximize_window_no_hwnd():
    with patch("src.capture.window.IS_WINDOWS", True):
        maximize_window(0)


def test_minimize_window_no_hwnd():
    with patch("src.capture.window.IS_WINDOWS", True):
        minimize_window(0)
