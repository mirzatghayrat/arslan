"""Reading, writing and handing over files."""
from server.registry.tool import Offer, Tool

# File tools. READS and WRITES now have different gates (spec 2026-08-24):
#
#   reads (read_file/list_dir/search_files) are offered when default-read is ON
#     (default) OR a workspace is set — so a novice can "look at my desktop" the
#     moment they install, bounded to the green ring (~/Desktop, ~/Documents,
#     ~/Downloads) plus any workspace. macOS does NOT gate those folders for this
#     app class (measured), so the boundary is our resolver, not the OS.
#   writes (write_file/edit_file) stay workspace-only and session-gated — the
#     green ring is READ-open, not write-open. No workspace ⇒ no writers offered,
#     unchanged from P1.


def _readable(offer: Offer) -> bool:
    return offer.default_read or offer.workspace


FILES = (
    Tool("read_file",
         "Read a text file. args: {path, offset?, limit?} — an absolute or ~/ "
         "path in the user's Desktop, Documents, Downloads, or workspace. A "
         "long file comes back truncated; page through it with offset and limit "
         "(in lines). Saved tool outputs are read this way too.",
         {"type": "object", "properties": {
             "path": {"type": "string", "minLength": 1,
                      "description": "File path within the approved readable roots or workspace."},
             "offset": {"type": "integer", "minimum": 0,
                        "description": "Lines to skip from the start (for paging a long file)."},
             "limit": {"type": "integer", "minimum": 1, "description": "Maximum lines to return."}},
             "required": ["path"], "additionalProperties": False},
         offered=_readable),
    Tool("list_dir",
         "List one level of a folder; with no path, the folders you can "
         "see. Absolute or ~/ path in "
         "Desktop, Documents, Downloads, or the workspace.",
         {
             "type": "object",
             "properties": {"path": {"type": "string", "description": (
                 "Absolute or ~/ folder path in Desktop, Documents, Downloads or the workspace; leave it out to list "
                 "the folders you can see.")}},
             "additionalProperties": False,
         },
         offered=_readable),
    Tool("search_files",
         "Find a literal string across the readable folders' text "
         "files (Desktop, Documents, Downloads, workspace). "
         "Returns path + line + the matching line; bounded, "
         "so a huge folder returns truncated=true rather than hanging.",
         {
             "type": "object",
             "properties": {"query": {"type": "string", "minLength": 1,
                                      "description": "Literal text to find in the readable folders' text files."}},
             "required": ["query"],
             "additionalProperties": False,
         },
         offered=_readable),
    # Writers stay workspace-only and gated by the session grant (P1b) —
    # except Arslan's own folder, which needs no grant (0.1.48). The text
    # says which, because "you will be asked" made models hedge or refuse.
    Tool("write_file",
         lambda offer: ("Create or overwrite a WORKSPACE file. "
                        "Missing folders in the path are created. Only the workspace, "
                        "not Desktop/Documents. " + (
                            "The workspace is your own folder: saving there needs no "
                            "permission — just write the file." if offer.own_folder else
                            "The user is asked for write permission: for this write, or for "
                            "any file in the folder for the rest of the conversation.")),
         {"type": "object", "properties": {
             "path": {"type": "string", "minLength": 1,
                      "description": "Destination file path within the configured workspace; "
                                     "missing folders are created."},
             "content": {"type": "string", "description": "Complete UTF-8 text to write."}},
             "required": ["path", "content"], "additionalProperties": False},
         offered=lambda offer: offer.workspace),
    Tool("edit_file",
         "Replace a UNIQUE occurrence of `old_string` with `new_string` in a "
         "WORKSPACE file. Read the file "
         "first. An ambiguous `old_string` is refused with its match count — "
         "give a longer snippet instead.",
         {
             "type": "object",
             "properties": {
                 "path": {"type": "string", "minLength": 1, "description": "File path within the configured workspace."},
                 "old_string": {"type": "string", "minLength": 1,
                                "description": "The exact text to replace; it must appear exactly once in the file."},
                 "new_string": {"type": "string", "description": "The text to put in its place."},
             },
             "required": ["path", "old_string", "new_string"],
             "additionalProperties": False,
         },
         offered=lambda offer: offer.workspace),
)

# 0.1.63 D1: a file the user asked for reaches them, not just its Mac path. Offered with the read
# tools, appended after every other built-in so no existing tool moves (the K3 / K7 rule).
# 0.1.63 D1: hand an existing file to the user (window card + paired iPhone).
ATTACH_FILE = Tool("attach_file",
                   "Attach an existing file to your answer so the user gets the file itself: a file card in the "
                   "Mac window and the file on their iPhone. args: {path, title?} — absolute, ~/ or "
                   "workspace-relative, in a readable folder; up to 20 MB a file, at most 32 files and 100 MB in "
                   "all per answer (files saved with write_file count too). Use it whenever the user asks for a "
                   "file (a screenshot, chart, export or document) instead of only naming its path. A screenshot "
                   "must first be saved as a file (for example with screencapture); save a new capture under a "
                   "new name, since the same call is not repeated.",
                   {"type": "object", "properties": {
                       "path": {"type": "string", "minLength": 1,
                                "description": "The file: absolute, ~/ or relative to the workspace, in a readable folder."},
                       "title": {"type": "string", "maxLength": 200,
                                 "description": "Optional name the user sees; the file's extension is kept."}},
                       "required": ["path"], "additionalProperties": False},
                   offered=_readable)
