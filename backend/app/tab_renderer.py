"""Render fingered events as 6-line ASCII tab (high e on top)."""
from __future__ import annotations

from itertools import groupby

from .guitar import STRING_LABELS, NoteEvent, Position
from .parser import PianoNote

STRINGS_TOP_DOWN = [1, 2, 3, 4, 5, 6]


def _gap(duration: float, spacing_by_duration: bool) -> int:
    """Dashes after a column; an eighth note gets 1, a quarter 2, a half 4, ..."""
    if not spacing_by_duration:
        return 1
    return max(1, min(8, round(duration * 2)))


def _render_measure(
    items: list[tuple[NoteEvent, list[Position | None]]], spacing_by_duration: bool
) -> list[str]:
    lines = ["-"] * 6  # leading dash after the bar line
    for ev, positions in items:
        frets = {p.string: str(p.fret) for p in positions if p is not None}
        width = max((len(f) for f in frets.values()), default=1)
        gap = "-" * _gap(ev.duration, spacing_by_duration)
        for i, s in enumerate(STRINGS_TOP_DOWN):
            lines[i] += frets.get(s, "").ljust(width, "-") + gap
    return lines


def render_tab(
    events: list[NoteEvent],
    positions: list[list[Position | None]],
    width: int = 80,
    spacing_by_duration: bool = True,
) -> str:
    if not events:
        return ""
    measures = [
        _render_measure(list(items), spacing_by_duration)
        for _, items in groupby(zip(events, positions), key=lambda x: x[0].measure)
    ]

    systems: list[list[str]] = []
    current: list[str] | None = None
    for block in measures:
        # Each line is "e|" + measures each followed by "|".
        if current is not None and len(current[0]) + len(block[0]) + 1 <= width:
            current = [c + b + "|" for c, b in zip(current, block)]
        else:
            if current is not None:
                systems.append(current)
            current = [f"{STRING_LABELS[s]}|{b}|" for s, b in zip(STRINGS_TOP_DOWN, block)]
    systems.append(current)

    return "\n\n".join("\n".join(sys) for sys in systems) + "\n"


def render_piano(notes: list[PianoNote], width: int = 80) -> str:
    """Note names per hand, one column per measure, e.g.

        R |E4 E4 F4 G4|G4 F4 E4 D4|
        L |C3         |G2         |

    Simultaneous notes are joined with "+" (lowest first). Lines wrap at measure boundaries.
    """
    hands = [("R", "right"), ("L", "left")]
    hands = [(label, hand) for label, hand in hands if any(n.hand == hand for n in notes)]
    measures = sorted({n.measure for n in notes})
    columns: list[list[str]] = []  # per measure, one cell per hand
    for m in measures:
        cells = []
        for _, hand in hands:
            in_measure = [n for n in notes if n.measure == m and n.hand == hand]
            onsets = []
            for _, group in groupby(sorted(in_measure, key=lambda n: (n.offset, n.midi)),
                                    key=lambda n: n.offset):
                onsets.append("+".join(n.name for n in group))
            cells.append(" ".join(onsets))
        cell_width = max(len(c) for c in cells)
        columns.append([c.ljust(cell_width) for c in cells])

    systems: list[list[str]] = []
    lines = [f"{label} |" for label, _ in hands]
    for cells in columns:
        if len(lines[0]) + len(cells[0]) + 1 > width and lines[0].endswith("|") and len(lines[0]) > 3:
            systems.append(lines)
            lines = [f"{label} |" for label, _ in hands]
        lines = [line + cell + "|" for line, cell in zip(lines, cells)]
    systems.append(lines)
    return "\n\n".join("\n".join(system) for system in systems)
