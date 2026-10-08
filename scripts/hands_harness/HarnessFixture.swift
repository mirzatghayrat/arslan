// The app the Hands engine harness acts on (Hands v2, spec docs/specs/2026-10-08-0157-hands-v2.md §8.2).
//
// Ground truth a case is judged by (what really happened, and how many times), never the
// engine's own word: every event is appended to HARNESS_LOG as one JSON line
// {"t": seconds, "event": ..., "value": ...}, and every 50 ms the whole state (field
// values, counters, sheet, minimized, hidden) is written to HARNESS_STATE — values set
// through accessibility fire no text-change callback, so they are read, not awaited.
// Commands for setting a case up are read from HARNESS_CMD (one word per line:
// reset, minimize, unminimize, hide, unhide, close_sheet) and the file is emptied.
//
// Controls: Title field, Notes text view, Password field (must never be typed into),
// Save (counts presses), Delete (risky), a Color pop-up, a Done checkbox, a Slow button
// (its label changes 2 s after a press), a Chat field where Return "sends", Sheet buttons
// that open a sheet 0, 0.3, 0.8 or 1.5 s after a press, a Canvas of custom-drawn buttons
// with no accessibility, and a "Fixture" menu with Bold (⌘B) and Mark (no shortcut).
//
// Build: swiftc -O -o HarnessFixture HarnessFixture.swift
import AppKit

let env = ProcessInfo.processInfo.environment
let logPath = env["HARNESS_LOG"] ?? "/tmp/harness-fixture.log"
let statePath = env["HARNESS_STATE"] ?? "/tmp/harness-fixture.state.json"
let commandPath = env["HARNESS_CMD"] ?? "/tmp/harness-fixture.cmd"
let started = Date()

func record(_ event: String, _ value: Any = "") {
    let line: [String: Any] = ["t": Date().timeIntervalSince(started), "event": event, "value": value]
    guard let data = try? JSONSerialization.data(withJSONObject: line),
          var text = String(data: data, encoding: .utf8) else { return }
    text += "\n"
    if let handle = FileHandle(forWritingAtPath: logPath) {
        handle.seekToEndOfFile()
        handle.write(text.data(using: .utf8)!)
        handle.closeFile()
    } else {
        FileManager.default.createFile(atPath: logPath, contents: text.data(using: .utf8))
    }
}

/// Custom-drawn buttons with no accessibility elements: reachable by pixels only.
final class Canvas: NSView {
    let labels = ["A", "B", "C"]
    override func draw(_ dirtyRect: NSRect) {
        NSColor.windowBackgroundColor.setFill()
        dirtyRect.fill()
        for (i, label) in labels.enumerated() {
            let rect = NSRect(x: 10 + i * 70, y: 10, width: 60, height: 30)
            NSColor.systemBlue.setFill()
            NSBezierPath(roundedRect: rect, xRadius: 6, yRadius: 6).fill()
            (label as NSString).draw(at: NSPoint(x: rect.midX - 4, y: rect.midY - 8),
                                     withAttributes: [.foregroundColor: NSColor.white])
        }
    }
    override func mouseDown(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        for (i, label) in labels.enumerated()
        where NSRect(x: 10 + i * 70, y: 10, width: 60, height: 30).contains(point) {
            record("canvas", label)
        }
    }
    override func isAccessibilityElement() -> Bool { false }
}

