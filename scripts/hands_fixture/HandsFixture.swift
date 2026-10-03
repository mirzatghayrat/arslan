// The app the Hands contract check and smoke drive (0.1.53).
//
// A small window with exactly the controls Arslan's eleven agent-desktop
// commands are exercised on: a title field, a password field (which Hands must
// refuse to type into), Save and Delete buttons, a pop-up, and a long scrolling
// list. Every effect is written to the Status label, so a check can observe
// the result instead of trusting the command's own `ok`.
//
// Build: swiftc -O -o HandsFixture HandsFixture.swift (see hands_contract_check.py)
import AppKit

final class Fixture: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    let title = NSTextField(string: "")
    let password = NSSecureTextField(string: "")
    let status = NSTextField(labelWithString: "ready")
    let color = NSPopUpButton(frame: .zero, pullsDown: false)

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 200, y: 200, width: 420, height: 380),
                          styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Hands Fixture"
        // On every Space: agent-desktop sees on-screen windows only, and a check
        // must not fail because the user switched desktops while it ran.
        window.collectionBehavior = [.canJoinAllSpaces]
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.edgeInsets = NSEdgeInsets(top: 12, left: 12, bottom: 12, right: 12)

        title.placeholderString = "Title"
        title.setAccessibilityLabel("Title")
        password.placeholderString = "Password"
        password.setAccessibilityLabel("Password")
        let save = NSButton(title: "Save", target: self, action: #selector(saved))
        let delete = NSButton(title: "Delete", target: self, action: #selector(deleted))
        color.addItems(withTitles: ["Red", "Green", "Blue"])
        color.setAccessibilityLabel("Color")
        color.target = self
        color.action = #selector(picked)
        status.setAccessibilityLabel("Status")

        let rows = NSTextView(frame: NSRect(x: 0, y: 0, width: 380, height: 2000))
        rows.string = (1...80).map { "Row \($0)" }.joined(separator: "\n")
        rows.isEditable = false
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 390, height: 120))
        scroll.documentView = rows
        scroll.hasVerticalScroller = true
        scroll.setAccessibilityLabel("Rows")
        scroll.heightAnchor.constraint(equalToConstant: 120).isActive = true
        scroll.widthAnchor.constraint(equalToConstant: 390).isActive = true

        for view in [title, password, save, delete, color, scroll, status] as [NSView] {
            stack.addArrangedSubview(view)
        }
        title.widthAnchor.constraint(equalToConstant: 300).isActive = true
        password.widthAnchor.constraint(equalToConstant: 300).isActive = true
        window.contentView = stack
        window.orderFrontRegardless()
    }

    @objc func saved() { status.stringValue = "saved:\(title.stringValue)" }
    @objc func deleted() { status.stringValue = "deleted" }
    @objc func picked() { status.stringValue = "color:\(color.titleOfSelectedItem ?? "")" }
    // Stays running with no window, so a check can see WINDOW_NOT_FOUND.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

let app = NSApplication.shared
let delegate = Fixture()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
