import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env file from project root if it exists."""
    for candidate in [Path(".env"), Path(__file__).resolve().parent.parent / ".env"]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
            break


_load_dotenv()

PORT = int(os.getenv("AGENT_PORT", "8421"))
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")


def validate_config() -> None:
    """Fail-fast if AGENT_TOKEN is not set or too short."""
    if not AGENT_TOKEN:
        print("FATAL: AGENT_TOKEN environment variable is not set.", file=sys.stderr)
        print("Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"", file=sys.stderr)
        sys.exit(1)
    if len(AGENT_TOKEN) < 32:
        print(f"FATAL: AGENT_TOKEN must be >= 32 chars (got {len(AGENT_TOKEN)}).", file=sys.stderr)
        sys.exit(1)
