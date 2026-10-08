import Foundation
import Observation

/// What's stored per saved tab, as one JSON file.
/// Fields added later must be optional so older saved files keep decoding.
struct SavedTab: Codable {
    var created: Date
    var result: ConvertResponse
}

/// A tab file or a folder in the library. Folders are paths relative to the library root,
/// e.g. "" (the root), "Rock", "Rock/Beatles".
struct LibraryItem: Identifiable, Hashable {
    let folder: String  // parent folder
    let name: String    // folder name, or tab file name without ".json"
    let isFolder: Bool

    var path: String { folder.isEmpty ? name : folder + "/" + name }
    var id: String { isFolder ? path + "/" : path }
}

enum LibraryError: LocalizedError {
    case emptyName
    case exists(String)
    case moveIntoItself

    var errorDescription: String? {
        switch self {
        case .emptyName: return "Please enter a name."
        case .exists(let name): return "\"\(name)\" already exists here."
        case .moveIntoItself: return "A folder can't be moved into itself."
        }
    }
}

/// Saved tabs, stored as plain files and folders in the app's Documents directory.
///
/// - They survive app updates and re-installs from Xcode; only deleting the app (or changing
///   its bundle ID) loses them.
/// - They're part of iPhone backups and show up in the Files app under
///   On My iPhone › Sheet2Tab (see UIFileSharingEnabled in Info.plist).
/// - The folders on disk *are* the library; there's no database to migrate between versions.
@Observable
final class TabLibrary {
    let root: URL
    /// Bumped on every change so views listing the library re-read it.
    private var revision = 0

    @ObservationIgnored private let fm = FileManager.default
    @ObservationIgnored private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        return e
    }()
    @ObservationIgnored private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    init(root: URL = .documentsDirectory) {
        self.root = root
    }

    // MARK: Reading

    func items(in folder: String) -> [LibraryItem] {
        _ = revision
        let urls = (try? fm.contentsOfDirectory(at: url(ofFolder: folder),
                                                includingPropertiesForKeys: [.isDirectoryKey],
                                                options: .skipsHiddenFiles)) ?? []
        return urls.compactMap { url -> LibraryItem? in
            if (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true {
                return LibraryItem(folder: folder, name: url.lastPathComponent, isFolder: true)
            }
            guard url.pathExtension == "json" else { return nil }
            return LibraryItem(folder: folder, name: url.deletingPathExtension().lastPathComponent,
                               isFolder: false)
        }
        .sorted { a, b in
            if a.isFolder != b.isFolder { return a.isFolder }
            return a.name.localizedStandardCompare(b.name) == .orderedAscending
        }
    }

    /// The root and every folder below it, depth-first, for "save to" and "move to" pickers.
    func allFolders() -> [String] {
        func walk(_ folder: String) -> [String] {
            [folder] + items(in: folder).filter(\.isFolder).flatMap { walk($0.path) }
        }
        return walk("")
    }

    func exists(folder: String) -> Bool {
        var isDir: ObjCBool = false
        return fm.fileExists(atPath: url(ofFolder: folder).path, isDirectory: &isDir) && isDir.boolValue
    }

    func load(_ item: LibraryItem) throws -> SavedTab {
        try decoder.decode(SavedTab.self, from: Data(contentsOf: url(of: item)))
    }

    static func displayName(ofFolder folder: String) -> String {
        folder.isEmpty ? "Library" : folder.replacingOccurrences(of: "/", with: " › ")
    }

    // MARK: Changing

    /// Re-read the disk, e.g. after files were changed in the Files app.
    func reload() {
        revision += 1
    }

    @discardableResult
    func createFolder(named name: String, in parent: String) throws -> String {
        let item = LibraryItem(folder: parent, name: try Self.cleanName(name), isFolder: true)
        guard !fm.fileExists(atPath: url(of: item).path) else { throw LibraryError.exists(item.name) }
        try fm.createDirectory(at: url(of: item), withIntermediateDirectories: true)
        revision += 1
        return item.path
    }

    /// Saves under `name`, adding " 2", " 3", … if that name is taken. Returns the name used.
    @discardableResult
    func save(_ result: ConvertResponse, named name: String, in folder: String) throws -> String {
        try fm.createDirectory(at: url(ofFolder: folder), withIntermediateDirectories: true)
        let item = uniqueItem(named: try Self.cleanName(name), in: folder, isFolder: false)
        let data = try encoder.encode(SavedTab(created: .now, result: result))
        try data.write(to: url(of: item), options: .atomic)
        revision += 1
        return item.name
    }

    func rename(_ item: LibraryItem, to newName: String) throws {
        let renamed = LibraryItem(folder: item.folder, name: try Self.cleanName(newName),
                                  isFolder: item.isFolder)
        guard renamed.name != item.name else { return }
        // The file system ignores case, so "abc" -> "ABC" collides with itself.
        if renamed.name.lowercased() != item.name.lowercased(),
           fm.fileExists(atPath: url(of: renamed).path) {
            throw LibraryError.exists(renamed.name)
        }
        try fm.moveItem(at: url(of: item), to: url(of: renamed))
        revision += 1
    }

    func move(_ item: LibraryItem, to folder: String) throws {
        guard folder != item.folder else { return }
        if item.isFolder, folder == item.path || folder.hasPrefix(item.path + "/") {
            throw LibraryError.moveIntoItself
        }
        let moved = uniqueItem(named: item.name, in: folder, isFolder: item.isFolder)
        try fm.moveItem(at: url(of: item), to: url(of: moved))
        revision += 1
    }

    /// Deletes a tab, or a folder with everything in it.
    func delete(_ item: LibraryItem) throws {
        try fm.removeItem(at: url(of: item))
        revision += 1
    }

    // MARK: Helpers

    private func url(ofFolder folder: String) -> URL {
        folder.isEmpty ? root : root.appending(path: folder, directoryHint: .isDirectory)
    }

    private func url(of item: LibraryItem) -> URL {
        item.isFolder
            ? url(ofFolder: item.path)
            : url(ofFolder: item.folder).appending(path: item.name + ".json", directoryHint: .notDirectory)
    }

    private func uniqueItem(named name: String, in folder: String, isFolder: Bool) -> LibraryItem {
        var candidate = LibraryItem(folder: folder, name: name, isFolder: isFolder)
        var n = 2
        while fm.fileExists(atPath: url(of: candidate).path) {
            candidate = LibraryItem(folder: folder, name: "\(name) \(n)", isFolder: isFolder)
            n += 1
        }
        return candidate
    }

    /// Turns a user-typed name into a safe file name ("AC/DC" -> "AC-DC").
    static func cleanName(_ name: String) throws -> String {
        var cleaned = name
            .replacingOccurrences(of: "/", with: "-")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        while cleaned.hasPrefix(".") { cleaned.removeFirst() }  // hidden files
        cleaned = String(cleaned.prefix(150))
        guard !cleaned.isEmpty else { throw LibraryError.emptyName }
        return cleaned
    }
}
