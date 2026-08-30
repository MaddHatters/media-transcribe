"""Windows Credential Manager reader (ctypes / advapi32.dll)."""
from __future__ import annotations

import logging

from src.config import IS_WINDOWS

log = logging.getLogger(__name__)


def _read_credential_win32(target: str) -> tuple[str, str] | None:
    """Internal: read from Windows Credential Manager via ctypes."""
    try:
        import ctypes
        import ctypes.wintypes
    except ImportError:
        log.warning("ctypes.wintypes unavailable")
        return None

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", ctypes.wintypes.DWORD),
            ("Type", ctypes.wintypes.DWORD),
            ("TargetName", ctypes.wintypes.LPWSTR),
            ("Comment", ctypes.wintypes.LPWSTR),
            ("LastWritten", ctypes.wintypes.FILETIME),
            ("CredentialBlobSize", ctypes.wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
            ("Persist", ctypes.wintypes.DWORD),
            ("AttributeCount", ctypes.wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", ctypes.wintypes.LPWSTR),
            ("UserName", ctypes.wintypes.LPWSTR),
        ]

    try:
        advapi32 = ctypes.windll.advapi32
    except AttributeError:
        log.warning("ctypes.windll unavailable")
        return None

    cred_ptr = ctypes.POINTER(CREDENTIAL)()
    ok = advapi32.CredReadW(target, 1, 0, ctypes.byref(cred_ptr))
    if not ok:
        log.warning("CredReadW failed for target=%s", target)
        return None
    try:
        cred = cred_ptr.contents
        username = cred.UserName or ""
        password = ctypes.string_at(
            cred.CredentialBlob, cred.CredentialBlobSize,
        ).decode("utf-16-le")
        return (username, password)
    finally:
        advapi32.CredFree(cred_ptr)


def read_credential(target: str) -> tuple[str, str] | None:
    """Read username + password from Windows Credential Manager.

    Returns (username, password) or None if not found or not on Windows.
    """
    if not IS_WINDOWS:
        log.debug("Not Windows — credential read skipped")
        return None

    return _read_credential_win32(target)
