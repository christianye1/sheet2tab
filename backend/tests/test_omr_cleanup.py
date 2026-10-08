from app.omr_cleanup import retime_oemer_musicxml

# Shaped like oemer's output: two staves in one part, notes positioned with stray
# <backup>s and untyped filler rests.
OEMER_MEASURE = """<score-partwise><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list><part id="P1"><measure number="1">
<attributes><divisions>2</divisions><staves>2</staves></attributes>
<note><pitch><step>D</step><octave>3</octave></pitch><duration>6</duration><type>half</type><dot/><staff>2</staff></note>
<backup><duration>6</duration></backup>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><type>quarter</type><staff>1</staff></note>
<note><rest/><duration>3</duration><staff>1</staff></note>
<backup><duration>5</duration></backup>
<note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><type>quarter</type><staff>1</staff></note>
<note><chord/><pitch><step>G</step><octave>4</octave></pitch><duration>2</duration><type>quarter</type><staff>1</staff></note>
<note><rest/><duration>2</duration><type>quarter</type><staff>1</staff></note>
<note><pitch><step>E</step><octave>3</octave></pitch><duration>2</duration><type>quarter</type><staff>2</staff></note>
</measure></part></score-partwise>"""


def test_notes_follow_each_other_per_staff():
    from music21 import converter, note, stream

    score = converter.parse(retime_oemer_musicxml(OEMER_MEASURE), format="musicxml")
    upper, lower = score.parts
    m = upper.getElementsByClass(stream.Measure).first()
    got = [(e.offset, "rest" if isinstance(e, note.Rest) else "+".join(p.nameWithOctave for p in e.pitches))
           for e in m.recurse().notesAndRests]
    # Filler rest dropped; the typed quarter rest kept; E4+G4 is one chord.
    assert got == [(0.0, "C4"), (1.0, "E4+G4"), (2.0, "rest")]
    low = lower.getElementsByClass(stream.Measure).first()
    assert [(n.offset, n.nameWithOctave) for n in low.recurse().notes] == [(0.0, "D3"), (3.0, "E3")]
