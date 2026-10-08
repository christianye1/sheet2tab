from app.jobs import Job
from app.omr import parse_oemer_line


def test_parse_oemer_stage_lines():
    assert parse_oemer_line("2026-10-08 10:00:00 Extracting stafflines\n") == ("Extracting staff lines", None)
    assert parse_oemer_line("2026-10-08 10:00:00 Extracting staffline and symbols") == \
        ("Finding staff lines and symbols", None)
    assert parse_oemer_line("2026-10-08 10:00:00 Extracting symbols") == \
        ("Finding clefs, rests and barlines", None)


def test_parse_oemer_batch_counter():
    assert parse_oemer_line("12/48 (step: 8)") == (None, 0.25)
    assert parse_oemer_line("1280 1024") == (None, None)


def test_job_progress_and_stage_timings():
    job = Job()
    job.update("Preparing image", 0.0)
    job.update("Finding staff lines and symbols", 0.5)
    mid = job.progress
    assert 0 < mid < 1
    job.update("Preparing image", 0.0)  # out-of-order report never moves the bar back
    assert job.progress == mid
    job.finish(result={"tab_text": ""})
    d = job.to_dict()
    assert d["status"] == "done" and d["progress"] == 1.0
    assert all(s["done"] for s in d["stages"])
    assert d["stages"][0]["name"] == "Preparing image"


def test_omr_cache_hit_skips_oemer(tmp_path, monkeypatch):
    from app import config, omr

    monkeypatch.setattr(config, "OMR_CACHE_DIR", tmp_path / "cache")
    image = b"fake image bytes"
    calls = []

    def fake_oemer(image_path, out_dir, on_progress=None, cancel=None):
        calls.append(image_path)
        out = out_dir / "input.musicxml"
        out.write_text("<score/>")
        return out

    monkeypatch.setattr(omr, "preprocess", lambda data: __import__("numpy").zeros((4, 4, 3), "uint8"))
    monkeypatch.setattr(omr, "run_oemer", fake_oemer)
    first = omr.image_to_musicxml(image, tmp_path)
    stages = []
    second = omr.image_to_musicxml(image, tmp_path, lambda stage, f: stages.append(stage))
    assert len(calls) == 1
    assert second.read_text() == first.read_text() == "<score/>"
    assert stages == [omr.CACHE_STAGE]


def test_oemer_merge_handles_a_single_box():
    from app.oemer_runner import _safe_merge_nearby_bbox

    assert _safe_merge_nearby_bbox([], 10) == []
    assert _safe_merge_nearby_bbox([(0, 0, 5, 5)], 10) == [(0, 0, 5, 5)]
    assert len(_safe_merge_nearby_bbox([(0, 0, 5, 5), (1, 1, 6, 6)], 10)) == 1


def test_cancel_kills_oemer(tmp_path, monkeypatch):
    import sys
    import threading
    import time

    import pytest

    from app import omr

    # Stand-in for oemer: a process that would run for a minute.
    monkeypatch.setattr(omr.sys, "executable", sys.executable)
    real_popen = omr.subprocess.Popen
    monkeypatch.setattr(omr.subprocess, "Popen",
                        lambda cmd, **kw: real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kw))
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    start = time.monotonic()
    with pytest.raises(omr.OMRCancelled):
        omr.run_oemer(tmp_path / "input.png", tmp_path, cancel=cancel)
    assert time.monotonic() - start < 5


def test_cancelled_job_ignores_late_progress():
    job = Job()
    job.update("Classifying symbols", 0.5)
    job.finish(cancelled=True)
    job.update("Classifying symbols", 0.9)
    assert job.to_dict()["status"] == "cancelled"


def test_progress_spans_all_pages():
    job = Job()
    job.set_page(1, 4)  # second of four pages
    job.update("Preparing image", 0.0)
    d = job.to_dict()
    assert d["stages"][-1]["name"] == "Page 2/4: Preparing image"
    assert 0.25 <= d["progress"] < 0.3
