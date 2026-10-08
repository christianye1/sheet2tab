"""Fixes note timing in oemer's MusicXML before it is parsed.

oemer recognizes the notes of each staff in the right order, but positions them with
unreliable <backup> elements and filler rests without a <type> (durations like 1, 12 or 96
divisions). Taken literally, notes land at the wrong beat and measures grow to 7 beats.

Here each measure is rebuilt: per staff, the notes follow each other in the order oemer
wrote them (chord notes share their onset), filler rests are dropped, and one <backup>
returns to the start of the measure before the next staff. Rests that oemer recognized
(with a <type>) are kept. Only meant for OMR output; hand-written MusicXML with several
voices per staff would be flattened by this.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET


def _duration(note: ET.Element) -> int:
    return int(note.findtext("duration") or 0)


def _is_filler_rest(note: ET.Element) -> bool:
    return note.find("rest") is not None and not (note.findtext("type") or "").strip()


def retime_measure(measure: ET.Element) -> None:
    """Rebuilds one <measure> in place (see module docstring)."""
    children = list(measure)
    staves: dict[str, list[ET.Element]] = {}
    before: list[ET.Element] = []  # attributes, directions, … before the first note
    after: list[ET.Element] = []   # barlines and anything after the last note
    seen_note = False
    for el in children:
        if el.tag == "note":
            seen_note = True
            if _is_filler_rest(el):
                continue
            staves.setdefault(el.findtext("staff") or "1", []).append(el)
        elif el.tag in ("backup", "forward"):
            continue
        elif el.tag == "barline" or seen_note and el.tag != "direction":
            after.append(el)
        else:
            before.append(el)

    for el in children:
        measure.remove(el)
    for el in before:
        measure.append(el)
    previous: list[ET.Element] = []
    for i, staff in enumerate(sorted(staves, key=int)):
        notes = staves[staff]
        if i > 0:
            # Back to the start of the measure for the next staff.
            elapsed = sum(_duration(n) for n in previous if n.find("chord") is None)
            if elapsed:
                backup = ET.SubElement(measure, "backup")
                ET.SubElement(backup, "duration").text = str(elapsed)
        for n in notes:
            voice = n.find("voice")
            if voice is None:
                voice = ET.SubElement(n, "voice")
            voice.text = staff  # one voice per staff
            measure.append(n)
        previous = notes
    for el in after:
        measure.append(el)


def retime_oemer_musicxml(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    for measure in root.iter("measure"):
        retime_measure(measure)
    return ET.tostring(root, encoding="unicode")
