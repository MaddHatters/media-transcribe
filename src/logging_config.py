"""Centralized logging, excepthook, and crash guards for the pipeline."""
from __future__ import annotations

import atexit
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path


def setup_logging(command: str, foreground: bool = False) -> Path:
    from src.config import LOGS_DIR

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"{command}_{timestamp}.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if foreground:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    sys.excepthook = _unhandled_exception_hook
    atexit.register(_emergency_stop_obs)

    from src.config import IS_WINDOWS

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    if IS_WINDOWS:
        signal.signal(signal.SIGBREAK, _signal_handler)

    return log_file


def _unhandled_exception_hook(exc_type, exc_value, exc_tb):
    logging.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _emergency_stop_obs():
    try:
        from src.engines.obs_engine import OBSEngine

        engine = OBSEngine()
        engine.connect()
        if engine.is_recording():
            engine.stop()
            logging.warning("[crash-guard] Stopped orphaned OBS recording")
        engine.disconnect()
    except Exception:
        pass


def _signal_handler(signum, frame):
    _emergency_stop_obs()
    logging.warning("[crash-guard] Received signal %s, exiting", signal.Signals(signum).name)
    sys.exit(128 + signum)
