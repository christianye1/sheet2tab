"""MusicXML -> tab result. Shared by the CLI test script and the API."""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Callable

from .omr_cleanup import retime_oemer_musicxml
from .fingering import FingeringStrategy, HandPositionStrategy
from music21 import stream

from .guitar import NoteEvent
from .parser import (DEFAULT_TEMPO_BPM, PianoNote, load_score, parse_piano_score, parse_score,
                     score_tempo)
from .tab_renderer import render_piano, render_tab

INSTRUMENTS = ("guitar", "piano")


def musicxml_to_tab(
    path: str | Path,
    strategy: FingeringStrategy | None = None,
    width: int = 80,
    instrument: str = "guitar",
) -> dict:
    return musicxml_pages_to_tab([path], strategy, width, instrument)


def musicxml_pages_to_tab(
    paths: list[str | Path],
    strategy: FingeringStrategy | None = None,
    width: int = 80,
    instrument: str = "guitar",
    page_numbers: list[int] | None = None,
) -> dict:
    """One result for several pages played one after another: each page starts where the
    previous one ends, and measure numbers continue across pages."""
    page_numbers = page_numbers or list(range(1, len(paths) + 1))
    many = len(paths) > 1
    warnings: list[str] = []
    events: list[NoteEvent] = []
    piano_notes: list[PianoNote] = []
    tempo_bpm = None
    beat_offset, measure_offset = 0.0, 0

    for number, path in zip(page_numbers, paths):
        prefix = f"Page {number}: " if many else ""
        score, error = load_score(path)
        if score is None:
            warnings.append(prefix + error)
            continue
        if tempo_bpm is None:
            tempo_bpm = score_tempo(score)
        if instrument == "piano":
            page_notes, page_warnings = parse_piano_score(score)
            for n in page_notes:
                n.start += beat_offset
                n.measure += measure_offset
            piano_notes += page_notes
        else:
            page_events, page_warnings = parse_score(score)
            for ev in page_events:
                ev.start += beat_offset
                ev.measure += measure_offset
            events += page_events
        warnings += [prefix + w for w in page_warnings]
        beat_offset += float(score.highestTime)
        measure_offset += max((m.number for m in score.recurse().getElementsByClass(stream.Measure)),
                              default=0)

    tempo_bpm = tempo_bpm or DEFAULT_TEMPO_BPM
    if instrument == "piano":
        return _piano_result(piano_notes, warnings, tempo_bpm, width)
    return _guitar_result(events, warnings, tempo_bpm, width, strategy or HandPositionStrategy())


def _guitar_result(events: list[NoteEvent], warnings: list[str], tempo_bpm: float, width: int,
                   strategy: FingeringStrategy) -> dict:
    result = strategy.choose(events)
    warnings += result.warnings

    notes = []
    for ev, positions in zip(events, result.positions):
        for midi, name, pos in zip(ev.pitches, ev.names, positions):
            if pos is None:
                continue
            notes.append({
                "pitch": name,
                "midi": midi,
                "duration": ev.duration,
                "measure": ev.measure,
                "offset": ev.offset,
                "start": ev.start,
                "string": pos.string,
                "fret": pos.fret,
                "hand": None,
            })

    if not notes:
        warnings.append("No playable notes found")

    return {
        "instrument": "guitar",
        "tab_text": render_tab(events, result.positions, width=width),
        "notes": notes,
        "tempo_bpm": tempo_bpm,
        "warnings": warnings,
    }


def _piano_result(notes: list[PianoNote], warnings: list[str], tempo_bpm: float, width: int) -> dict:
    """Both hands as note names; every pitch has exactly one key, so no fingering step."""
    if not notes:
        warnings.append("No playable notes found")
    return {
        "instrument": "piano",
        "tab_text": render_piano(notes, width=width),
        "notes": [
            {
                "pitch": n.name,
                "midi": n.midi,
                "duration": n.duration,
                "measure": n.measure,
                "offset": n.offset,
                "start": n.start,
                "string": None,
                "fret": None,
                "hand": n.hand,
            }
            for n in notes
        ],
        "tempo_bpm": tempo_bpm,
        "warnings": warnings,
    }


BUILD_TAB_STAGE = "Building tab"


def image_to_tab(
    image_bytes: bytes,
    strategy: FingeringStrategy | None = None,
    on_progress: Callable[[str, float], None] | None = None,
    cancel: threading.Event | None = None,
    instrument: str = "guitar",
) -> dict:
    """Photo -> OMR -> MusicXML -> tab. Raises omr.OMRError if recognition fails."""
    return images_to_tab([image_bytes], strategy, on_progress, cancel, instrument)


def images_to_tab(
    pages: list[bytes],
    strategy: FingeringStrategy | None = None,
    on_progress: Callable[[str, float], None] | None = None,
    cancel: threading.Event | None = None,
    instrument: str = "guitar",
    on_page: Callable[[int, int], None] | None = None,
) -> dict:
    """Photos of consecutive pages -> one tab. Each page goes through OMR on its own (and is
    cached on its own); a page that fails is skipped with a warning, and omr.OMRError is
    raised only if no page could be recognized.

    `on_page(index, count)` is called before each page, `on_progress(stage, fraction)` as
    each stage of it starts and advances. Setting `cancel` stops OMR and raises
    omr.OMRCancelled.
    """
    from .omr import OMRCancelled, OMRError, image_to_musicxml  # heavy imports

    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sheet2tab-") as tmp:
        xml_paths: list[Path] = []
        page_numbers: list[int] = []
        first_error: OMRError | None = None
        for i, data in enumerate(pages):
            if cancel is not None and cancel.is_set():
                raise OMRCancelled()
            if on_page:
                on_page(i, len(pages))
            page_dir = Path(tmp) / f"page{i + 1}"
            page_dir.mkdir()
            try:
                xml_path = image_to_musicxml(data, page_dir, on_progress, cancel)
            except OMRError as e:
                if len(pages) == 1:
                    raise
                first_error = first_error or e
                warnings.append(f"Page {i + 1} was skipped: {str(e).splitlines()[0]}")
                continue
            # oemer's note positions within a measure are unreliable; its note order is not.
            retimed = page_dir / "retimed.musicxml"
            retimed.write_text(retime_oemer_musicxml(xml_path.read_text()))
            xml_paths.append(retimed)
            page_numbers.append(i + 1)
        if not xml_paths:
            raise first_error
        if on_progress:
            on_progress(BUILD_TAB_STAGE, 0.0)
        result = musicxml_pages_to_tab(xml_paths, strategy, instrument=instrument,
                                       page_numbers=page_numbers)
    result["warnings"] = (["Recognized by OMR; expect some wrong or missing notes"]
                          + warnings + result["warnings"])
    return result
