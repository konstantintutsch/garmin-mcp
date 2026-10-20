"""Runtime configuration, resolved from environment variables."""

import os
from pathlib import Path

DEFAULT_TOKENSTORE = "~/.garmin-mcp"
DEFAULT_MAX_CHARS = 100_000


def tokenstore() -> str:
    """Directory (or .json file) holding the saved Garmin session tokens."""
    return str(Path(os.environ.get("GARMIN_MCP_TOKENSTORE", DEFAULT_TOKENSTORE)).expanduser())


def download_dir() -> Path:
    """Where downloaded activity files (FIT/GPX/TCX/...) are written."""
    default = Path(tokenstore()) / "downloads"
    return Path(os.environ.get("GARMIN_MCP_DOWNLOAD_DIR", default)).expanduser()


def is_cn() -> bool:
    """Whether the account lives on Garmin's China (garmin.cn) servers."""
    return os.environ.get("GARMIN_IS_CN", "").lower() in {"1", "true", "yes"}
