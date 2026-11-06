// Cellar for Mac: a menu bar app with a native window.
// It runs the Cellar server (cellar.py) in the background and shows the UI in a WebKit window.
// Built locally by build-app.sh and signed "ad hoc", so no paid Apple developer account is needed.

import Cocoa
import WebKit
import ServiceManagement
import Network

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
    private var lanBrowser: NWBrowser?

    // MARK: life cycle

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        setIcon(connected: false)
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
        requestLocalNetwork()
        startServer()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 4, repeats: true) { [weak self] _ in self?.poll() }
    }

    /// Unmounts this server's Finder mounts ("http://127.0.0.1:<port>/dav/… on /Volumes/…").
    private func unmountFinder(port: Int) {
        let list = Process()
        list.executableURL = URL(fileURLWithPath: "/sbin/mount")
        let out = Pipe()
        list.standardOutput = out
        guard (try? list.run()) != nil else { return }
        list.waitUntilExit()
        let text = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        for line in text.split(separator: "\n") where line.hasPrefix("http://127.0.0.1:\(port)/dav/") {
            guard let on = line.range(of: " on "), let paren = line.range(of: " (webdav", range: on.upperBound..<line.endIndex) else { continue }
            let mp = String(line[on.upperBound..<paren.lowerBound])
            let u = Process()
            u.executableURL = URL(fileURLWithPath: "/usr/sbin/diskutil")
            u.arguments = ["unmount", "force", mp]
            u.standardOutput = FileHandle.nullDevice
            u.standardError = FileHandle.nullDevice
            guard (try? u.run()) != nil else { continue }
            let deadline = Date().addingTimeInterval(10)   // about 3 s when a Finder window shows the phone
            while u.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.1) }
            if u.isRunning { u.terminate() }
        }
    }

    /// macOS only lets an app reach devices on the Wi-Fi once the person allows "Local Network" for it,
    /// and adb (started by this app) inherits that. Without it, Go wireless fails with "No route to host".
    /// Browsing for phones with Wireless debugging on makes macOS ask, in Cellar's name, at launch.
    private func requestLocalNetwork() {
        let b = NWBrowser(for: .bonjour(type: "_adb-tls-connect._tcp", domain: nil), using: .tcp)
        b.stateUpdateHandler = { _ in }
        b.start(queue: .main)
        lanBrowser = b
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in self?.lanBrowser?.cancel(); self?.lanBrowser = nil }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        // Unmount the phone from Finder while the server can still answer: a mount whose server is
        // gone makes Finder hang. Then stop the server and wait for it, so opening Cellar again right
        // away finds port 8765 free instead of moving to another port.
        guard let s = server else { return }
        if let port = baseURL?.port { unmountFinder(port: port) }
        s.terminate()
        let deadline = Date().addingTimeInterval(8)
        while s.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.1) }
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
        env["CELLAR_PARENT_PID"] = String(getpid())   // the server exits by itself if this app is killed
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
            // Liquid Glass: a transparent title bar over a glass window background. The page leaves its
            // sidebar see-through (Settings › Liquid Glass), so the desktop shows through it.
            w.titlebarAppearsTransparent = true
            w.titleVisibility = .hidden
            w.minSize = NSSize(width: 860, height: 480)
            let glass = makeGlassBackground()
            wv.translatesAutoresizingMaskIntoConstraints = false
            let drag = DragStrip()
            drag.translatesAutoresizingMaskIntoConstraints = false
            glass.addSubview(wv)
            glass.addSubview(drag)
            NSLayoutConstraint.activate([
                wv.leadingAnchor.constraint(equalTo: glass.leadingAnchor), wv.trailingAnchor.constraint(equalTo: glass.trailingAnchor),
                wv.topAnchor.constraint(equalTo: glass.topAnchor), wv.bottomAnchor.constraint(equalTo: glass.bottomAnchor),
                // The page keeps the top of its sidebar empty for the traffic lights; this strip makes it drag the window.
                drag.leadingAnchor.constraint(equalTo: glass.leadingAnchor), drag.topAnchor.constraint(equalTo: glass.topAnchor),
                drag.widthAnchor.constraint(equalToConstant: 248), drag.heightAnchor.constraint(equalToConstant: 40),
            ])
            w.contentView = glass
            w.center()
            w.setFrameAutosaveName("CellarMain")
            w.isReleasedWhenClosed = false
            w.delegate = self
            window = w
            webView = wv
            wv.load(URLRequest(url: appURL(base)))
        } else if webView?.url == nil || webView?.url?.host != base.host || webView?.url?.port != base.port {
            webView?.load(URLRequest(url: appURL(base)))
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// "?app=1" tells the page it runs inside this window: it reserves room for the traffic lights and
    /// lets the glass background show through its sidebar.
    private func appURL(_ base: URL) -> URL {
        var c = URLComponents(url: base, resolvingAgainstBaseURL: false)
        c?.queryItems = [URLQueryItem(name: "app", value: "1")]
        return c?.url ?? base
    }

    /// Liquid Glass on macOS 26 and later; the frosted sidebar material on older versions.
    private func makeGlassBackground() -> NSView {
        if #available(macOS 26.0, *) {
            let g = NSGlassEffectView()
            g.cornerRadius = 0
            return GlassHost(background: g)
        }
        let v = NSVisualEffectView()
        v.material = .sidebar
        v.blendingMode = .behindWindow
        v.state = .followsWindowActiveState
        return v
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

/// Holds a full-size background view (the window's glass) with the page and the drag strip on top of it.
final class GlassHost: NSView {
    init(background: NSView) {
        super.init(frame: .zero)
        background.translatesAutoresizingMaskIntoConstraints = false
        addSubview(background)
        NSLayoutConstraint.activate([
            background.leadingAnchor.constraint(equalTo: leadingAnchor), background.trailingAnchor.constraint(equalTo: trailingAnchor),
            background.topAnchor.constraint(equalTo: topAnchor), background.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }
}

/// An invisible strip over the top of the sidebar: drags the window, and a double-click zooms it,
/// as a title bar would. The web view under it would otherwise swallow those clicks.
final class DragStrip: NSView {
    override var mouseDownCanMoveWindow: Bool { true }
    override func mouseDown(with event: NSEvent) {
        if event.clickCount == 2 { window?.performZoom(nil) } else { window?.performDrag(with: event) }
    }
}
