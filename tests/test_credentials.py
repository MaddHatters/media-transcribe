"""Tests for Windows Credential Manager reader."""
from unittest.mock import patch, MagicMock

from src.capture.credentials import read_credential


def test_non_windows_returns_none():
    with patch("src.capture.credentials.IS_WINDOWS", False):
        assert read_credential("test_target") is None


def test_successful_credential_read():
    with patch("src.capture.credentials.IS_WINDOWS", True):
        mock_ctypes = MagicMock()
        mock_wintypes = MagicMock()

        cred_mock = MagicMock()
        cred_mock.UserName = "user@example.com"
        cred_mock.CredentialBlobSize = 24
        cred_mock.CredentialBlob = MagicMock()

        mock_advapi32 = MagicMock()
        mock_advapi32.CredReadW.return_value = True
        mock_advapi32.CredFree = MagicMock()

        mock_ctypes.windll.advapi32 = mock_advapi32
        mock_ctypes.wintypes = mock_wintypes

        ptr_mock = MagicMock()
        ptr_mock.contents = cred_mock

        mock_ctypes.POINTER.return_value.return_value = ptr_mock
        mock_ctypes.byref.return_value = MagicMock()
        mock_ctypes.string_at.return_value = "password123".encode("utf-16-le")

        with patch.dict("sys.modules", {
            "ctypes": mock_ctypes,
            "ctypes.wintypes": mock_wintypes,
        }):
            with patch("src.capture.credentials._read_credential_win32") as mock_read:
                mock_read.return_value = ("user@example.com", "password123")
                result = read_credential("patreon_02_ai")

        assert result == ("user@example.com", "password123")


def test_missing_credential_returns_none():
    with patch("src.capture.credentials.IS_WINDOWS", True):
        with patch("src.capture.credentials._read_credential_win32") as mock_read:
            mock_read.return_value = None
            result = read_credential("nonexistent_target")
    assert result is None
