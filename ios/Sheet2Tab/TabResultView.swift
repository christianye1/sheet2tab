import SwiftUI

struct TabResultView: View {
    let result: ConvertResponse
    /// Title read from the photo, offered as the name when saving.
    var suggestedTitle: String? = nil
    /// Set when showing a tab from the library, or once this one has been saved.
    @State var savedName: String? = nil
    @State private var showSave = false

    var body: some View {
        List {
            Section {
                ScrollView(.horizontal) {
                    Text(result.tab_text)
                        .font(.system(size: 13, design: .monospaced))
                        .fixedSize()   // never wrap tab lines
                        .textSelection(.enabled)
                        .padding(.vertical, 8)
                }
            } header: {
                Text("\(result.notes.count) notes")
            }

            if !result.warnings.isEmpty {
                Section("Warnings") {
                    ForEach(result.warnings, id: \.self) { warning in
                        Label(warning, systemImage: "exclamationmark.triangle")
                            .font(.footnote)
                            .foregroundStyle(.orange)
                    }
                }
            }
        }
        .navigationTitle(savedName ?? "Tab")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if !result.notes.isEmpty {
                NavigationLink {
                    PlaybackView(result: result)
                } label: {
                    Label("Play", systemImage: "play.fill")
                }
            }
            if savedName == nil {
                Button("Save", systemImage: "square.and.arrow.down") { showSave = true }
            }
            ShareLink(item: savedName.map { "\($0)\n\n\(result.tab_text)" } ?? result.tab_text)
        }
        .sheet(isPresented: $showSave) {
            SaveTabView(result: result, suggestedTitle: suggestedTitle) { savedName = $0 }
        }
    }
}
