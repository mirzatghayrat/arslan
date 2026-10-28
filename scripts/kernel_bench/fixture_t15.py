"""T15 fixture: a tiny synthetic Swift package; the PR adds the model behind a notes list.
Written for the bench, no real project's code. The planted bugs are in check_t15.BUGS."""

from __future__ import annotations

from pathlib import Path

from scripts.kernel_bench import review_kit

BASE = {
    "Package.swift": """// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Notes",
    targets: [.target(name: "Notes")]
)
""",
    "Sources/Notes/Note.swift": """public struct Note: Equatable {
    public let id: Int
    public var title: String
    public var body: String

    public init(id: Int, title: String, body: String) {
        self.id = id
        self.title = title
        self.body = body
    }
}
""",
    "Sources/Notes/Paging.swift": """/// One page of the notes list. The server numbers pages from 1.
public struct PageRequest: Equatable {
    public let page: Int
    public let size: Int

    public init(page: Int, size: Int = 20) {
        self.page = page
        self.size = size
    }
}

public protocol NotesAPI: AnyObject {
    /// Calls `completion` once, on the main queue.
    func fetch(_ request: PageRequest, completion: @escaping (Result<[Note], Error>) -> Void)
}
""",
    "Sources/Notes/EditTracker.swift": """/// Tells the editor whether to ask "Save changes?" when the user leaves a note.
public enum EditTracker {
    /// True when the note was changed since it was opened.
    public static func hasUnsavedChanges(opened: Note, current: Note) -> Bool {
        opened != current
    }
}
""",
}

PR = {
    "Sources/Notes/Note.swift": """public struct Note: Equatable {
    public let id: Int
    public var title: String
    public var body: String

    public init(id: Int, title: String, body: String) {
        self.id = id
        self.title = title
        self.body = body
    }

    /// Two notes are the same row when they have the same id, so the list keeps its rows across edits.
    public static func == (lhs: Note, rhs: Note) -> Bool {
        lhs.id == rhs.id
    }
}
""",
    "Sources/Notes/NotesModel.swift": """import Foundation

/// Backs the notes list screen.
public final class NotesModel {
    public private(set) var notes: [Note] = []
    public var searchText = ""
    public var onChange: (() -> Void)?
    private let api: NotesAPI
    private let firstPage = PageRequest(page: 0)

    public init(api: NotesAPI) {
        self.api = api
    }

    /// What the list shows: every note, or those whose title matches the search.
    public var visible: [Note] {
        searchText.isEmpty ? notes : notes.filter { $0.title.localizedCaseInsensitiveContains(searchText) }
    }

    private var refreshTimer: Timer?

    /// Load the first page, then refresh it every minute while the model exists.
    public func start() {
        load(firstPage)
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in
            self.load(self.firstPage)
        }
    }

    /// Delete the note at `index` in the list the user sees.
    public func delete(at index: Int) {
        let id = visible[index].id
        notes.removeAll { $0.id == id }
        onChange?()
    }

    /// The "Go to note" box: the user types a note's number.
    public func jump(to text: String) -> Note? {
        let id = Int(text)!
        return notes.first { $0.id == id }
    }

    private func load(_ request: PageRequest) {
        api.fetch(request) { [weak self] result in
            guard let self, case .success(let page) = result else { return }
            self.notes = page
            self.onChange?()
        }
    }
}
""",
}

MESSAGE = """Add NotesModel for the notes list

- Loads the first page and refreshes every minute.
- Search, delete and "go to note".
- Note equality is by id, so list rows survive an edit.
"""


def head() -> dict[str, str]:
    """Every file as it stands on `feature`."""
    return {**BASE, **PR}


def fixture(run: str) -> None:
    review_kit.build_repo(Path(run) / "repo", BASE, PR, MESSAGE)
