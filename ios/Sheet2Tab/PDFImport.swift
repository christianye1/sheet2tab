import PDFKit
import SwiftUI

/// Turns a PDF page into an image for OMR. Sheet music PDFs are usually vector graphics,
/// so rendering them large gives crisp, evenly thick staff lines, unlike a screenshot.
enum PDFImport {
    /// Longest side of the rendered page. The server scales down to SHEET2TAB_OMR_MAX_SIDE
    /// (2500) anyway, and the upload is capped at 3000.
    static let renderSide: CGFloat = 3000

    static func render(_ page: PDFPage, longSide: CGFloat = renderSide) -> UIImage {
        var size = page.bounds(for: .cropBox).size
        if page.rotation % 180 != 0 { size = CGSize(width: size.height, height: size.width) }
        let scale = longSide / max(size.width, size.height, 1)
        // thumbnail(of:for:) draws on white and applies the page's rotation.
        return page.thumbnail(of: CGSize(width: size.width * scale, height: size.height * scale),
                              for: .cropBox)
    }

    /// The line of text set in the largest font, which on sheet music is the title.
    /// Nil for scanned PDFs without a text layer; the caller then falls back to OCR.
    static func title(of page: PDFPage) -> String? {
        guard let text = page.attributedString else { return nil }
        let string = text.string as NSString
        var best: (size: CGFloat, line: String)?
        string.enumerateSubstrings(in: NSRange(location: 0, length: string.length),
                                   options: .byLines) { line, range, _, _ in
            guard let line = line?.trimmingCharacters(in: .whitespaces),
                  line.filter(\.isLetter).count >= 3 else { return }
            var size: CGFloat = 0
            text.enumerateAttribute(.font, in: range) { font, _, _ in
                size = max(size, (font as? UIFont)?.pointSize ?? 0)
            }
            if size > (best?.size ?? 0) { best = (size, line) }
        }
        return best?.line
    }
}

