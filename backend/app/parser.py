"""MusicXML -> list of NoteEvents (sounding pitches in guitar range), via music21."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from music21 import chord, clef, converter, instrument, note, stream, tempo

from .guitar import HIGHEST_MIDI, LOWEST_MIDI, NoteEvent

# Used when the score has no metronome mark. oemer never writes one (it doesn't read text).
DEFAULT_TEMPO_BPM = 90.0


def is_guitar_score(score: stream.Score, part: stream.Part) -> bool:
    """Guitar music is notated an octave above sounding pitch."""
    for c in part.recurse().getElementsByClass(clef.Clef):
        if isinstance(c, clef.Treble8vbClef) or (
            isinstance(c, clef.TrebleClef) and c.octaveChange == -1
        ):
            return True
    inst = part.getInstrument(returnDefault=False)
    if inst is not None and (
        isinstance(inst, instrument.Guitar)
        or "guitar" in (inst.instrumentName or "").lower()
        or "guitar" in (inst.partName or "").lower()
    ):
        return True
    title = (score.metadata.title or "") if score.metadata else ""
    return "guitar" in title.lower() or "guitar" in (part.partName or "").lower()


def _onsets(part: stream.Part):
    """Yields (measure, empty NoteEvent, elements) for every onset in `part`.

    Everything starting at the same offset (across voices) is one onset.
    """
    for m in part.getElementsByClass(stream.Measure):
        measure_start = float(m.getOffsetInHierarchy(part))
        groups: dict[float, list[note.GeneralNote]] = defaultdict(list)
        for el in m.recurse().notesAndRests:
            if el.duration.isGrace:
                continue
            groups[float(el.getOffsetInHierarchy(m))].append(el)
        for offset in sorted(groups):
            els = groups[offset]
            ev = NoteEvent(
                measure=m.number,
                offset=offset,
                duration=float(max(e.quarterLength for e in els)),
                start=measure_start + offset,
            )
            yield m, ev, els


def shift_into_range(midi: int) -> int:
    while midi < LOWEST_MIDI:
        midi += 12
    while midi > HIGHEST_MIDI:
        midi -= 12
    return midi


def parse_score(score: stream.Score) -> tuple[list[NoteEvent], list[str]]:
    warnings: list[str] = []
    parts = list(score.parts)
    if not parts:
        return [], ["No parts found in score"]
    if len(parts) > 1:
        warnings.append(f"Score has {len(parts)} parts/staves; only the first is converted")
    part = parts[0]

    transpose = -12 if is_guitar_score(score, part) else 0
    if transpose:
        warnings.append("Detected guitar notation; transposed down one octave to sounding pitch")

    events: list[NoteEvent] = []
    shifted_measures: set[int] = set()
    shifted_count = 0

    for m, ev, els in _onsets(part):
        for el in els:
            if isinstance(el, note.Rest):
                continue
            notes = el.notes if isinstance(el, chord.Chord) else [el]
            for n in notes:
                # A tie continuation isn't re-plucked.
                if n.tie is not None and n.tie.type in ("stop", "continue"):
                    continue
                written = n.pitch.midi + transpose
                sounding = shift_into_range(written)
                if sounding != written:
                    shifted_count += 1
                    shifted_measures.add(m.number)
                if sounding not in ev.pitches:
                    ev.pitches.append(sounding)
                    ev.names.append(n.pitch.transpose(sounding - n.pitch.midi).nameWithOctave)
        events.append(ev)

    if shifted_count:
        ms = ", ".join(map(str, sorted(shifted_measures)))
        warnings.append(
            f"Shifted {shifted_count} note(s) by octaves into guitar range (measures {ms})"
        )
    return events, warnings


def score_tempo(score: stream.Score) -> float:
    """Quarter notes per minute from the first metronome mark, else DEFAULT_TEMPO_BPM."""
    for mark in score.recurse().getElementsByClass(tempo.MetronomeMark):
        bpm = mark.getQuarterBPM()
        if bpm:
            return float(bpm)
    return DEFAULT_TEMPO_BPM


PIANO_LOWEST_MIDI = 21   # A0
PIANO_HIGHEST_MIDI = 108  # C8


@dataclass
class PianoNote:
    hand: str            # "right" | "left"
    midi: int
    name: str
    measure: int
    offset: float        # quarter lengths from start of measure
    start: float         # quarter lengths from start of the piece
    duration: float      # quarter lengths, including tied continuations


def parse_piano_score(score: stream.Score) -> tuple[list[PianoNote], list[str]]:
    """Both hands of a piano score: the upper staff is the right hand, the lower the left.

    Pitches are kept as written (no guitar octave or range handling); a tied note is one
    note whose duration covers the tie.
    """
    warnings: list[str] = []
    parts = list(score.parts)
    if not parts:
        return [], ["No parts found in score"]
    if len(parts) == 1:
        hands = [("right", parts[0])]
        warnings.append("Only one staff found; it is played as the right hand")
    else:
        # Piano-vocal sheets put the vocal line above the piano: the piano is the bottom two.
        if len(parts) > 2:
            warnings.append(f"Score has {len(parts)} staves; the bottom two are used as the piano")
        hands = [("right", parts[-2]), ("left", parts[-1])]

    notes: list[PianoNote] = []
    for hand, part in hands:
        open_ties: dict[int, PianoNote] = {}  # midi -> note a tie continues
        for m, ev, els in _onsets(part):
            struck: set[int] = set()  # a key can only be struck once per onset
            for el in els:
                if isinstance(el, note.Rest):
                    continue
                for n in (el.notes if isinstance(el, chord.Chord) else [el]):
                    midi = n.pitch.midi
                    while midi < PIANO_LOWEST_MIDI:
                        midi += 12
                    while midi > PIANO_HIGHEST_MIDI:
                        midi -= 12
                    tie = n.tie.type if n.tie is not None else None
                    if tie in ("stop", "continue") and midi in open_ties:
                        open_ties[midi].duration += float(n.quarterLength)
                        if tie == "stop":
                            del open_ties[midi]
                        continue
                    if midi in struck:
                        continue
                    struck.add(midi)
                    # music21 spells flats with "-" (B-3); show the usual "Bb3".
                    name = n.pitch.transpose(midi - n.pitch.midi).nameWithOctave.replace("-", "b")
                    pn = PianoNote(hand, midi, name, m.number, ev.offset, ev.start,
                                   float(n.quarterLength))
                    notes.append(pn)
                    if tie == "start":
                        open_ties[midi] = pn
    notes.sort(key=lambda n: (n.start, n.hand != "right", -n.midi))
    return notes, warnings


def load_score(path: str | Path) -> tuple[stream.Score | None, str | None]:
    """(score, None), or (None, error message) if the file can't be parsed."""
    try:
        score = converter.parse(str(path))
    except Exception as e:  # music21 raises a variety of exception types
        return None, f"Could not parse MusicXML: {e}"
    if isinstance(score, stream.Part):
        score = stream.Score([score])
    return score, None


def parse_musicxml(path: str | Path) -> tuple[list[NoteEvent], list[str], float]:
    """Returns (events, warnings, tempo in quarter notes per minute)."""
    score, error = load_score(path)
    if score is None:
        return [], [error], DEFAULT_TEMPO_BPM
    events, warnings = parse_score(score)
    return events, warnings, score_tempo(score)


def parse_musicxml_piano(path: str | Path) -> tuple[list[PianoNote], list[str], float]:
    """Returns (notes of both hands, warnings, tempo in quarter notes per minute)."""
    score, error = load_score(path)
    if score is None:
        return [], [error], DEFAULT_TEMPO_BPM
    notes, warnings = parse_piano_score(score)
    return notes, warnings, score_tempo(score)