final class Fixture: NSObject, NSApplicationDelegate, NSTextFieldDelegate, NSTextViewDelegate {
    var window: NSWindow!
    let title = NSTextField(string: "")
    let notes = NSTextView(frame: NSRect(x: 0, y: 0, width: 300, height: 60))
    let password = NSSecureTextField(string: "")
    let chat = NSTextField(string: "")
    let color = NSPopUpButton(frame: .zero, pullsDown: false)
    let done = NSButton(checkboxWithTitle: "Done", target: nil, action: nil)
    let slow = NSButton(title: "Slow", target: nil, action: nil)
    var saves = 0
    var sends = 0
    var lastState = ""

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 240, y: 160, width: 460, height: 560),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "Harness Fixture"
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.edgeInsets = NSEdgeInsets(top: 12, left: 12, bottom: 12, right: 12)

        title.placeholderString = "Title"
        title.setAccessibilityLabel("Title")
        title.delegate = self
        notes.setAccessibilityLabel("Notes")
        notes.delegate = self
        notes.isRichText = false
        let notesScroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 300, height: 60))
        notesScroll.documentView = notes
        notesScroll.heightAnchor.constraint(equalToConstant: 60).isActive = true
        notesScroll.widthAnchor.constraint(equalToConstant: 300).isActive = true
        password.placeholderString = "Password"
        password.setAccessibilityLabel("Password")
        password.delegate = self
        chat.placeholderString = "Message"
        chat.setAccessibilityLabel("Message")
        chat.target = self
        chat.action = #selector(sent)
        color.addItems(withTitles: ["Red", "Green", "Blue"])
        color.setAccessibilityLabel("Color")
        color.target = self
        color.action = #selector(picked)
        done.target = self
        done.action = #selector(toggled)
        slow.target = self
        slow.action = #selector(slowPressed)
        let save = NSButton(title: "Save", target: self, action: #selector(saved))
        let delete = NSButton(title: "Delete", target: self, action: #selector(deleted))
        let sheets = NSStackView(views: [0.0, 0.3, 0.8, 1.5].map { delay in
            let b = NSButton(title: "Sheet \(delay)", target: self, action: #selector(sheetPressed(_:)))
            b.tag = Int(delay * 10)
            return b
        })
        let canvas = Canvas(frame: NSRect(x: 0, y: 0, width: 230, height: 50))
        canvas.heightAnchor.constraint(equalToConstant: 50).isActive = true
        canvas.widthAnchor.constraint(equalToConstant: 230).isActive = true

        for view in [title, notesScroll, password, chat, color, done, slow, save, delete, sheets, canvas] as [NSView] {
            stack.addArrangedSubview(view)
        }
        for field in [title, password, chat] {
            field.widthAnchor.constraint(equalToConstant: 300).isActive = true
        }
        window.contentView = stack
        installMenu()
        window.orderFrontRegardless()
        record("ready")
        Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { _ in
            self.runCommands()
            self.writeState()
        }
    }

    func writeState() {
        let state: [String: Any] = [
            "title": title.stringValue, "notes": notes.string, "chat": chat.stringValue,
            "password_length": password.stringValue.count, "saves": saves, "sends": sends,
            "color": color.titleOfSelectedItem ?? "", "done": done.state == .on, "slow": slow.title,
            "sheet_open": window.attachedSheet != nil, "minimized": window.isMiniaturized,
            "hidden": NSApp.isHidden, "key": window.isKeyWindow,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: state, options: [.sortedKeys]),
              let text = String(data: data, encoding: .utf8), text != lastState else { return }
        lastState = text
        try? text.write(toFile: statePath + ".tmp", atomically: false, encoding: .utf8)
        _ = try? FileManager.default.replaceItemAt(URL(fileURLWithPath: statePath),
                                                   withItemAt: URL(fileURLWithPath: statePath + ".tmp"))
        if !FileManager.default.fileExists(atPath: statePath) {
            try? text.write(toFile: statePath, atomically: true, encoding: .utf8)
        }
    }

    func runCommands() {
        guard let text = try? String(contentsOfFile: commandPath, encoding: .utf8), !text.isEmpty else { return }
        try? "".write(toFile: commandPath, atomically: true, encoding: .utf8)
        for command in text.split(separator: "\n").map({ $0.trimmingCharacters(in: .whitespaces) }) {
            switch command {
            case "reset":
                title.stringValue = ""; notes.string = ""; chat.stringValue = ""; password.stringValue = ""
                color.selectItem(at: 0); done.state = .off; slow.title = "Slow"
                if let sheet = window.attachedSheet { window.endSheet(sheet) }
            case "minimize": window.miniaturize(nil)
            case "unminimize": window.deminiaturize(nil)
            case "hide": NSApp.hide(nil)
            case "unhide": NSApp.unhideWithoutActivation(); window.orderFrontRegardless()
            case "close_sheet": if let sheet = window.attachedSheet { window.endSheet(sheet) }
            default: continue
            }
            record("command", command)
        }
    }

    func installMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        appItem.submenu = NSMenu()
        main.addItem(appItem)
        let fixtureItem = NSMenuItem(title: "Fixture", action: nil, keyEquivalent: "")
        let menu = NSMenu(title: "Fixture")
        menu.addItem(NSMenuItem(title: "Bold", action: #selector(bold), keyEquivalent: "b"))
        menu.addItem(NSMenuItem(title: "Mark", action: #selector(mark), keyEquivalent: ""))
        for item in menu.items { item.target = self }
        fixtureItem.submenu = menu
        main.addItem(fixtureItem)
        NSApp.mainMenu = main
    }

    func controlTextDidChange(_ note: Notification) {
        guard let field = note.object as? NSTextField else { return }
        if field === title { record("title", field.stringValue) }
        if field === password { record("password_typed", field.stringValue.count) }
    }
    func textDidChange(_ note: Notification) { record("notes", notes.string) }

    @objc func saved() { saves += 1; record("save", saves) }
    @objc func deleted() { record("delete") }
    @objc func picked() { record("color", color.titleOfSelectedItem ?? "") }
    @objc func toggled() { record("done", done.state == .on) }
    @objc func sent() {
        guard !chat.stringValue.isEmpty else { return }
        sends += 1
        record("send", chat.stringValue)
        chat.stringValue = ""
    }
    @objc func slowPressed() {
        record("slow_pressed")
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            self.slow.title = "Slow done"
            record("slow_done")
        }
    }
    @objc func sheetPressed(_ sender: NSButton) {
        let delay = Double(sender.tag) / 10
        record("sheet_requested", delay)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            let alert = NSAlert()
            alert.messageText = "Sheet"
            alert.addButton(withTitle: "Submit")
            alert.addButton(withTitle: "Cancel")
            alert.beginSheetModal(for: self.window) { response in
                record("sheet_answer", response == .alertFirstButtonReturn ? "Submit" : "Cancel")
            }
            record("sheet_shown", delay)
        }
    }
    @objc func bold() { record("menu", "Bold") }
    @objc func mark() { record("menu", "Mark") }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

let app = NSApplication.shared
let delegate = Fixture()
app.delegate = delegate
// A regular app, as the apps Hands works in are (it is never activated by the harness).
app.setActivationPolicy(.regular)
app.run()
