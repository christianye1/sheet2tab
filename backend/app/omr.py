"""Optical Music Recognition: image bytes -> MusicXML file, via the oemer CLI."""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from . import config
from .tab_detect import has_tab_staffs


logger = logging.getLogger(__name__)


class OMRError(Exception):
    pass


class OMRCancelled(Exception):
    """The user cancelled the conversion; oemer was stopped."""


def _save_failure(image_path: Path, output: list[str]) -> Path | None:
    """Keep the image oemer got and its full output, to reproduce the failure later."""
    if not config.OMR_FAILURE_DIR:
        return None
    stem = time.strftime("%Y%m%d-%H%M%S")
    config.OMR_FAILURE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(image_path, config.OMR_FAILURE_DIR / f"{stem}.png")
    (config.OMR_FAILURE_DIR / f"{stem}.log").write_text("\n".join(output))
    return config.OMR_FAILURE_DIR / f"{stem}.png"


# Called with (stage label, fraction of that stage done, 0..1).
ProgressFn = Callable[[str, float], None]

PREPARE_STAGE = "Preparing image"
CACHE_STAGE = "Using cached OMR result"
# Python startup and model loading, before oemer logs anything.
LOADING_STAGE = "Loading OMR models"
# oemer log message -> stage label shown in the app, in pipeline order.
OEMER_STAGES = {
    "Extracting staffline and symbols": "Finding staff lines and symbols",
    "Extracting layers of different symbols": "Classifying symbols",
    "Dewarping": "Straightening the page",
    "Extracting stafflines": "Extracting staff lines",
    "Extracting noteheads": "Finding noteheads",
    "Grouping noteheads": "Grouping notes",
    "Extracting symbols": "Finding clefs, rests and barlines",
    "Extracting rhythm types": "Reading rhythms",
    "Building MusicXML document": "Writing MusicXML",
}
# oemer prints "12/40 (step: 8)" per batch while its neural networks run.
_BATCH_RE = re.compile(r"(\d+)/(\d+) \(step")


def parse_oemer_line(line: str) -> tuple[str | None, float | None]:
    """(new stage label, None) for a stage log line, (None, fraction) for a batch counter."""
    for message, label in OEMER_STAGES.items():
        if message in line:
            return label, None
    m = _BATCH_RE.search(line)
    if m and int(m.group(2)):
        return None, int(m.group(1)) / int(m.group(2))
    return None, None


def preprocess(image_bytes: bytes, max_side: int = config.OMR_MAX_SIDE) -> np.ndarray:
    """Decode (honouring EXIF rotation) and scale the longest side to `max_side`.

    Large phone photos are scaled down. Small images (screenshots, low-res PNGs) are
    scaled up: at ~1000 px, staff lines are ~7 px apart and oemer misses some of them
    (StafflineNotAligned); enlarged, the same image converts fine.

    Deskewing/dewarping is left to oemer. Contrast enhancement (CLAHE) was tried
    and broke oemer's dewarping step, so the colour image is passed through as-is.
    """
    buf = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)  # applies EXIF orientation
    if img is None:
        raise OMRError("Could not decode image (expected JPEG or PNG)")

    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale != 1:
        interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=interpolation)
    return img


def run_oemer(
    image_path: Path,
    out_dir: Path,
    on_progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    report = on_progress or (lambda stage, fraction: None)
    # Text mode turns the "\r" of oemer's batch counters into line breaks.
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.oemer_runner", str(image_path), "-o", str(out_dir)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        cwd=Path(__file__).resolve().parents[1],  # so `-m app.oemer_runner` resolves
    )

    output: list[str] = []

    def read_output() -> None:
        stage = LOADING_STAGE
        report(stage, 0.0)
        for line in proc.stdout:
            if not line.strip():
                continue
            output.append(line.rstrip())
            new_stage, fraction = parse_oemer_line(line)
            if new_stage:
                stage = new_stage
                report(stage, 0.0)
            elif fraction is not None:
                report(stage, fraction)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    deadline = time.monotonic() + config.OMR_TIMEOUT_S
    try:
        while proc.poll() is None:
            if cancel is not None and cancel.wait(0.2):
                proc.kill()
                proc.wait()
                raise OMRCancelled()
            if cancel is None:
                time.sleep(0.2)
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                raise OMRError(f"OMR timed out after {config.OMR_TIMEOUT_S}s")
    finally:
        reader.join(timeout=5)

    out = out_dir / f"{image_path.stem}.musicxml"
    if proc.returncode != 0 or not out.exists():
        saved = _save_failure(image_path, output)
        logger.error("OMR failed; input and full oemer output saved to %s\n%s",
                     saved, "\n".join(output[-20:]))
        last = output[-1:] or ["no output"]
        raise OMRError(
            "Could not recognize sheet music in this photo. Try a flat, well-lit page "
            f"that fills the frame.\n\nDetails: {last[0]}"
        )
    return out


def cache_key(image_bytes: bytes) -> str:
    """Same upload + same OMR settings -> same key."""
    h = hashlib.sha256(image_bytes)
    h.update(f"max_side={config.OMR_MAX_SIDE}".encode())
    return h.hexdigest()


def image_to_musicxml(
    image_bytes: bytes,
    work_dir: Path,
    on_progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    cached = config.OMR_CACHE_DIR / f"{cache_key(image_bytes)}.musicxml" if config.OMR_CACHE_DIR else None
    if cached and cached.exists():
        if on_progress:
            on_progress(CACHE_STAGE, 0.0)
        return cached

    if on_progress:
        on_progress(PREPARE_STAGE, 0.0)
    img = preprocess(image_bytes)
    if has_tab_staffs(img):
        raise OMRError(
            "This sheet already contains guitar tab (6-line TAB staffs). Sheet2Tab converts "
            "standard notation only; scan a page with regular 5-line staffs."
        )
    image_path = work_dir / "input.png"
    cv2.imwrite(str(image_path), img)
    out = run_oemer(image_path, work_dir, on_progress, cancel)

    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".tmp")
        shutil.copyfile(out, tmp)
        tmp.replace(cached)  # atomic: a half-written file is never picked up
    return out
