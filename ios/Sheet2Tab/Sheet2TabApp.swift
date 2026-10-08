import SwiftUI

@main
struct Sheet2TabApp: App {
    @State private var library = TabLibrary()

    var body: some Scene {
        WindowGroup {
            TabView {
                CaptureView()
                    .tabItem { Label("Convert", systemImage: "camera") }
                LibraryView()
                    .tabItem { Label("Library", systemImage: "books.vertical") }
            }
            .environment(library)
        }
    }
}
