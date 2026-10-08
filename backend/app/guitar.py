"""Guitar constants and data types shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field

# Standard tuning. String numbers follow guitar convention: 1 = high e, 6 = low E.
STANDARD_TUNING: dict[int, int] = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}
STRING_LABELS: dict[int, str] = {1: "e", 2: "B", 3: "G", 4: "D", 5: "A", 6: "E"}
MAX_FRET = 20
LOWEST_MIDI = min(STANDARD_TUNING.values())               # 40 (E2)
HIGHEST_MIDI = max(STANDARD_TUNING.values()) + MAX_FRET   # 84 (C6)


@dataclass(frozen=True)
class Position:
    string: int  # 1 (high e) .. 6 (low E)
    fret: int


@dataclass
class NoteEvent:
    """Something that happens at one onset: a single note, a chord, or a rest.

    `pitches` are *sounding* MIDI numbers, already transposed/shifted into guitar range.
    """
    measure: int
    offset: float               # quarter lengths from start of measure
    duration: float             # quarter lengths
    pitches: list[int] = field(default_factory=list)
    names: list[str] = field(default_factory=list)  # pitch names matching `pitches`
    start: float = 0.0          # quarter lengths from start of the piece (for playback)

    @property
    def is_rest(self) -> bool:
        return not self.pitches


def candidate_positions(midi: int, tuning: dict[int, int] = STANDARD_TUNING) -> list[Position]:
    """All (string, fret) positions that produce `midi`."""
    return [
        Position(string, midi - open_midi)
        for string, open_midi in tuning.items()
        if 0 <= midi - open_midi <= MAX_FRET
    ]
