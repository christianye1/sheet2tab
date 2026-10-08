import PDFKit
import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

struct CaptureView: View {
    @AppStorage("backendURL") private var backendURL = "http://192.168.1.20:8000"
    /// "guitar" or "piano": what the sheet is converted for.
    @AppStorage("instrument") private var instrument = "guitar"

    /// The first page: shown, OCR'd for the title, and cropped for photos.
    @State private var image: UIImage?
    /// Pages after the first (multi-page PDFs and scans); converted together with `image`.
    @State private var morePages: [UIImage] = []
    @State private var photoItem: PhotosPickerItem?
    @State private var showScanner = false
    @State private var cropRequest: CropRequest?
    @State private var showFileImporter = false
    /// The image rendered from a PDF and the title read from its text, if any.
    @State private var pdfSource: (image: UIImage, title: String?)?
    @State private var showSettings = false
    @State private var isLoading = false
    @State private var job: JobStatus?
    @State private var convertTask: Task<Void, Never>?
    @State private var errorMessage: String?
    @State private var result: ConvertResponse?
    @State private var suggestedTitle: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                if isLoading {
                    JobProgressView(job: job)
                } else {
                    preview
                }

                HStack(spacing: 12) {
                    Button {
                        showScanner = true
                    } label: {
                        Label("Scan", systemImage: "doc.viewfinder")
                            .frame(maxWidth: .infinity)
                    }
                    .disabled(!DocumentScanner.isAvailable)

                    PhotosPicker(selection: $photoItem, matching: .images) {
                        Label("Library", systemImage: "photo.on.rectangle")
                            .frame(maxWidth: .infinity)
                    }

                    Button {
                        showFileImporter = true
                    } label: {
                        Label("Files", systemImage: "doc")
                            .frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.bordered)
                .controlSize(.regular)
                .font(.subheadline)

                Picker("Instrument", selection: $instrument) {
                    Label("Guitar", systemImage: "guitars").tag("guitar")
                    Label("Piano", systemImage: "pianokeys").tag("piano")
                }
                .pickerStyle(.segmented)
                .disabled(isLoading)

                if isLoading {
                    Button(role: .destructive) {
                        cancelConversion()
                    } label: {
                        Text("Cancel").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                } else {
                    Button {
                        convertTask = Task { await convert() }
                    } label: {
                        Text("Convert to Tab").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(image == nil)
                }
            }
            .padding()
            .navigationTitle("Sheet → Tab")
            .toolbar {
                Button { showSettings = true } label: { Image(systemName: "gear") }
            }
            .sheet(isPresented: $showSettings) { SettingsView(backendURL: $backendURL) }
            .fullScreenCover(isPresented: $showScanner) {
                DocumentScanner { setPages($0) }.ignoresSafeArea()
            }
            .fullScreenCover(item: $cropRequest) { request in
                PageCropView(image: request.image, corners: request.corners) { setPages([$0]) }
            }
            .fileImporter(isPresented: $showFileImporter, allowedContentTypes: [.pdf, .image]) { result in
                Task { await loadFile(result) }
            }
            .onChange(of: photoItem) { _, item in
                Task { await loadPhoto(item) }
            }
            .alert("Conversion failed", isPresented: .constant(errorMessage != nil)) {
                Button("OK") { errorMessage = nil }
            } message: {
                Text(errorMessage ?? "")
            }
            .navigationDestination(isPresented: Binding(
                get: { result != nil },
                set: { if !$0 { result = nil } }
            )) {
                if let result { TabResultView(result: result, suggestedTitle: suggestedTitle) }
            }
        }
    }

    @ViewBuilder private var preview: some View {
        if let image {
            Image(uiImage: image)
                .resizable()
                .scaledToFit()
                .frame(maxHeight: .infinity)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(alignment: .topTrailing) {
                    if !morePages.isEmpty {
                        Label("\(morePages.count + 1) pages", systemImage: "doc.on.doc")
                            .font(.footnote.weight(.semibold))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(.thinMaterial, in: Capsule())
                            .padding(8)
                    }
                }
        } else {
            ContentUnavailableView(
                "No photo yet",
                systemImage: "music.note.list",
                description: Text("Scan printed sheet music, pick a photo, or open a PDF from Files.")
            )
            .frame(maxHeight: .infinity)
        }
    }

    private func loadPhoto(_ item: PhotosPickerItem?) async {
        guard let item else { return }
        defer { photoItem = nil }  // so picking the same photo again triggers onChange
        do {
            if let data = try await item.loadTransferable(type: Data.self),
               let loaded = UIImage(data: data) {
                await cropPhoto(loaded)
            } else {
                errorMessage = "Could not load that photo."
            }
        } catch {
            errorMessage = "Could not load that photo: \(error.localizedDescription)"
        }
    }

    private func cropPhoto(_ loaded: UIImage) async {
        // Same size limit as the upload; keeps detection and cropping quick.
        let photo = loaded.downscaled(maxSide: 3000).upright()
        let corners = await PageDetector.detect(in: photo) ?? PageCorners()
        cropRequest = CropRequest(image: photo, corners: corners)
    }

