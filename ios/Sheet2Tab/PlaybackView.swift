import AVFoundation
import SwiftUI

/// One note to play and draw, timed in beats (quarter notes) from the start of the piece.
struct PlaybackNote {
    let string: Int?  // guitar: 1 = high e … 6 = low E
    let fret: Int?
    let hand: String?  // piano: "right" | "left"
    let name: String   // e.g. "Bb4"
    let midi: Int
    let start: Double
    let duration: Double
}

extension ConvertResponse {
    static let defaultTempo = 90.0

    var playbackNotes: [PlaybackNote] {
        // Tabs saved before the server sent `start`: lay the measures end to end,
        // each as long as its last note reaches.
        var measureStart: [Int: Double] = [:]
        if notes.contains(where: { $0.start == nil }) {
            var lengths: [Int: Double] = [:]
            for n in notes { lengths[n.measure] = max(lengths[n.measure] ?? 0, n.offset + n.duration) }
            var t = 0.0
            for m in lengths.keys.sorted() {
                measureStart[m] = t
                t += lengths[m]!
            }
        }
        return notes.map { n in
            PlaybackNote(string: n.string, fret: n.fret, hand: n.hand, name: n.pitch, midi: n.midi,
                         start: n.start ?? (measureStart[n.measure] ?? 0) + n.offset,
                         duration: n.duration)
        }
        .sorted { $0.start < $1.start }
    }
}

/// Plays the notes with a recorded guitar or piano (GeneralUser GS SoundFont, bundled with
/// the app; see GeneralUser-GS-LICENSE.txt). The view reads `currentBeat` every frame; it
/// comes from the sequencer that plays the notes, so picture and sound share one clock and
/// can't drift apart.
@Observable
final class TabPlayer {
    /// Beats of silence before the first note, so it scrolls in from the right.
    static let leadIn = 2.0
    /// General MIDI program 26 (0-based): jazz guitar. The steel and nylon acoustic presets
    /// would sound closer to an acoustic guitar, but Apple's sampler ignores their sample loops,
    /// so held notes cut off after ~1 s. Jazz guitar rings for several seconds.
    private static let guitarProgram: UInt8 = 26
    /// General MIDI program 4: tine electric piano (Rhodes-like). It rings evenly for several
    /// seconds in Apple's sampler; the FM electric piano (5) dies within a second there.
    private static let pianoProgram: UInt8 = 4

    let notes: [PlaybackNote]
    let isPiano: Bool
    let tempo: Double
    let endBeat: Double
    private(set) var isPlaying = false

    @ObservationIgnored private let engine = AVAudioEngine()
    @ObservationIgnored private let sampler = AVAudioUnitSampler()
    @ObservationIgnored private var sequencer: AVAudioSequencer?

    init(result: ConvertResponse) {
        notes = result.playbackNotes
        isPiano = result.isPiano
        tempo = result.tempo_bpm ?? ConvertResponse.defaultTempo
        endBeat = (notes.map { $0.start + $0.duration }.max() ?? 0) + Self.leadIn
    }

    /// Position in the piece, in beats; negative during the lead-in.
    var currentBeat: Double {
        (sequencer?.currentPositionInBeats ?? 0) - Self.leadIn
    }

    func play() {
        do {
            if sequencer == nil { try setUp() }
            guard let sequencer else { return }
            if sequencer.currentPositionInBeats >= endBeat { sequencer.currentPositionInBeats = 0 }
            if !engine.isRunning { try engine.start() }
            try sequencer.start()
            isPlaying = true
        } catch {
            print("Playback failed: \(error)")
        }
    }

    func pause() {
        sequencer?.stop()
        isPlaying = false
    }

    func stop() {
        pause()
        engine.stop()
    }

    private func setUp() throws {
        // .playback: audible even when the ring/silent switch is set to silent.
        try AVAudioSession.sharedInstance().setCategory(.playback)
        try AVAudioSession.sharedInstance().setActive(true)

        engine.attach(sampler)
        engine.connect(sampler, to: engine.mainMixerNode, format: nil)
        if let soundFont = Bundle.main.url(forResource: "GeneralUser-GS", withExtension: "sf2") {
            // Only the one preset is loaded into memory, not the whole bank.
            try sampler.loadSoundBankInstrument(
                at: soundFont, program: isPiano ? Self.pianoProgram : Self.guitarProgram,
                bankMSB: UInt8(kAUSampler_DefaultMelodicBankMSB), bankLSB: UInt8(kAUSampler_DefaultBankLSB))
        }
        try engine.start()

        let sequencer = AVAudioSequencer(audioEngine: engine)
        sequencer.tempoTrack.addEvent(AVExtendedTempoEvent(tempo: tempo), at: 0)
        let track = sequencer.createAndAppendTrack()
        track.destinationAudioUnit = sampler
        for note in notes {
            // Slightly shorter than written, so repeated notes are heard as separate notes.
            let event = AVMIDINoteEvent(channel: 0, key: UInt32(note.midi), velocity: 100,
                                        duration: AVMusicTimeStamp(note.duration * 0.95))
            track.addEvent(event, at: AVMusicTimeStamp(note.start + Self.leadIn))
        }
        sequencer.prepareToPlay()
        self.sequencer = sequencer
    }
}

