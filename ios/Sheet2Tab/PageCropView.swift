import CoreImage
import CoreImage.CIFilterBuiltins
import SwiftUI
import Vision

/// The page's corners as fractions of the image size (0...1, origin top-left).
struct PageCorners {
    var topLeft = CGPoint(x: 0, y: 0)
    var topRight = CGPoint(x: 1, y: 0)
    var bottomRight = CGPoint(x: 1, y: 1)
    var bottomLeft = CGPoint(x: 0, y: 1)

    static let all: [WritableKeyPath<PageCorners, CGPoint>] =
        [\.topLeft, \.topRight, \.bottomRight, \.bottomLeft]
}

/// Library photos get the same treatment as the document scanner: find the page, let the
/// user adjust the corners, then crop and straighten it.
enum PageDetector {
    /// Page corners found by Vision, or nil if it doesn't see a document.
    static func detect(in image: UIImage) async -> PageCorners? {
        guard let cgImage = image.cgImage else { return nil }
        return await Task.detached(priority: .userInitiated) {
            let request = VNDetectDocumentSegmentationRequest()
            try? VNImageRequestHandler(cgImage: cgImage).perform([request])
            guard let page = request.results?.first else { return nil }
            // Vision's origin is bottom-left.
            func flip(_ p: CGPoint) -> CGPoint { CGPoint(x: p.x, y: 1 - p.y) }
            return PageCorners(topLeft: flip(page.topLeft), topRight: flip(page.topRight),
                               bottomRight: flip(page.bottomRight), bottomLeft: flip(page.bottomLeft))
        }.value
    }

    /// Cuts out the quadrilateral and warps it into a flat rectangle.
    static func crop(_ image: UIImage, to corners: PageCorners) -> UIImage? {
        guard let cgImage = image.cgImage else { return nil }
        let input = CIImage(cgImage: cgImage)
        let (w, h) = (input.extent.width, input.extent.height)
        // Core Image's origin is bottom-left too.
        func pixel(_ p: CGPoint) -> CGPoint { CGPoint(x: p.x * w, y: (1 - p.y) * h) }

        let filter = CIFilter.perspectiveCorrection()
        filter.inputImage = input
        filter.topLeft = pixel(corners.topLeft)
        filter.topRight = pixel(corners.topRight)
        filter.bottomRight = pixel(corners.bottomRight)
        filter.bottomLeft = pixel(corners.bottomLeft)
        guard let output = filter.outputImage,
              let result = CIContext().createCGImage(output, from: output.extent) else { return nil }
        return UIImage(cgImage: result)
    }
}

/// Shows the photo with four draggable corner handles around the page.
struct PageCropView: View {
    let image: UIImage
    let onDone: (UIImage) -> Void
    @State private var corners: PageCorners
    @Environment(\.dismiss) private var dismiss

    init(image: UIImage, corners: PageCorners, onDone: @escaping (UIImage) -> Void) {
        self.image = image
        self.onDone = onDone
        _corners = State(initialValue: corners)
    }

    var body: some View {
        NavigationStack {
            GeometryReader { geo in
                let frame = fittedFrame(in: geo.size)
                ZStack {
                    Image(uiImage: image)
                        .resizable()
                        .frame(width: frame.width, height: frame.height)
                        .position(x: frame.midX, y: frame.midY)

                    Path { path in
                        path.addLines(PageCorners.all.map { point(corners[keyPath: $0], in: frame) })
                        path.closeSubpath()
                    }
                    .fill(Color.accentColor.opacity(0.15))
                    .overlay {
                        Path { path in
                            path.addLines(PageCorners.all.map { point(corners[keyPath: $0], in: frame) })
                            path.closeSubpath()
                        }
                        .stroke(Color.accentColor, lineWidth: 2)
                    }

                    ForEach(PageCorners.all, id: \.self) { corner in
                        Circle()
                            .fill(.white)
                            .stroke(Color.accentColor, lineWidth: 3)
                            .frame(width: 28, height: 28)
                            .contentShape(Circle().inset(by: -12))  // easier to grab
                            .position(point(corners[keyPath: corner], in: frame))
                            .gesture(DragGesture(coordinateSpace: .named("crop")).onChanged { drag in
                                corners[keyPath: corner] = CGPoint(
                                    x: min(max((drag.location.x - frame.minX) / frame.width, 0), 1),
                                    y: min(max((drag.location.y - frame.minY) / frame.height, 0), 1))
                            })
                    }
                }
                .coordinateSpace(.named("crop"))
            }
            .padding(24)
            .background(Color.black)
            .navigationTitle("Adjust page")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Use whole photo") { finish(image) }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Crop") { finish(PageDetector.crop(image, to: corners) ?? image) }
                }
            }
        }
    }

    private func finish(_ result: UIImage) {
        onDone(result)
        dismiss()
    }

    /// Where the image sits when scaled to fit `size`.
    private func fittedFrame(in size: CGSize) -> CGRect {
        let scale = min(size.width / image.size.width, size.height / image.size.height)
        let fitted = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        return CGRect(x: (size.width - fitted.width) / 2, y: (size.height - fitted.height) / 2,
                      width: fitted.width, height: fitted.height)
    }

    private func point(_ p: CGPoint, in frame: CGRect) -> CGPoint {
        CGPoint(x: frame.minX + p.x * frame.width, y: frame.minY + p.y * frame.height)
    }
}

/// A library photo waiting to be cropped.
struct CropRequest: Identifiable {
    let id = UUID()
    let image: UIImage
    let corners: PageCorners
}

extension UIImage {
    /// Pixel data rotated to match how the photo is displayed, so Vision and Core Image
    /// (which ignore `imageOrientation`) see the same thing as the user.
    func upright() -> UIImage {
        guard imageOrientation != .up else { return self }
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = scale
        return UIGraphicsImageRenderer(size: size, format: format).image { _ in
            draw(in: CGRect(origin: .zero, size: size))
        }
    }
}
