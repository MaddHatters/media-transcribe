"""Put the (non-package) script dirs on sys.path so tests can import them."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("transcribe", "acquire", "experts"):
    sys.path.insert(0, str(ROOT / sub))
