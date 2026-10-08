import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "ode_to_joy.musicxml"


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_convert_musicxml_upload():
    with SAMPLE.open("rb") as f:
        r = client.post("/convert", files={"file": ("ode.musicxml", f, "application/xml")})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"instrument", "tab_text", "notes", "tempo_bpm", "warnings"}
    assert body["tab_text"].startswith("e|")


def test_rejects_non_image():
    r = client.post("/convert", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_undecodable_image_is_422():
    r = client.post("/convert", files={"file": ("x.jpg", b"not a jpeg", "image/jpeg")})
    assert r.status_code == 422
    assert "decode" in r.json()["detail"]


def test_job_for_musicxml_upload():
    with SAMPLE.open("rb") as f:
        r = client.post("/jobs", files={"file": ("ode.musicxml", f, "application/xml")})
    assert r.status_code == 202
    job_id = r.json()["id"]
    for _ in range(100):
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert body["status"] == "done"
    assert body["progress"] == 1.0
    assert body["result"]["tab_text"].startswith("e|")
    assert [s["name"] for s in body["stages"]] == ["Building tab"]


def test_failed_job_reports_error():
    r = client.post("/jobs", files={"file": ("x.jpg", b"not a jpeg", "image/jpeg")})
    job_id = r.json()["id"]
    for _ in range(100):
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert body["status"] == "failed"
    assert "decode" in body["error"]


def test_unknown_job_is_404():
    assert client.get("/jobs/nope").status_code == 404


def wait_for(job_id):
    for _ in range(100):
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.05)
    return body


def test_job_with_several_pages_chains_them():
    data = SAMPLE.read_bytes()
    r = client.post("/jobs", files=[("file", ("p1.musicxml", data, "application/xml")),
                                    ("file", ("p2.musicxml", data, "application/xml"))])
    body = wait_for(r.json()["id"])
    one = client.post("/convert", files={"file": ("p.musicxml", data, "application/xml")}).json()
    notes = body["result"]["notes"]
    assert len(notes) == 2 * len(one["notes"])
    page_length = max(n["start"] + n["duration"] for n in one["notes"])
    second = notes[len(one["notes"])]
    assert second["start"] == page_length
    assert second["measure"] == max(n["measure"] for n in one["notes"]) + 1


def test_job_rejects_mixed_images_and_musicxml():
    r = client.post("/jobs", files=[("file", ("p1.musicxml", SAMPLE.read_bytes(), "application/xml")),
                                    ("file", ("p2.png", b"x", "image/png"))])
    assert r.status_code == 415
