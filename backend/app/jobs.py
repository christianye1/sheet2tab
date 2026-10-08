"""Background conversion jobs, so the app can poll progress while OMR runs."""
from __future__ import annotations

import threading
import time
import uuid

# Stages in pipeline order, with their rough share of total time. Measured on a
# sample page on a laptop CPU: the two neural-network passes take ~95% of the time.
# Only used to turn the current stage into a percentage.
STAGE_WEIGHTS = {
    "Using cached OMR result": 1,
    "Preparing image": 1,
    "Loading OMR models": 1,
    "Finding staff lines and symbols": 45,
    "Classifying symbols": 47,
    "Straightening the page": 1,
    "Extracting staff lines": 1,
    "Finding noteheads": 1,
    "Grouping notes": 1,
    "Finding clefs, rests and barlines": 1,
    "Reading rhythms": 1,
    "Writing MusicXML": 1,
    "Building tab": 1,
}
_STAGE_ORDER = list(STAGE_WEIGHTS)
_TOTAL_WEIGHT = sum(STAGE_WEIGHTS.values())
# Finished jobs are forgotten after this many seconds.
JOB_TTL_S = 3600


class Job:
    def __init__(self) -> None:
        self.id = uuid.uuid4().hex
        self.status = "queued"  # queued | running | done | failed | cancelled
        self.created = time.monotonic()
        self.progress = 0.0
        self.result: dict | None = None
        self.error: str | None = None
        self._stages: list[list] = []  # [name, start, end or None]
        self._lock = threading.Lock()
        self.cancel_requested = threading.Event()
        self.page, self.pages = 0, 1

    def set_page(self, page: int, pages: int) -> None:
        """Page callback for pipeline.images_to_tab: `page` (0-based) of `pages` starts."""
        with self._lock:
            self.page, self.pages = page, pages

    def update(self, stage: str, fraction: float) -> None:
        """Progress callback for pipeline.images_to_tab."""
        now = time.monotonic()
        with self._lock:
            if self.finished:
                return  # late report from oemer's output reader after a cancel
            self.status = "running"
            # With several pages, each page's steps are listed (and timed) separately.
            name = stage if self.pages == 1 or stage == "Building tab" else (
                f"Page {self.page + 1}/{self.pages}: {stage}")
            if not self._stages or self._stages[-1][0] != name:
                if self._stages:
                    self._stages[-1][2] = now
                self._stages.append([name, now, None])
            if stage in STAGE_WEIGHTS:
                idx = _STAGE_ORDER.index(stage)
                done = sum(STAGE_WEIGHTS[s] for s in _STAGE_ORDER[:idx])
                current = STAGE_WEIGHTS[stage] * min(max(fraction, 0.0), 1.0)
                within_page = (done + current) / _TOTAL_WEIGHT
                # Never move the bar backwards.
                self.progress = max(self.progress, (self.page + within_page) / self.pages)

    @property
    def finished(self) -> bool:
        return self.status in ("done", "failed", "cancelled")

    def cancel(self) -> None:
        """Ask the worker to stop; it marks the job cancelled once oemer is killed."""
        self.cancel_requested.set()

    def finish(self, result: dict | None = None, error: str | None = None, cancelled: bool = False) -> None:
        with self._lock:
            if self._stages and self._stages[-1][2] is None:
                self._stages[-1][2] = time.monotonic()
            self.result, self.error = result, error
            self.status = "cancelled" if cancelled else "failed" if error else "done"
            if self.status == "done":
                self.progress = 1.0

    def to_dict(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "stage": self._stages[-1][0] if self._stages else None,
                "progress": round(self.progress, 3),
                "elapsed": round(now - self.created, 1),
                "stages": [
                    {"name": name, "seconds": round((end or now) - start, 1), "done": end is not None}
                    for name, start, end in self._stages
                ],
                "result": self.result,
                "error": self.error,
            }


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def create_job() -> Job:
    job = Job()
    now = time.monotonic()
    with _jobs_lock:
        for old in [j for j in _jobs.values() if now - j.created > JOB_TTL_S]:
            del _jobs[old.id]
        _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    with _jobs_lock:
        return _jobs.get(job_id)