    /// A PDF or image picked in Files. PDF pages are rendered at full resolution and
    /// need no cropping; images go through the same crop step as photos.
    private func loadFile(_ result: Result<URL, Error>) async {
        do {
            let url = try result.get()
            let accessing = url.startAccessingSecurityScopedResource()
            defer { if accessing { url.stopAccessingSecurityScopedResource() } }
            let data = try Data(contentsOf: url)

            if UTType(filenameExtension: url.pathExtension)?.conforms(to: .pdf) == true {
                guard let document = PDFDocument(data: data), document.pageCount > 0 else {
                    errorMessage = "Could not open that PDF."
                    return
                }
                guard !document.isLocked else {
                    errorMessage = "That PDF is password-protected."
                    return
                }
                guard document.pageCount <= Self.maxPages else {
                    errorMessage = "That PDF has \(document.pageCount) pages; at most \(Self.maxPages) can be converted at once."
                    return
                }
                usePDF(document)
            } else if let loaded = UIImage(data: data) {
                await cropPhoto(loaded)
            } else {
                errorMessage = "Could not open that file."
            }
        } catch {
            errorMessage = "Could not open that file: \(error.localizedDescription)"
        }
    }

    /// Same limit as the server's SHEET2TAB_MAX_PAGES default.
    private static let maxPages = 20

    /// All pages of a PDF, converted together; the title comes from the first page's text.
    private func usePDF(_ document: PDFDocument) {
        let pages = (0..<document.pageCount).compactMap { document.page(at: $0) }
        let rendered = pages.map { PDFImport.render($0) }
        setPages(rendered)
        if let first = rendered.first {
            pdfSource = (first, PDFImport.title(of: pages[0]))
        }
    }

    private func setPages(_ pages: [UIImage]) {
        image = pages.first
        morePages = Array(pages.dropFirst())
    }

    private func convert() async {
        guard let image else { return }
        isLoading = true
        job = nil
        UIApplication.shared.isIdleTimerDisabled = true  // keep the screen on during OMR
        defer {
            isLoading = false
            job = nil
            UIApplication.shared.isIdleTimerDisabled = false
        }
        // Read the title on the phone while the server does the slow part. A PDF's own
        // text is exact; otherwise OCR the image.
        let pdfTitle = pdfSource?.image === image ? pdfSource?.title : nil
        let titleTask = Task<String?, Never> {
            if let pdfTitle { return pdfTitle }
            return await TitleRecognizer.guessTitle(in: image)
        }
        let client = APIClient(baseURL: backendURL)
        do {
            var status = try await client.startJob(images: [image] + morePages, instrument: instrument)
            job = status
            var failures = 0
            while status.status == "queued" || status.status == "running" {
                try await Task.sleep(for: .seconds(1))
                do {
                    status = try await client.job(id: status.id)
                    job = status
                    failures = 0
                } catch {
                    // Ride out a brief Wi-Fi hiccup; give up if the server stays unreachable.
                    failures += 1
                    if failures >= 5 { throw error }
                }
            }
            if let converted = status.result {
                suggestedTitle = await titleTask.value
                result = converted
            } else {
                errorMessage = status.error ?? "Conversion failed."
            }
        } catch {
            // A cancelled task throws too (from sleep or the request); that's not a failure.
            if !Task.isCancelled {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func cancelConversion() {
        // Stop polling right away; tell the server to kill OMR in the background.
        if let id = job?.id {
            let client = APIClient(baseURL: backendURL)
            Task { try? await client.cancelJob(id: id) }
        }
        convertTask?.cancel()
        convertTask = nil
    }
}

/// Current step, overall progress and how long each step took, so slow steps are visible.
private struct JobProgressView: View {
    let job: JobStatus?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(.headline)
            if let job {
                ProgressView(value: job.progress)
                HStack {
                    Text("\(Int(job.progress * 100))%")
                    Spacer()
                    Text("\(Self.format(job.elapsed)) elapsed")
                }
                .font(.footnote)
                .foregroundStyle(.secondary)
                .monospacedDigit()

                Divider()
                ScrollView {
                    VStack(spacing: 10) {
                        ForEach(job.stages) { stage in
                            HStack {
                                if stage.done {
                                    Image(systemName: "checkmark.circle.fill")
                                        .foregroundStyle(.green)
                                } else {
                                    ProgressView()
                                        .controlSize(.small)
                                }
                                Text(stage.name)
                                Spacer()
                                Text(Self.format(stage.seconds))
                                    .monospacedDigit()
                                    .foregroundStyle(.secondary)
                            }
                            .font(.subheadline)
                        }
                    }
                }
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    private var title: String {
        guard let job else { return "Uploading photo…" }
        if job.status == "queued" { return "Waiting for another conversion to finish…" }
        return job.stage.map { "\($0)…" } ?? "Starting…"
    }

    static func format(_ seconds: Double) -> String {
        Duration.seconds(seconds).formatted(.time(pattern: .minuteSecond))
    }
}
