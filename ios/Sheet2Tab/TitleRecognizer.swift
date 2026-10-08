import UIKit
import Vision

/// Guesses a piece's title from a photo of the sheet music, on the device.
/// (oemer doesn't read text, so the server can't tell us the title.)
enum TitleRecognizer {
    /// The largest line of text in the top part of the page, which is usually the title.
    static func guessTitle(in image: UIImage) async -> String? {
        let scaled = image.downscaled(maxSide: 2000)
        guard let cgImage = scaled.cgImage else { return nil }
        let orientation = CGImagePropertyOrientation(scaled.imageOrientation)

        return await Task.detached(priority: .userInitiated) {
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = true
            try? VNImageRequestHandler(cgImage: cgImage, orientation: orientation).perform([request])
            return pickTitle(request.results ?? [])
        }.value
    }

    private static func pickTitle(_ lines: [VNRecognizedTextObservation]) -> String? {
        let candidates = lines.compactMap { line -> (text: String, height: CGFloat)? in
            guard let text = line.topCandidates(1).first?.string
                    .trimmingCharacters(in: .whitespacesAndNewlines),
                  line.boundingBox.minY > 0.6,  // top 40% of the page; Vision's origin is bottom-left
                  text.filter(\.isLetter).count >= 3  // skip "mf", "♩ = 120", page numbers
            else { return nil }
            return (text, line.boundingBox.height)
        }
        return candidates.max { $0.height < $1.height }?.text
    }
}

private extension CGImagePropertyOrientation {
    init(_ orientation: UIImage.Orientation) {
        switch orientation {
        case .up: self = .up
        case .upMirrored: self = .upMirrored
        case .down: self = .down
        case .downMirrored: self = .downMirrored
        case .left: self = .left
        case .leftMirrored: self = .leftMirrored
        case .right: self = .right
        case .rightMirrored: self = .rightMirrored
        @unknown default: self = .up
        }
    }
}
