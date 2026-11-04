// Cellar for Mac: a menu bar app with a native window.
// It runs the Cellar server (cellar.py) in the background and shows the UI in a WebKit window.
// Built locally by build-app.sh and signed "ad hoc", so no paid Apple developer account is needed.

import Cocoa
import WebKit
import ServiceManagement

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate, WKUIDelegate, WKNavigationDelegate, NSWindowDelegate {
    private var statusItem: NSStatusItem!
    private var server: Process?
    private var window: NSWindow?
    private var webView: WKWebView?
    private var baseURL: URL?
    private let token = UUID().uuidString.replacingOccurrences(of: "-", with: "")
    private var pollTimer: Timer?
    private var statusLine = "Starting…"
    private var serial: String?
    private var connected = false
    private var lastLog = ""

    // MARK: life cycle

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        setIcon(connected: false)
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
        startServer()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 4, repeats: true) { [weak self] _ in self?.poll() }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        server?.terminate()
    }

    // MARK: server

    private func resourcePath(_ name: String) -> String? {
        Bundle.main.resourceURL?.appendingPathComponent(name).path
    }

    private func pythonPath() -> String {
        for p in ["/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"] where FileManager.default.isExecutableFile(atPath: p) {
            return p
        }
        return "/usr/bin/python3"
    }

    private func startServer() {
        guard let script = resourcePath("cellar.py") else { statusLine = "Cellar files are missing from the app"; return }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: pythonPath())
        p.arguments = ["-u", script]
        var env = ProcessInfo.processInfo.environment
        env["CELLAR_NO_BROWSER"] = "1"
        env["CELLAR_TOKEN"] = token
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        p.environment = env
        let out = Pipe()
        p.standardOutput = out
        p.standardError = out
        out.fileHandleForReading.readabilityHandler = { [weak self] h in
            let data = h.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            DispatchQueue.main.async { self?.handleServerOutput(text) }
        }
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self = self else { return }
                if proc.terminationReason == .exit && proc.terminationStatus != 0 {
                    self.statusLine = "Cellar stopped. Choose Restart to try again."
                    self.baseURL = nil
                    self.setIcon(connected: false)
                }
            }
        }
        do {
            try p.run()
            server = p
        } catch {
            statusLine = "Couldn't start: \(error.localizedDescription)"
        }
    }

    private func handleServerOutput(_ text: String) {
        lastLog = String((lastLog + text).suffix(4000))
        if baseURL == nil, let r = text.range(of: #"http://127\.0\.0\.1:\d+/"#, options: .regularExpression) {
            baseURL = URL(string: String(text[r]))
            statusLine = "Looking for your phone…"
            poll()
            showWindow()
        }
        if text.contains("xcode-select") || text.contains("command line developer tools") {
            statusLine = "macOS needs its free Command Line Tools. Install them, then restart Cellar."
        }
    }

    private func restartServer() {
        server?.terminationHandler = nil
        server?.terminate()
        baseURL = nil
        statusLine = "Restarting…"
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.startServer() }
    }

    // MARK: talking to the server

    private func request(_ path: String, method: String = "GET", query: [String: String] = [:], body: [String: Any]? = nil, done: ((Any?) -> Void)? = nil) {
        guard let base = baseURL, var comps = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false) else { done?(nil); return }
        var q = query
        if let s = serial, q["s"] == nil { q["s"] = s }
        comps.queryItems = q.map { URLQueryItem(name: $0.key, value: $0.value) }
        guard let url = comps.url else { done?(nil); return }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue(token, forHTTPHeaderField: "X-Token")
        if method == "POST" {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = body.flatMap { try? JSONSerialization.data(withJSONObject: $0) } ?? "{}".data(using: .utf8)
        }
        req.timeoutInterval = 30
        URLSession.shared.dataTask(with: req) { data, _, _ in
            let obj = data.flatMap { try? JSONSerialization.jsonObject(with: $0) }
            DispatchQueue.main.async { done?(obj) }
        }.resume()
    }

    private func poll() {
        guard baseURL != nil else { return }
        request("api/devices") { [weak self] obj in
            guard let self = self, let d = obj as? [String: Any] else { return }
            if (d["adb"] as? Bool) == false {
                self.statusLine = "Android tools needed. Open Cellar to install them."
                self.connected = false; self.serial = nil; self.setIcon(connected: false); return
            }
            let devices = (d["devices"] as? [[String: Any]]) ?? []
            let usable = devices.filter { ($0["state"] as? String) == "device" }
            if let first = usable.first {
                self.serial = first["serial"] as? String
                self.connected = true
                let how = (first["transport"] as? String) == "wifi" ? "Wi-Fi" : "USB"
                let model = (first["model"] as? String) ?? "Phone"
                self.statusLine = "\(model) · \(how)"
                self.request("api/info") { info in
                    guard let i = info as? [String: Any] else { return }
                    let name = "\((i["manufacturer"] as? String) ?? "") \((i["model"] as? String) ?? "")".trimmingCharacters(in: .whitespaces)
                    var parts = [name.isEmpty ? model : name]
                    if let b = i["battery"] as? Int { parts.append("\(b)% battery") }
                    parts.append(how)
                    self.statusLine = parts.joined(separator: " · ")
                }
            } else if devices.contains(where: { ($0["state"] as? String) == "unauthorized" }) {
                self.connected = false; self.serial = nil
                self.statusLine = "Tap Allow on your phone"
            } else {
                self.connected = false; self.serial = nil
                self.statusLine = "No phone connected"
            }
            self.setIcon(connected: self.connected)
        }
    }

    private func setIcon(connected: Bool) {
        guard let button = statusItem.button else { return }
        let names = connected ? ["candybarphone", "iphone"] : ["iphone.slash", "iphone"]
        for n in names {
            if let img = NSImage(systemSymbolName: n, accessibilityDescription: connected ? "Cellar: phone connected" : "Cellar: no phone") {
                img.isTemplate = true
                button.image = img
                break
            }
        }
        button.toolTip = "Cellar: " + statusLine
    }

    // MARK: menu

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let head = NSMenuItem(title: statusLine, action: nil, keyEquivalent: "")
        head.isEnabled = false
        menu.addItem(head)
        menu.addItem(.separator())
        menu.addItem(item("Open Cellar", #selector(openWindow), "o"))
        let finder = item("Show Phone in Finder", #selector(showInFinder), "")
        finder.isEnabled = connected
        menu.addItem(finder)
        let backup = item("Back Up Photos Now", #selector(backupNow), "")
        backup.isEnabled = connected
        menu.addItem(backup)
        let mirror = item("Mirror Phone Screen", #selector(mirrorScreen), "")
        mirror.isEnabled = connected
        menu.addItem(mirror)
        let shot = item("Take Screenshot", #selector(takeScreenshot), "")
        shot.isEnabled = connected
        menu.addItem(shot)
        let controls = NSMenuItem(title: "Phone Controls", action: nil, keyEquivalent: "")
        let sub = NSMenu(title: "Phone Controls")
        for (title, sel) in [("Ring My Phone", #selector(ringPhone)), ("Play / Pause", #selector(mediaPlayPause)), ("Next Track", #selector(mediaNext)),
                             ("Previous Track", #selector(mediaPrevious)), ("Do Not Disturb On", #selector(dndOn)), ("Do Not Disturb Off", #selector(dndOff))] {
            let i = item(title, sel, "")
            i.isEnabled = connected
            sub.addItem(i)
        }
        controls.submenu = sub
        controls.isEnabled = connected
        menu.addItem(controls)
        menu.addItem(.separator())
        menu.addItem(item("Open Downloads/Cellar", #selector(openSaveFolder), ""))
        if #available(macOS 13.0, *) {
            let login = item("Open at Login", #selector(toggleLogin), "")
            login.state = SMAppService.mainApp.status == .enabled ? .on : .off
            menu.addItem(login)
        }
        menu.addItem(item("Restart Cellar", #selector(restart), ""))
        menu.addItem(.separator())
        menu.addItem(item("Quit Cellar", #selector(quit), "q"))
    }

    private func item(_ title: String, _ sel: Selector, _ key: String) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        i.target = self
        return i
    }

    @objc private func openWindow() { showWindow() }
    @objc private func restart() { restartServer() }
    @objc private func quit() { NSApp.terminate(nil) }

    @objc private func showInFinder() {
        request("api/finder/mount", method: "POST") { obj in
            if let d = obj as? [String: Any], let err = d["error"] as? String { self.alert("Couldn't show the phone in Finder", err) }
        }
    }

    @objc private func backupNow() {
        request("api/backup/run", method: "POST") { obj in
            guard let d = obj as? [String: Any] else { return }
            if d["nothing"] != nil { self.notify("Everything is already backed up") }
            else if let err = d["error"] as? String { self.alert("Backup didn't start", err) }
            else { self.notify("Backing up new photos…") }
        }
    }

    @objc private func mirrorScreen() {
        request("api/mirror", method: "POST") { obj in
            if let d = obj as? [String: Any], let err = d["error"] as? String {
                if err == "need_scrcpy" { self.showWindow(); self.webView?.evaluateJavaScript("document.getElementById('mirrorBtn').click()") }
                else { self.alert("Mirroring didn't start", err) }
            }
        }
    }

    // Phone controls. Not every phone supports every one, so failures are explained rather than ignored.
    private func phoneControl(_ path: String, body: [String: Any]? = nil, done: String? = nil, failTitle: String) {
        request(path, method: "POST", body: body) { obj in
            if let d = obj as? [String: Any], let err = d["error"] as? String { self.alert(failTitle, err) }
            else if let done = done { self.notify(done) }
        }
    }
    @objc private func ringPhone() { phoneControl("api/ring", done: "Ringing in about a minute. Dismiss the alarm on the phone.", failTitle: "Couldn't ring the phone") }
    @objc private func mediaPlayPause() { phoneControl("api/media", body: ["key": "playpause"], failTitle: "Couldn't control the music") }
    @objc private func mediaNext() { phoneControl("api/media", body: ["key": "next"], failTitle: "Couldn't control the music") }
    @objc private func mediaPrevious() { phoneControl("api/media", body: ["key": "previous"], failTitle: "Couldn't control the music") }
    @objc private func dndOn() { phoneControl("api/dnd", body: ["mode": "priority"], done: "Do Not Disturb is on", failTitle: "Couldn't change Do Not Disturb") }
    @objc private func dndOff() { phoneControl("api/dnd", body: ["mode": "off"], done: "Do Not Disturb is off", failTitle: "Couldn't change Do Not Disturb") }

    @objc private func takeScreenshot() {
        showWindow()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { self.webView?.evaluateJavaScript("document.getElementById('shotBtn').click()") }
    }

    @objc private func openSaveFolder() {
        let url = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Downloads/Cellar")
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        NSWorkspace.shared.open(url)
    }

    @objc private func toggleLogin() {
        guard #available(macOS 13.0, *) else { return }
        do {
            if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister() }
            else { try SMAppService.mainApp.register() }
        } catch {
            alert("Couldn't change Open at Login", "Add Cellar yourself in System Settings › General › Login Items. (\(error.localizedDescription))")
        }
    }

    private func notify(_ text: String) {
        let script = "display notification \"\(text.replacingOccurrences(of: "\"", with: "'"))\" with title \"Cellar\""
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        p.arguments = ["-e", script]
        try? p.run()
    }

    private func alert(_ title: String, _ text: String) {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = title
        a.informativeText = text
        a.runModal()
    }

    // MARK: window

    private func showWindow() {
        guard let base = baseURL else {
            alert("Cellar is still starting", statusLine + (lastLog.isEmpty ? "" : "\n\n" + String(lastLog.suffix(600))))
            return
        }
        NSApp.setActivationPolicy(.regular)
        if window == nil {
            let config = WKWebViewConfiguration()
            config.preferences.setValue(true, forKey: "developerExtrasEnabled")
            let wv = WKWebView(frame: .zero, configuration: config)
            wv.uiDelegate = self
            wv.navigationDelegate = self
            wv.setValue(false, forKey: "drawsBackground")
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1240, height: 800),
                             styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                             backing: .buffered, defer: false)
            w.title = "Cellar"
            w.titlebarAppearsTransparent = false
            w.minSize = NSSize(width: 720, height: 480)
            w.contentView = wv
            w.center()
            w.setFrameAutosaveName("CellarMain")
            w.isReleasedWhenClosed = false
            w.delegate = self
            window = w
            webView = wv
            wv.load(URLRequest(url: base))
        } else if webView?.url == nil || webView?.url?.host != base.host || webView?.url?.port != base.port {
            webView?.load(URLRequest(url: base))
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ notification: Notification) {
        // Keep running in the menu bar; drop the Dock icon until the window is opened again.
        NSApp.setActivationPolicy(.accessory)
    }

    // File pickers (<input type="file">) need a native open panel in WebKit.
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = !parameters.allowsDirectories
        panel.prompt = parameters.allowsDirectories ? "Copy Folder to Phone" : "Copy to Phone"
        panel.beginSheetModal(for: window!) { resp in completionHandler(resp == .OK ? panel.urls : nil) }
    }

    // Links to other sites open in the default browser.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, let base = baseURL, url.host != base.host || url.port != base.port, action.navigationType == .linkActivated {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }
}

// Standard Edit menu so ⌘C / ⌘X / ⌘V / ⌘A / ⌘Z reach the page.
func buildMainMenu() {
    let main = NSMenu()
    let appItem = NSMenuItem()
    main.addItem(appItem)
    let appMenu = NSMenu()
    appMenu.addItem(withTitle: "Hide Cellar", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
    appMenu.addItem(.separator())
    appMenu.addItem(withTitle: "Quit Cellar", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
    appItem.submenu = appMenu
    let editItem = NSMenuItem()
    main.addItem(editItem)
    let edit = NSMenu(title: "Edit")
    // Undo (⌘Z) and Select All (⌘A) are left to the page, which handles them as Cellar actions.
    edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
    edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
    edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
    editItem.submenu = edit
    let winItem = NSMenuItem()
    main.addItem(winItem)
    let win = NSMenu(title: "Window")
    win.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
    win.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
    winItem.submenu = win
    NSApp.mainMenu = main
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
buildMainMenu()
app.run()
