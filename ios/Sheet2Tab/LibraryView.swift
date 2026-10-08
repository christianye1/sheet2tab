import SwiftUI

/// Saved tabs, browsable by folder.
struct LibraryView: View {
    var body: some View {
        NavigationStack {
            FolderView(folder: "")
                .navigationDestination(for: LibraryItem.self) { item in
                    if item.isFolder {
                        FolderView(folder: item.path)
                    } else {
                        SavedTabView(item: item)
                    }
                }
        }
    }
}

private struct FolderView: View {
    let folder: String
    @Environment(TabLibrary.self) private var library

    @State private var showNewFolder = false
    @State private var newFolderName = ""
    @State private var renaming: LibraryItem?
    @State private var renameText = ""
    @State private var moving: LibraryItem?
    @State private var deleting: LibraryItem?
    @State private var errorMessage: String?

    var body: some View {
        let items = library.items(in: folder)
        List {
            ForEach(items) { item in
                NavigationLink(value: item) {
                    Label(item.name, systemImage: item.isFolder ? "folder" : "music.note.list")
                }
                .contextMenu {
                    Button("Rename", systemImage: "pencil") {
                        renameText = item.name
                        renaming = item
                    }
                    Button("Move", systemImage: "folder") { moving = item }
                    Button("Delete", systemImage: "trash", role: .destructive) { deleting = item }
                }
                .swipeActions {
                    Button("Delete", systemImage: "trash", role: .destructive) { deleting = item }
                    Button("Move", systemImage: "folder") { moving = item }
                        .tint(.indigo)
                }
            }
        }
        .overlay {
            if items.isEmpty {
                ContentUnavailableView(
                    folder.isEmpty ? "No saved tabs" : "Empty folder",
                    systemImage: "folder",
                    description: Text("Save a tab from the result screen. Tap \(Image(systemName: "folder.badge.plus")) to add a folder.")
                )
            }
        }
        .navigationTitle(folder.isEmpty ? "Library" : (folder as NSString).lastPathComponent)
        .toolbar {
            Button("New Folder", systemImage: "folder.badge.plus") {
                newFolderName = ""
                showNewFolder = true
            }
        }
        .refreshable { library.reload() }  // picks up changes made in the Files app
        .onAppear { library.reload() }
        .alert("New Folder", isPresented: $showNewFolder) {
            TextField("Name", text: $newFolderName)
            Button("Cancel", role: .cancel) {}
            Button("Create") { attempt { try library.createFolder(named: newFolderName, in: folder) } }
        }
        .alert("Rename", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("Name", text: $renameText)
            Button("Cancel", role: .cancel) {}
            Button("Rename") {
                if let renaming { attempt { try library.rename(renaming, to: renameText) } }
            }
        }
        .confirmationDialog(
            deleting.map { $0.isFolder ? "Delete \"\($0.name)\" and everything in it?" : "Delete \"\($0.name)\"?" } ?? "",
            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
            titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                if let deleting { attempt { try library.delete(deleting) } }
            }
        }
        .sheet(item: $moving) { item in
            FolderPickerView(title: "Move \"\(item.name)\"", excluding: item) { target in
                attempt { try library.move(item, to: target) }
            }
        }
        .alert("Something went wrong", isPresented: Binding(get: { errorMessage != nil }, set: { if !$0 { errorMessage = nil } })) {
            Button("OK") {}
        } message: {
            Text(errorMessage ?? "")
        }
    }

    private func attempt(_ action: () throws -> Void) {
        do { try action() } catch { errorMessage = error.localizedDescription }
    }
}

/// Lists every folder; tapping one picks it.
private struct FolderPickerView: View {
    let title: String
    let excluding: LibraryItem  // the item being moved: not its own folder, nor anything inside it
    let onPick: (String) -> Void
    @Environment(TabLibrary.self) private var library
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List(library.allFolders().filter(isAllowed), id: \.self) { folder in
                Button {
                    onPick(folder)
                    dismiss()
                } label: {
                    Label(TabLibrary.displayName(ofFolder: folder),
                          systemImage: folder.isEmpty ? "books.vertical" : "folder")
                }
                .disabled(folder == excluding.folder)
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                Button("Cancel") { dismiss() }
            }
        }
    }

    private func isAllowed(_ folder: String) -> Bool {
        !excluding.isFolder || (folder != excluding.path && !folder.hasPrefix(excluding.path + "/"))
    }
}

private struct SavedTabView: View {
    let item: LibraryItem
    @Environment(TabLibrary.self) private var library

    var body: some View {
        switch Result(catching: { try library.load(item) }) {
        case .success(let saved):
            TabResultView(result: saved.result, savedName: item.name)
        case .failure(let error):
            ContentUnavailableView("Can't open this tab", systemImage: "exclamationmark.triangle",
                                   description: Text(error.localizedDescription))
        }
    }
}

/// Name the tab (pre-filled with the recognized title) and pick or create a folder.
struct SaveTabView: View {
    let result: ConvertResponse
    let onSaved: (String) -> Void
    @Environment(TabLibrary.self) private var library
    @Environment(\.dismiss) private var dismiss
    /// Remember the last folder used, since tabs usually go into the same place.
    @AppStorage("lastSaveFolder") private var lastFolder = ""

    @State private var name: String
    @State private var folder = ""
    @State private var showNewFolder = false
    @State private var newFolderName = ""
    @State private var errorMessage: String?
    private let recognized: Bool

    init(result: ConvertResponse, suggestedTitle: String?, onSaved: @escaping (String) -> Void) {
        self.result = result
        self.onSaved = onSaved
        recognized = suggestedTitle != nil
        _name = State(initialValue: suggestedTitle
                      ?? "Tab \(Date.now.formatted(date: .abbreviated, time: .shortened))")
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Song title", text: $name)
                } header: {
                    Text("Name")
                } footer: {
                    Text(recognized ? "Read from the photo. Correct it if it's wrong." :
                            "No title found in the photo.")
                }

                Section("Folder") {
                    Picker("Save in", selection: $folder) {
                        ForEach(library.allFolders(), id: \.self) { folder in
                            Text(TabLibrary.displayName(ofFolder: folder)).tag(folder)
                        }
                    }
                    Button("New Folder…", systemImage: "folder.badge.plus") {
                        newFolderName = ""
                        showNewFolder = true
                    }
                }

                if let errorMessage {
                    Text(errorMessage).foregroundStyle(.red)
                }
            }
            .navigationTitle("Save Tab")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save", action: save)
                        .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .onAppear {
                folder = library.exists(folder: lastFolder) ? lastFolder : ""
            }
            .alert("New Folder", isPresented: $showNewFolder) {
                TextField("Name", text: $newFolderName)
                Button("Cancel", role: .cancel) {}
                Button("Create") {
                    do {
                        folder = try library.createFolder(named: newFolderName, in: folder)
                        errorMessage = nil
                    } catch {
                        errorMessage = error.localizedDescription
                    }
                }
            } message: {
                Text("Inside \(TabLibrary.displayName(ofFolder: folder))")
            }
        }
    }

    private func save() {
        do {
            let savedName = try library.save(result, named: name, in: folder)
            lastFolder = folder
            onSaved(savedName)
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
