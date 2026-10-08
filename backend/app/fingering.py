"""Choosing where on the fretboard to play each note.

The rest of the pipeline only depends on `FingeringStrategy` and `FingeringResult`.
`HandPositionStrategy` is the default; `LowestFretStrategy` is the naive original,
kept for comparison.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .guitar import NoteEvent, Position, candidate_positions


@dataclass
class FingeringResult:
    # positions[i][j] is the position for events[i].pitches[j], or None if dropped.
    positions: list[list[Position | None]]
    warnings: list[str] = field(default_factory=list)


class FingeringStrategy(ABC):
    @abstractmethod
    def choose(self, events: list[NoteEvent]) -> FingeringResult:
        """Assign a position to every pitch of every event.

        Must return one list per event, aligned with `event.pitches`. Within a
        chord, no two notes may share a string; unplayable notes get None.
        """


def _position_cost(p: Position) -> tuple[int, int]:
    # Lowest fret first; tie-break on higher-pitched string (smaller string number).
    return (p.fret, p.string)


def best_chord_assignment(
    pitches: list[int], cost=_position_cost
) -> list[Position | None]:
    """Assign distinct strings to as many pitches as possible, minimizing total cost.

    Chords have at most a handful of notes, so exhaustive search is fine.
    Returns positions aligned with `pitches`; None where a note had to be dropped.
    """
    candidates = [sorted(candidate_positions(m), key=cost) for m in pitches]
    best_key: tuple | None = None
    best: list[Position | None] = []

    def search(i: int, used: set[int], chosen: list[Position | None]) -> None:
        nonlocal best_key, best
        if i == len(pitches):
            placed = [cost(p) for p in chosen if p is not None]
            # Prefer more notes placed, then lower summed cost.
            key = (-len(placed), *(sum(c) for c in zip(*placed)))
            if best_key is None or key < best_key:
                best_key, best = key, list(chosen)
            return
        for p in candidates[i]:
            if p.string not in used:
                search(i + 1, used | {p.string}, chosen + [p])
        search(i + 1, used, chosen + [None])  # drop this note

    search(0, set(), [])
    return best


class LowestFretStrategy(FingeringStrategy):
    """Naive placeholder: each note independently at its lowest fret."""

    def choose(self, events: list[NoteEvent]) -> FingeringResult:
        result = FingeringResult(positions=[])
        for ev in events:
            if len(ev.pitches) <= 1:
                cands = [sorted(candidate_positions(m), key=_position_cost) for m in ev.pitches]
                chosen = [c[0] if c else None for c in cands]
            else:
                chosen = best_chord_assignment(ev.pitches)
            for name, pos in zip(ev.names, chosen):
                if pos is None:
                    result.warnings.append(
                        f"Measure {ev.measure}: dropped {name} (no free string / out of range)"
                    )
            result.positions.append(chosen)
        return result


def _chord_options(pitches: list[int]) -> list[list[Position | None]]:
    """Every way to play all `pitches` on distinct strings; if none exists, the best
    assignment with some notes dropped (see best_chord_assignment)."""
    candidates = [candidate_positions(m) for m in pitches]
    options: list[list[Position | None]] = []

    def search(i: int, used: set[int], chosen: list[Position | None]) -> None:
        if i == len(pitches):
            options.append(list(chosen))
            return
        for p in candidates[i]:
            if p.string not in used:
                search(i + 1, used | {p.string}, chosen + [p])

    search(0, set(), [])
    return options or [best_chord_assignment(pitches)]


class HandPositionStrategy(FingeringStrategy):
    """Picks positions that keep the fretting hand compact and still.

    Every candidate fingering of an event (a note or chord) gets a cost:
      - spread: how far its fretted notes are from their average fret (compact chords),
      - stretch: a large penalty per fret beyond `max_span` (a hand covers ~4 frets),
      - height: a small preference for lower frets, to break ties near the nut.
    Moving the hand between consecutive events costs the distance between their average
    frets. Open strings need no finger, so they don't move the hand.

    The cheapest sequence over the whole piece is found with dynamic programming: for each
    event and each of its candidates, remember the cheapest way to arrive there from any
    candidate of the previous event. Then walk back from the cheapest last candidate.
    """

    def __init__(
        self,
        max_span: int = 4,
        move_weight: float = 1.0,
        spread_weight: float = 1.0,
        stretch_penalty: float = 100.0,
        height_weight: float = 0.3,
    ) -> None:
        self.max_span = max_span
        self.move_weight = move_weight
        self.spread_weight = spread_weight
        self.stretch_penalty = stretch_penalty
        self.height_weight = height_weight

    def _option_cost(self, option: list[Position | None]) -> tuple[float, float | None]:
        """(cost of playing this option on its own, hand position or None if no finger is used)."""
        frets = [p.fret for p in option if p is not None and p.fret > 0]
        if not frets:
            return 0.0, None
        center = sum(frets) / len(frets)
        spread = sum(abs(f - center) for f in frets)
        stretch = max(0, max(frets) - min(frets) - self.max_span)
        cost = (self.spread_weight * spread + self.stretch_penalty * stretch
                + self.height_weight * center)
        return cost, center

    def choose(self, events: list[NoteEvent]) -> FingeringResult:
        result = FingeringResult(positions=[[] for _ in events])
        playable = [i for i, ev in enumerate(events) if ev.pitches]  # rests don't move the hand

        # best[k][j] = (total cost, hand position, index of previous option) for option j
        # of the k-th playable event.
        options: list[list[list[Position | None]]] = []
        best: list[list[tuple[float, float | None, int]]] = []
        for k, i in enumerate(playable):
            opts = _chord_options(events[i].pitches)
            options.append(opts)
            row = []
            for opt in opts:
                own, center = self._option_cost(opt)
                if k == 0:
                    row.append((own, center, -1))
                    continue
                choice = None
                for prev_j, (prev_cost, prev_center, _) in enumerate(best[k - 1]):
                    move = (self.move_weight * abs(center - prev_center)
                            if center is not None and prev_center is not None else 0.0)
                    total = prev_cost + own + move
                    if choice is None or total < choice[0]:
                        # An option without fretted notes leaves the hand where it was.
                        choice = (total, center if center is not None else prev_center, prev_j)
                row.append(choice)
            best.append(row)

        if best:
            j = min(range(len(best[-1])), key=lambda j: best[-1][j][0])
            for k in range(len(playable) - 1, -1, -1):
                result.positions[playable[k]] = options[k][j]
                j = best[k][j][2]

        for ev, chosen in zip(events, result.positions):
            for name, pos in zip(ev.names, chosen):
                if pos is None:
                    result.warnings.append(
                        f"Measure {ev.measure}: dropped {name} (no free string / out of range)"
                    )
        return result
