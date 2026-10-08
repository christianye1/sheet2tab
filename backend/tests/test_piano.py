from pathlib import Path

from fastapi.testclient import TestClient
from music21 import chord, note, stream, tie

from app.main import app
from app.parser import parse_piano_score
from app.tab_renderer import render_piano

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "ode_to_joy.musicxml"


def piano_score(right, left, extra_top=None):
    """A score whose parts each hold one measure with the given elements."""
    parts = []
    for elements in ([extra_top] if extra_top else []) + [right, left]:
        m = stream.Measure(number=1)
        m.append(elements)
        parts.append(stream.Part([m]))
    return stream.Score(parts)


def test_upper_staff_is_right_hand_lower_is_left():
    score = piano_score([note.Note("E5"), note.Note("D5")], [note.Note("C3", quarterLength=2)])
    notes, warnings = parse_piano_score(score)
    assert [(n.hand, n.name, n.start, n.duration) for n in notes] == [
        ("right", "E5", 0.0, 1.0), ("left", "C3", 0.0, 2.0), ("right", "D5", 1.0, 1.0)]
    assert warnings == []


def test_vocal_staff_above_the_piano_is_skipped():
    score = piano_score([note.Note("E5")], [note.Note("C3")], extra_top=[note.Note("G4")])
    notes, warnings = parse_piano_score(score)
    assert {(n.hand, n.name) for n in notes} == {("right", "E5"), ("left", "C3")}
    assert "bottom two" in warnings[0]


def test_tied_notes_become_one_long_note_and_flats_read_b():
    first, second = note.Note("B-4", quarterLength=2), note.Note("B-4", quarterLength=1)
    first.tie, second.tie = tie.Tie("start"), tie.Tie("stop")
    notes, _ = parse_piano_score(piano_score([first, second], [chord.Chord(["C3", "G3"])]))
    right = [n for n in notes if n.hand == "right"]
    assert [(n.name, n.duration) for n in right] == [("Bb4", 3.0)]


def test_render_piano_aligns_hands_per_measure():
    notes, _ = parse_piano_score(piano_score(
        [note.Note("E4"), note.Note("F4")], [chord.Chord(["C3", "G3"], quarterLength=2)]))
    assert render_piano(notes) == "R |E4 F4|\nL |C3+G3|"


def test_api_piano_mode():
    client = TestClient(app)
    with SAMPLE.open("rb") as f:
        r = client.post("/convert", files={"file": ("ode.musicxml", f, "application/xml")},
                        data={"instrument": "piano"})
    body = r.json()
    assert body["instrument"] == "piano"
    assert body["tab_text"].startswith("R |")
    assert all(n["hand"] in ("right", "left") and n["fret"] is None for n in body["notes"])


def test_api_rejects_unknown_instrument():
    client = TestClient(app)
    with SAMPLE.open("rb") as f:
        r = client.post("/convert", files={"file": ("ode.musicxml", f, "application/xml")},
                        data={"instrument": "drums"})
    assert r.status_code == 422
