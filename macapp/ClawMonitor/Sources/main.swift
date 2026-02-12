import AppKit
import SwiftUI

// Minimal native menu bar app MVP (no .app bundle yet):
// - Creates a status bar item
// - Opens a SwiftUI popover

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var popover: NSPopover!

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.title = "🦞"
            button.action = #selector(togglePopover(_:))
            button.target = self
        }

        popover = NSPopover()
        popover.behavior = .transient
        popover.contentSize = NSSize(width: 360, height: 220)
        popover.contentViewController = NSHostingController(rootView: ContentView())
    }

    @objc private func togglePopover(_ sender: Any?) {
        guard let button = statusItem.button else { return }
        if popover.isShown {
            popover.performClose(sender)
        } else {
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            NSApp.activate(ignoringOtherApps: true)
        }
    }
}

struct ContentView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Claw Monitor")
                .font(.headline)
            Text("MVP: collector running; UI wiring next")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            Divider()

            HStack {
                VStack(alignment: .leading) {
                    Text("Token/s")
                    Text("—")
                        .font(.title2)
                        .monospaced()
                }
                Spacer()
                VStack(alignment: .leading) {
                    Text("Context")
                    Text("—")
                        .font(.title2)
                        .monospaced()
                }
            }

            Spacer()

            HStack {
                Button("Dashboard") {
                    // TODO
                }
                Spacer()
                Button("Quit") {
                    NSApp.terminate(nil)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.setActivationPolicy(.accessory)
app.delegate = delegate
app.run()
