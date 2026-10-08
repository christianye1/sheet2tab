from pathlib import Path

from app.guitar import NoteEvent, Position
from app.pipeline import musicxml_to_tab
from app.tab_renderer import render_tab

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "ode_to_joy.musicxml"


def ev(measure, *pitches, duration=1.0):
    return NoteEvent(measure=measure, offset=0.0, duration=duration, pitches=list(pitches))


def test_single_measure_layout():
    events = [ev(1, 64), ev(1, 60)]
    positions = [[Position(1, 0)], [Position(2, 1)]]
    tab = render_tab(events, positions, spacing_by_duration=False)
    assert tab.splitlines() == [
        "e|-0---|",
        "B|---1-|",
        "G|-----|",
        "D|-----|",
        "A|-----|",
        "E|-----|",
    ]


def test_two_digit_frets_keep_columns_aligned():
    events = [ev(1, 76, 45)]
    positions = [[Position(1, 12), Position(5, 0)]]
    lines = render_tab(events, positions, spacing_by_duration=False).splitlines()
    assert lines[0] == "e|-12-|"
    assert lines[4] == "A|-0--|"
    assert len({len(l) for l in lines}) == 1


def test_measures_separated_by_bars():
    events = [ev(1, 64), ev(2, 64)]
    positions = [[Position(1, 0)], [Position(1, 3)]]
    first = render_tab(events, positions, spacing_by_duration=False).splitlines()[0]
    assert first == "e|-0-|-3-|"


def test_duration_spacing():
    events = [ev(1, 64, duration=2.0), ev(1, 64, duration=0.5)]
    positions = [[Position(1, 0)], [Position(1, 0)]]
    assert render_tab(events, positions).splitlines()[0] == "e|-0----0-|"


def test_rest_renders_as_dashes():
    events = [ev(1), ev(1, 64)]
    positions = [[], [Position(1, 0)]]
    lines = render_tab(events, positions, spacing_by_duration=False).splitlines()
    assert lines[0] == "e|---0-|"


def test_dropped_note_not_rendered():
    events = [ev(1, 40, 41)]
    positions = [[Position(6, 0), None]]
    lines = render_tab(events, positions, spacing_by_duration=False).splitlines()
    assert lines[5] == "E|-0-|"


def test_wraps_at_width():
    events = [ev(m, 64) for m in range(1, 21)]
    positions = [[Position(1, 0)]] * 20
    tab = render_tab(events, positions, width=30)
    systems = tab.strip().split("\n\n")
    assert len(systems) > 1
    for system in systems:
        lines = system.splitlines()
        assert len(lines) == 6
        assert all(len(l) <= 30 for l in lines)
        assert lines[0].startswith("e|") and lines[5].startswith("E|")


def test_empty_input():
    assert render_tab([], []) == ""


def test_sample_file_end_to_end():
    result = musicxml_to_tab(SAMPLE)
    assert result["notes"][0] == {
        "pitch": "E4", "midi": 64, "duration": 1.0, "measure": 1,
        "offset": 0.0, "start": 0.0, "string": 1, "fret": 0, "hand": None,
    }
    assert len(result["notes"]) == 38
    assert result["tab_text"].startswith("e|-0--0--1--3--|")
    assert result["warnings"] == []
