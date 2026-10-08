from music21 import chord, clef, note, stream

from app.fingering import LowestFretStrategy, best_chord_assignment
from app.guitar import NoteEvent, Position, candidate_positions
from app.parser import parse_score


def ev(*pitches, measure=1, duration=1.0):
    return NoteEvent(measure=measure, offset=0.0, duration=duration,
                     pitches=list(pitches), names=[str(p) for p in pitches])


def choose_one(midi):
    return LowestFretStrategy().choose([ev(midi)]).positions[0][0]


def score_of(*elements, clef_obj=None):
    m = stream.Measure(number=1)
    if clef_obj:
        m.append(clef_obj)
    m.append(list(elements))
    p = stream.Part([m])
    return stream.Score([p])


# --- known pitches -> string/fret -------------------------------------------

def test_open_strings():
    for midi, string in [(40, 6), (45, 5), (50, 4), (55, 3), (59, 2), (64, 1)]:
        assert choose_one(midi) == Position(string, 0)


def test_lowest_fret_wins():
    assert choose_one(60) == Position(2, 1)   # C4: B string fret 1, not G fret 5
    assert choose_one(43) == Position(6, 3)   # G2: only on low E
    assert choose_one(84) == Position(1, 20)  # C6: top of range


def test_tie_break_prefers_higher_string():
    # A single pitch can't tie on fret in standard tuning, so check via a chord
    # and via the cost ordering directly.
    assert best_chord_assignment([64, 59]) == [Position(1, 0), Position(2, 0)]
    # The cost ordering puts the higher string first on equal fret.
    from app.fingering import _position_cost
    assert sorted([Position(3, 2), Position(2, 2)], key=_position_cost)[0] == Position(2, 2)


def test_candidate_positions_cover_all_strings():
    # E4 is playable on 5 strings (low E would need fret 24).
    assert {p.string for p in candidate_positions(64)} == {1, 2, 3, 4, 5}


# --- out-of-range handling --------------------------------------------------

def test_out_of_range_notes_shifted_with_warning():
    events, warnings = parse_score(score_of(note.Note("C2"), note.Note("C7")))
    assert [e.pitches for e in events] == [[48], [84]]  # C3, C6
    assert any("Shifted 2 note(s)" in w for w in warnings)


def test_in_range_notes_untouched():
    events, warnings = parse_score(score_of(note.Note("A4")))
    assert events[0].pitches == [69]
    assert not any("Shifted" in w for w in warnings)


def test_guitar_clef_transposes_down_an_octave():
    events, warnings = parse_score(
        score_of(note.Note("E4"), clef_obj=clef.Treble8vbClef()))
    assert events[0].pitches == [52]  # written E4 sounds E3
    assert events[0].names == ["E3"]
    assert any("guitar notation" in w for w in warnings)


def test_rest_produces_empty_event():
    events, _ = parse_score(score_of(note.Rest(), note.Note("E4")))
    assert events[0].is_rest and events[1].pitches == [64]


# --- chords ------------------------------------------------------------------

def test_chord_uses_distinct_strings():
    # E major open chord: E2 B2 E3 G#3 B3 E4
    positions = best_chord_assignment([40, 47, 52, 56, 59, 64])
    assert positions == [Position(6, 0), Position(5, 2), Position(4, 2),
                         Position(3, 1), Position(2, 0), Position(1, 0)]


def test_chord_conflict_resolved_by_moving_note():
    # B3 and C4 both prefer the B string (fret 0 / 1); one must move to G.
    positions = best_chord_assignment([59, 60])
    assert None not in positions
    assert len({p.string for p in positions}) == 2
    assert sum(p.fret for p in positions) == 5  # B0+G5 or G4+B1


def test_chord_conflict_drops_note_and_warns():
    # Three notes that can only be played on the low E string.
    result = LowestFretStrategy().choose([ev(40, 41, 42)])
    placed = [p for p in result.positions[0] if p is not None]
    assert len(placed) == 1
    assert len(result.warnings) == 2
    assert all("dropped" in w for w in result.warnings)


def test_seven_note_chord_drops_one():
    result = LowestFretStrategy().choose([ev(40, 45, 50, 55, 59, 64, 69)])
    assert sum(p is None for p in result.positions[0]) == 1


def test_parser_groups_simultaneous_notes_into_chord():
    events, _ = parse_score(score_of(chord.Chord(["C4", "E4", "G4"])))
    assert sorted(events[0].pitches) == [60, 64, 67]


def test_start_is_absolute_across_measures():
    m1, m2 = stream.Measure(number=1), stream.Measure(number=2)
    m1.append([note.Note("E4", quarterLength=2), note.Note("F4", quarterLength=2)])
    m2.append([note.Rest(quarterLength=1), note.Note("G4", quarterLength=3)])
    part = stream.Part([m1, m2])
    events, _ = parse_score(stream.Score([part]))
    assert [(e.measure, e.offset, e.start) for e in events] == [
        (1, 0.0, 0.0), (1, 2.0, 2.0), (2, 0.0, 4.0), (2, 1.0, 5.0)]


def hand_moves(positions):
    """Total frets the hand travels between consecutive events (open strings don't count)."""
    centers = []
    for chosen in positions:
        frets = [p.fret for p in chosen if p is not None and p.fret > 0]
        if frets:
            centers.append(sum(frets) / len(frets))
    return sum(abs(a - b) for a, b in zip(centers, centers[1:]))


def test_hand_position_stays_near_previous_chord():
    from app.fingering import HandPositionStrategy

    # C5+G4+E4 can only be played compactly around fret 8. The next D4 is lowest on the
    # B string at fret 3, but G string fret 7 keeps the hand in place.
    events = [ev(72, 67, 64), ev(62)]
    lowest = LowestFretStrategy().choose(events).positions
    hand = HandPositionStrategy().choose(events).positions
    assert lowest[1] == [Position(2, 3)]
    assert hand[1] == [Position(3, 7)]


def test_hand_position_keeps_chords_within_four_frets():
    from app.fingering import HandPositionStrategy

    chosen = HandPositionStrategy().choose([ev(72, 67, 64)]).positions[0]
    frets = [p.fret for p in chosen if p.fret > 0]
    assert max(frets) - min(frets) <= 4
    assert len({p.string for p in chosen}) == 3


def test_hand_position_prefers_open_strings_and_low_frets():
    from app.fingering import HandPositionStrategy

    # E4 F4 G4: open e, then frets 1 and 3 on the e string.
    chosen = HandPositionStrategy().choose([ev(64), ev(65), ev(67)]).positions
    assert chosen == [[Position(1, 0)], [Position(1, 1)], [Position(1, 3)]]


def test_hand_position_handles_rests_and_unplayable_notes():
    from app.fingering import HandPositionStrategy

    result = HandPositionStrategy().choose([ev(64), ev(), ev(30)])
    assert result.positions[1] == []
    assert result.positions[2] == [None]
    assert any("dropped" in w for w in result.warnings)
