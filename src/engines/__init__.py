from src.engines.base import CaptureEngine, EngineStatus
from src.engines.null_engine import NullEngine

__all__ = ["CaptureEngine", "EngineStatus", "NullEngine"]


def get_obs_engine(**kwargs):
    from src.engines.obs_engine import OBSEngine
    return OBSEngine(**kwargs)


def get_ytdlp_engine(**kwargs):
    from src.engines.ytdlp_engine import YtDlpEngine
    return YtDlpEngine(**kwargs)
