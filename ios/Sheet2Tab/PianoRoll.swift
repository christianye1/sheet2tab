import SwiftUI

/// Synthesia-style piano view: notes fall from the top onto a keyboard and are played when
/// they reach it; a note's height is its duration. Keys light up while their note sounds.
/// Right hand blue, left hand orange.
enum PianoRoll {
    static let pointsPerBeat: CGFloat = 110
    static let rightHand = Color(red: 0.30, green: 0.62, blue: 1.0)
    static let leftHand = Color(red: 1.0, green: 0.58, blue: 0.20)

    static func isBlack(_ midi: Int) -> Bool { [1, 3, 6, 8, 10].contains(midi % 12) }

    /// Keys to show: the piece's range plus a little room, from a C to a B, at least 2 octaves.
    static func keyRange(for notes: [PlaybackNote]) -> ClosedRange<Int> {
        var low = (notes.map(\.midi).min() ?? 60) - 2
        var high = (notes.map(\.midi).max() ?? 71) + 2
        while high - low < 23 { low -= 1; high += 1 }
        low -= low % 12            // down to a C
        high += 11 - high % 12     // up to a B
        return max(low, 21)...min(high, 108)
    }

    static func draw(context: GraphicsContext, size: CGSize, beat: Double,
                     notes: [PlaybackNote], keys: ClosedRange<Int>) {
        let keyboardHeight = min(size.height * 0.16, 110)
        let keyboardTop = size.height - keyboardHeight
        let whiteKeys = keys.filter { !isBlack($0) }
        let whiteWidth = size.width / CGFloat(whiteKeys.count)
        let blackWidth = whiteWidth * 0.6

        /// Left edge and width of a key's column.
        func column(_ midi: Int) -> (x: CGFloat, width: CGFloat) {
            let whitesBelow = CGFloat(whiteKeys.filter { $0 < midi }.count)
            return isBlack(midi)
                ? (whitesBelow * whiteWidth - blackWidth / 2, blackWidth)
                : (whitesBelow * whiteWidth, whiteWidth)
        }
        func color(_ note: PlaybackNote) -> Color { note.hand == "left" ? leftHand : rightHand }

        // Faint guide line at every C, so octaves are easy to follow.
        for midi in keys where midi % 12 == 0 {
            var line = Path()
            let x = column(midi).x
            line.move(to: CGPoint(x: x, y: 0))
            line.addLine(to: CGPoint(x: x, y: keyboardTop))
            context.stroke(line, with: .color(.white.opacity(0.12)), lineWidth: 1)
        }

        // Falling notes: a note's bottom edge reaches the keyboard when it starts.
        var sounding: [Int: Color] = [:]
        for note in notes {
            let bottom = keyboardTop - CGFloat(note.start - beat) * pointsPerBeat
            let top = bottom - CGFloat(note.duration) * pointsPerBeat + 2
            guard bottom > 0, top < keyboardTop else { continue }
            let isSounding = note.start <= beat && beat < note.start + note.duration
            if isSounding { sounding[note.midi] = color(note) }

            let (x, width) = column(note.midi)
            let rect = CGRect(x: x + 1, y: max(top, 0), width: width - 2,
                              height: min(bottom, keyboardTop) - max(top, 0))
            let bar = Path(roundedRect: rect, cornerRadius: min(5, width / 3))
            context.fill(bar, with: .color(color(note).opacity(isSounding ? 1 : 0.8)))
            if isSounding {
                context.stroke(bar, with: .color(.white), lineWidth: 2)
            }
            if width >= 16, rect.height >= 18 {
                let letter = note.name.filter { !$0.isNumber && $0 != "-" }
                context.draw(Text(letter).font(.system(size: min(width * 0.45, 13), weight: .bold))
                                .foregroundStyle(.black),
                             at: CGPoint(x: rect.midX, y: rect.maxY - 10))
            }
        }

        // Keyboard: white keys, then black keys on top; sounding keys take their hand's colour.
        for midi in whiteKeys {
            let rect = CGRect(x: column(midi).x, y: keyboardTop, width: whiteWidth, height: keyboardHeight)
            context.fill(Path(rect), with: .color(sounding[midi] ?? .white))
            context.stroke(Path(rect), with: .color(.black.opacity(0.35)), lineWidth: 1)
            if midi % 12 == 0, whiteWidth >= 14 {
                context.draw(Text("C\(midi / 12 - 1)").font(.system(size: min(whiteWidth * 0.4, 11)))
                                .foregroundStyle(.black.opacity(0.5)),
                             at: CGPoint(x: rect.midX, y: rect.maxY - 9))
            }
        }
        for midi in keys where isBlack(midi) {
            let (x, width) = column(midi)
            let rect = CGRect(x: x, y: keyboardTop, width: width, height: keyboardHeight * 0.62)
            context.fill(Path(roundedRect: rect, cornerRadius: 2), with: .color(sounding[midi] ?? .black))
        }

        // The line notes land on.
        var now = Path()
        now.move(to: CGPoint(x: 0, y: keyboardTop))
        now.addLine(to: CGPoint(x: size.width, y: keyboardTop))
        context.stroke(now, with: .color(.white), lineWidth: 2)
    }
}