/// Guitar: Guitar-Hero-style view, one lane per string, notes scroll from right to left and
/// are played when they reach the line on the left. Piano: notes fall onto a keyboard
/// (PianoRoll). Either way, a note's length on screen is its duration.
struct PlaybackView: View {
    @State private var player: TabPlayer
    private let pianoKeys: ClosedRange<Int>

    init(result: ConvertResponse) {
        let player = TabPlayer(result: result)
        _player = State(initialValue: player)
        pianoKeys = PianoRoll.keyRange(for: player.notes)
    }

    var body: some View {
        TimelineView(.animation(paused: !player.isPlaying)) { _ in
            let beat = player.currentBeat
            Canvas { context, size in
                if player.isPiano {
                    PianoRoll.draw(context: context, size: size, beat: beat,
                                   notes: player.notes, keys: pianoKeys)
                } else {
                    drawHighway(context: context, size: size, beat: beat)
                }
            }
            .onChange(of: beat >= player.endBeat - TabPlayer.leadIn) { _, finished in
                if finished { player.pause() }
            }
        }
        .background(Color.black)
        .contentShape(Rectangle())
        .onTapGesture { player.isPlaying ? player.pause() : player.play() }
        .overlay(alignment: .bottom) {
            if !player.isPlaying {
                Label("Tap to play", systemImage: "play.fill")
                    .font(.headline)
                    .foregroundStyle(.white)
                    .padding(.bottom, 24)
                    .allowsHitTesting(false)
            }
        }
        .navigationTitle("Playback")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { player.play() }
        .onDisappear { player.stop() }
    }

    // MARK: Drawing

    private static let pointsPerBeat: CGFloat = 90
    private static let labelWidth: CGFloat = 28
    private static let stringNames = ["e", "B", "G", "D", "A", "E"]
    private static let stringColors: [Color] = [.red, .orange, .yellow, .green, .cyan, .purple]

    private func drawHighway(context: GraphicsContext, size: CGSize, beat: Double) {
        let laneHeight = size.height / 6
        let nowX = Self.labelWidth + (size.width - Self.labelWidth) * 0.15
        func laneY(_ string: Int) -> CGFloat { laneHeight * (CGFloat(string) - 0.5) }

        // Strings and their names.
        for string in 1...6 {
            let y = laneY(string)
            var line = Path()
            line.move(to: CGPoint(x: Self.labelWidth, y: y))
            line.addLine(to: CGPoint(x: size.width, y: y))
            context.stroke(line, with: .color(.white.opacity(0.25)), lineWidth: CGFloat(string) * 0.5 + 0.5)
            context.draw(Text(Self.stringNames[string - 1]).font(.system(size: 15, weight: .semibold, design: .monospaced))
                            .foregroundStyle(.white.opacity(0.7)),
                         at: CGPoint(x: Self.labelWidth / 2, y: y))
        }

        // Only notes on screen are drawn.
        let firstVisible = beat - Double(nowX / Self.pointsPerBeat)
        let lastVisible = beat + Double((size.width - nowX) / Self.pointsPerBeat)
        let barHeight = min(laneHeight * 0.7, 40)
        for note in player.notes where note.start + note.duration > firstVisible && note.start < lastVisible {
            guard let string = note.string, let fret = note.fret else { continue }
            let x = nowX + CGFloat(note.start - beat) * Self.pointsPerBeat
            let width = max(CGFloat(note.duration) * Self.pointsPerBeat - 3, barHeight)
            let rect = CGRect(x: x, y: laneY(string) - barHeight / 2, width: width, height: barHeight)
            let sounding = note.start <= beat && beat < note.start + note.duration
            let color = Self.stringColors[string - 1]

            let bar = Path(roundedRect: rect, cornerRadius: barHeight / 2)
            context.fill(bar, with: .color(color.opacity(sounding ? 1 : 0.75)))
            if sounding {
                context.stroke(bar, with: .color(.white), lineWidth: 3)
            }
            context.draw(Text("\(fret)").font(.system(size: barHeight * 0.55, weight: .bold, design: .rounded))
                            .foregroundStyle(.black),
                         at: CGPoint(x: rect.minX + barHeight / 2, y: rect.midY))
        }

        // The "now" line: play a note when its left edge reaches it.
        var now = Path()
        now.move(to: CGPoint(x: nowX, y: 0))
        now.addLine(to: CGPoint(x: nowX, y: size.height))
        context.stroke(now, with: .color(.white), lineWidth: 2)
    }
}
