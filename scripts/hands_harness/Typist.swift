// The user's stand-in for the Hands engine harness (spec §8.2): a front window with a
// text view the harness types into, as a user would, while an engine acts elsewhere.
//
// Logged to TYPIST_LOG, one JSON line each: every text change (the whole text), and
// every time its window becomes or stops being key — so "the user's key window never
// changed" (oracle O2) and "no key was lost or misdirected" (O5) are read here, from
// the window itself.
//
// Build: swiftc -O -o Typist Typist.swift
import AppKit

let logPath = ProcessInfo.processInfo.environment["TYPIST_LOG"] ?? "/tmp/harness-typist.log"
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

final class Typist: NSObject, NSApplicationDelegate, NSWindowDelegate, NSTextViewDelegate {
    var window: NSWindow!
    let text = NSTextView(frame: NSRect(x: 0, y: 0, width: 380, height: 200))

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 760, y: 200, width: 400, height: 220),
                          styleMask: [.titled], backing: .buffered, defer: false)
        window.title = "Typist"
        window.delegate = self
        text.isRichText = false
        text.delegate = self
        window.contentView = text
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(text)
        NSApp.activate(ignoringOtherApps: true)
        record("ready")
    }

    func textDidChange(_ note: Notification) { record("text", text.string) }
    func windowDidBecomeKey(_ note: Notification) { record("key", true) }
    func windowDidResignKey(_ note: Notification) { record("key", false) }
}

let app = NSApplication.shared
let delegate = Typist()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
