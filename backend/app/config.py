"""Runtime settings, overridable via environment variables."""
import os
import sys
from pathlib import Path

HOST = os.environ.get("SHEET2TAB_HOST", "0.0.0.0")  # 0.0.0.0 = reachable from the LAN
PORT = int(os.environ.get("SHEET2TAB_PORT", "8000"))

OMR_TIMEOUT_S = int(os.environ.get("SHEET2TAB_OMR_TIMEOUT", "600"))
# Longest image side fed to OMR; phone photos are much larger than oemer needs.
OMR_MAX_SIDE = int(os.environ.get("SHEET2TAB_OMR_MAX_SIDE", "2500"))
# OMR results (MusicXML) are cached here by image hash, so re-running the same photo
# skips the minutes-long OMR step. Set to an empty string to disable.
_cache_dir = os.environ.get("SHEET2TAB_OMR_CACHE_DIR", str(Path(__file__).resolve().parents[1] / ".omr_cache"))
OMR_CACHE_DIR = Path(_cache_dir) if _cache_dir else None
# When OMR fails, the image oemer got and its full output are saved here for debugging.
_failure_dir = os.environ.get("SHEET2TAB_OMR_FAILURE_DIR", str(Path(__file__).resolve().parents[1] / ".omr_failures"))
OMR_FAILURE_DIR = Path(_failure_dir) if _failure_dir else None
MAX_UPLOAD_MB = int(os.environ.get("SHEET2TAB_MAX_UPLOAD_MB", "20"))  # per file
MAX_PAGES = int(os.environ.get("SHEET2TAB_MAX_PAGES", "20"))
