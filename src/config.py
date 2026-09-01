"""Single source of truth for paths, network endpoints, and behavior constants."""
from __future__ import annotations

import sys
from pathlib import Path

# -- Paths: obs-machine (Windows) --
SCRIPTS_DIR = Path(r"C:\Users\Matt\agent-control\scripts")
STATE_DIR = Path(r"C:\Users\Matt\agent-control\state")
LOGS_DIR = Path(r"C:\Users\Matt\agent-control\logs")
BACKUP_DIR = Path(r"D:\MasterClass Video Backup")
CHROME_PATH = Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")
CHROME_PROFILE = Path(r"C:\Users\Matt\agent-control\chrome-profile")
OBS_PATH = Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe")

# -- Paths: devbox-01 (Linux) --
LOCAL_TRANSCRIPTS = Path("/mnt/secondary/media/patreon/FIRE Investing Masterclass/transcripts")
LOCAL_DATA = Path("/home/tuna/repos/media-transcribe/data")

# -- Network --
CDP_URL = "http://localhost:9222"
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = "DK4HLJPKgslAhEgD"
SSH_HOST = "Matt@100.66.194.100"
REMOTE_PROJECT_DIR = "C:/Users/Matt/transcribe"
SSH_OPTS = ["-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=no"]

# -- Recording behavior --
BREAK_MIN_SECONDS = 300
BREAK_MAX_SECONDS = 1500
CRED_TARGET = "patreon_02_ai"

# -- Chrome launch flags --
CHROME_FLAGS = [
    f"--user-data-dir={CHROME_PROFILE}",
    "--remote-debugging-port=9222",
    "--start-maximized",
    "--autoplay-policy=no-user-gesture-required",
]

# -- Scheduled task names --
SCHTASK_NAME_CHROME = "MediaTranscribe_Chrome"
SCHTASK_NAME_OBS = "MediaTranscribe_OBS"
TEMP_BAT_DIR = SCRIPTS_DIR / "temp"

# -- Platform detection --
IS_WINDOWS = sys.platform == "win32"
