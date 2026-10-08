"""HTTP API.  Run with:  python -m app.main"""
from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile

from . import config
from .jobs import Job, create_job, get_job
from .omr import OMRCancelled, OMRError
from .pipeline import BUILD_TAB_STAGE, INSTRUMENTS, image_to_tab, images_to_tab, musicxml_pages_to_tab

app = FastAPI(title="sheet2tab")
logger = logging.getLogger(__name__)

IMAGE_TYPES = {"image/jpeg", "image/png"}
MUSICXML_SUFFIXES = {".musicxml", ".xml", ".mxl"}
# OMR is CPU- and memory-heavy; run one at a time.
_omr_lock = threading.Lock()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    """Validate an upload; returns (data, suffix) where suffix marks MusicXML uploads."""
    data = file.file.read()
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File larger than {config.MAX_UPLOAD_MB} MB")
    if not data:
        raise HTTPException(400, "Empty upload")

    suffix = Path(file.filename or "").suffix.lower()
    if (suffix not in MUSICXML_SUFFIXES and file.content_type not in IMAGE_TYPES
            and suffix not in {".jpg", ".jpeg", ".png"}):
        raise HTTPException(415, "Upload a JPEG or PNG image")
    return data, suffix


def _check_instrument(instrument: str) -> str:
    if instrument not in INSTRUMENTS:
        raise HTTPException(422, f"instrument must be one of {', '.join(INSTRUMENTS)}")
    return instrument


def _musicxml_bytes_to_tab(data: bytes, suffix: str, instrument: str) -> dict:
    return _musicxml_pages_to_tab([(data, suffix)], instrument)


def _musicxml_pages_to_tab(uploads: list[tuple[bytes, str]], instrument: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="sheet2tab-") as tmp:
        paths = []
        for i, (data, suffix) in enumerate(uploads):
            path = Path(tmp) / f"page{i + 1}{suffix}"
            path.write_bytes(data)
            paths.append(path)
        return musicxml_pages_to_tab(paths, instrument=instrument)


@app.post("/convert")
def convert(file: UploadFile, instrument: str = Form("guitar")) -> dict:
    """Synchronous conversion: the request stays open until the tab is ready."""
    # Plain `def`: FastAPI runs it in a worker thread, so slow OMR doesn't block /health.
    _check_instrument(instrument)
    data, suffix = _read_upload(file)
    if suffix in MUSICXML_SUFFIXES:
        # Handy for testing the API without waiting for OMR.
        return _musicxml_bytes_to_tab(data, suffix, instrument)
    with _omr_lock:
        try:
            return image_to_tab(data, instrument=instrument)
        except OMRError as e:
            raise HTTPException(422, str(e))


@app.post("/jobs", status_code=202)
def start_job(file: list[UploadFile], instrument: str = Form("guitar")) -> dict:
    """Start a conversion in the background; poll GET /jobs/{id} for progress and the result.

    Several `file` fields = consecutive pages of one piece, converted into one result.
    `instrument` ("guitar" or "piano") is a form field next to the files.
    """
    _check_instrument(instrument)
    if len(file) > config.MAX_PAGES:
        raise HTTPException(413, f"At most {config.MAX_PAGES} pages per conversion")
    uploads = [_read_upload(f) for f in file]
    kinds = {suffix in MUSICXML_SUFFIXES for _, suffix in uploads}
    if len(kinds) > 1:
        raise HTTPException(415, "Upload either images or MusicXML files, not both")
    job = create_job()
    threading.Thread(target=_run_job, args=(job, uploads, instrument), daemon=True).start()
    return job.to_dict()


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job (the server may have restarted)")
    return job.to_dict()


@app.delete("/jobs/{job_id}")
def cancel_job(job_id: str) -> dict:
    """Stop a conversion; GET /jobs/{id} reports "cancelled" once oemer has been stopped."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job (the server may have restarted)")
    job.cancel()
    return job.to_dict()


def _run_job(job: Job, uploads: list[tuple[bytes, str]], instrument: str) -> None:
    try:
        if uploads[0][1] in MUSICXML_SUFFIXES:
            job.update(BUILD_TAB_STAGE, 0.0)
            job.finish(result=_musicxml_pages_to_tab(uploads, instrument))
            return
        # Wait for the running conversion, but stay cancellable while queued.
        while not _omr_lock.acquire(timeout=0.5):
            if job.cancel_requested.is_set():
                raise OMRCancelled()
        try:
            job.finish(result=images_to_tab([data for data, _ in uploads], on_progress=job.update,
                                            cancel=job.cancel_requested, instrument=instrument,
                                            on_page=job.set_page))
        finally:
            _omr_lock.release()
    except OMRCancelled:
        job.finish(cancelled=True)
    except OMRError as e:
        job.finish(error=str(e))
    except Exception as e:
        logger.exception("Job %s failed", job.id)
        job.finish(error=f"Internal error: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT)
