import SwiftUI

struct SettingsView: View {
    @Binding var backendURL: String
    @Environment(\.dismiss) private var dismiss
    @State private var status: String?
    @State private var testing = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://192.168.1.20:8000", text: $backendURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("Backend URL")
                } footer: {
                    Text("Your Mac's local IP and the server port. See the README for how to find it.")
                }

                Section {
                    Button(testing ? "Testing…" : "Test connection") {
                        Task { await test() }
                    }
                    .disabled(testing)
                    if let status {
                        Text(status).font(.footnote)
                    }
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                Button("Done") { dismiss() }
            }
        }
    }

    private func test() async {
        testing = true
        defer { testing = false }
        do {
            try await APIClient(baseURL: backendURL).health()
            status = "✅ Connected"
        } catch {
            status = "❌ \(error.localizedDescription)"
        }
    }
}
