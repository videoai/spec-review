import AppKit
import WebKit

final class App: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var web: WKWebView!
    var backend: Process?
    var origin: URL?
    var output = Data()
    func applicationDidFinishLaunching(_ notification: Notification) {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.userContentController.add(self, name: "desktop")
        config.userContentController.addUserScript(WKUserScript(source: "window.print=()=>window.webkit.messageHandlers.desktop.postMessage({action:'print'});", injectionTime: .atDocumentEnd, forMainFrameOnly: true))
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self; web.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 900), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "ONVIF Spec Review"; window.minSize = NSSize(width: 820, height: 600)
        window.contentView = web; window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        menus()
        web.loadHTMLString("<body style='font:20px system-ui;padding:70px;color:#164536'><h1>ONVIF Spec Review</h1><p>Opening your review workspace…</p><p>The first launch may take a moment to download the specifications.</p></body>", baseURL: nil)
        start()
    }
    func menus() {
        let bar = NSMenu(); NSApp.mainMenu = bar
        let appItem = NSMenuItem(); bar.addItem(appItem); let app = NSMenu(); appItem.submenu = app
        app.addItem(withTitle: "About ONVIF Spec Review", action: #selector(about), keyEquivalent: "")
        app.addItem(.separator()); app.addItem(withTitle: "Quit ONVIF Spec Review", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem=NSMenuItem();bar.addItem(editItem);let edit=NSMenu(title:"Edit");editItem.submenu=edit
        for (title, selector, key) in [("Undo", "undo:", "z"),("Cut", "cut:", "x"),("Copy", "copy:", "c"),("Paste", "paste:", "v"),("Select All", "selectAll:", "a")] {edit.addItem(withTitle:title,action:Selector(selector),keyEquivalent:key)}
        let reviewItem=NSMenuItem();bar.addItem(reviewItem);let review=NSMenu(title:"Review");reviewItem.submenu=review
        for (title,id,key) in [("Notes","noteHistory","n"),("Finish Review…","previewReview","u"),("Resume Review","resumeReview","r"),("Export…","exportDialog",""),("Backup & Restore…","reviewDataDialog","")] {
            let item=NSMenuItem(title:title,action:#selector(reviewAction(_:)),keyEquivalent:key);item.representedObject=id;item.target=self;review.addItem(item)
        }
    }
    @objc func about(){NSApp.orderFrontStandardAboutPanel(options:[.applicationName:"ONVIF Spec Review",.applicationVersion:"0.1 Mac prototype",.credits:NSAttributedString(string:"Review ONVIF specifications with local notes and GitHub feedback.")])}
    @objc func reviewAction(_ item:NSMenuItem){guard let id=item.representedObject as? String else{return};web.evaluateJavaScript("(()=>{const e=document.getElementById('\(id)');if(e?.tagName==='DIALOG')e.showModal();else e?.click();})()",completionHandler:nil)}
    func start() {
        let resources=Bundle.main.resourceURL!
        let process=Process();backend=process;process.executableURL=resources.appendingPathComponent("backend/spec-review-service")
        var env=ProcessInfo.processInfo.environment
        env["PATH"]=resources.appendingPathComponent("tools").path+":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env["GIT_EXEC_PATH"]=resources.appendingPathComponent("tools/git-core").path
        env["GIT_TEMPLATE_DIR"]=resources.appendingPathComponent("templates").path
        env["XML_REVIEW_GITHUB_REPO"]=UserDefaults.standard.string(forKey:"reviewRepository") ?? "onvif/specs"
        process.environment=env
        let pipe=Pipe();process.standardOutput=pipe
        let folder=FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/ONVIF Spec Review")
        try? FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
        let logfile=folder.appendingPathComponent("backend.log");FileManager.default.createFile(atPath:logfile.path,contents:nil)
        process.standardError=try? FileHandle(forWritingTo:logfile)
        pipe.fileHandleForReading.readabilityHandler={ [weak self] handle in
            let data=handle.availableData;guard !data.isEmpty else{return}
            DispatchQueue.main.async {self?.received(data)}
        }
        process.terminationHandler={ [weak self] task in DispatchQueue.main.async {if NSApp.isRunning && task.terminationStatus != 0 {self?.fail("The local service stopped. See ~/Library/Logs/ONVIF Spec Review/backend.log for details.")}} }
        do{try process.run()}catch{fail(error.localizedDescription)}
    }
    func received(_ data:Data){
        output.append(data)
        while let end=output.firstIndex(of:10) {
            let line=String(data:output.prefix(upTo:end),encoding:.utf8) ?? "";output.removeSubrange(...end)
            if line.hasPrefix("SPEC_REVIEW_STATUS "),let json=line.dropFirst(19).data(using:.utf8),let value=try? JSONSerialization.jsonObject(with:json) as? [String:String],let message=value["message"],let data=try? JSONSerialization.data(withJSONObject:message,options:.fragmentsAllowed),let literal=String(data:data,encoding:.utf8) {web.evaluateJavaScript("document.querySelector('p')?.replaceChildren("+literal+")",completionHandler:nil)}
            if line.hasPrefix("SPEC_REVIEW_READY "),let json=line.dropFirst(18).data(using:.utf8),let value=try? JSONSerialization.jsonObject(with:json) as? [String:String],let raw=value["url"],let url=URL(string:raw) {origin=url;web.load(URLRequest(url:url))}
        }
    }
    func fail(_ message:String){let alert=NSAlert();alert.messageText="Could not open ONVIF Spec Review";alert.informativeText=message;alert.runModal()}
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool{true}
    func applicationWillTerminate(_ notification:Notification){backend?.terminate()}
    func local(_ url:URL)->Bool{url.host=="127.0.0.1" && url.port==origin?.port && url.scheme=="http"}
    func webView(_ webView:WKWebView,decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void){
        guard let url=action.request.url else{decisionHandler(.cancel);return}
        if url.scheme=="about" || local(url){decisionHandler(.allow)}else{if ["https","http"].contains(url.scheme ?? ""){NSWorkspace.shared.open(url)};decisionHandler(.cancel)}
    }
    func webView(_ webView:WKWebView,createWebViewWith configuration:WKWebViewConfiguration,for action:WKNavigationAction,windowFeatures:WKWindowFeatures)->WKWebView? {
        if let url=action.request.url {if local(url){web.load(action.request)}else if url.scheme=="https" {NSWorkspace.shared.open(url)}};return nil
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel=NSOpenPanel();panel.allowsMultipleSelection=false;panel.canChooseDirectories=false
        panel.beginSheetModal(for:window){result in completionHandler(result == .OK ? panel.urls : nil)}
    }
    func userContentController(_ controller:WKUserContentController,didReceive message:WKScriptMessage){
        guard message.frameInfo.isMainFrame,let url=message.frameInfo.request.url,local(url),let data=message.body as? [String:String],let action=data["action"] else{return}
        if action=="repository",let repository=data["text"],["onvif/specs","videoai/test-specs"].contains(repository) {
            UserDefaults.standard.set(repository,forKey:"reviewRepository")
            let previous=backend;previous?.terminationHandler=nil;previous?.terminate()
            web.loadHTMLString("<body style='font:20px system-ui;padding:60px;color:#164536'><h1>Opening repository…</h1></body>",baseURL:nil)
            DispatchQueue.global().async {previous?.waitUntilExit();DispatchQueue.main.async {self.output.removeAll();self.origin=nil;self.start()}}
            return
        }
        if action=="print"{let info=NSPrintInfo();info.paperSize=NSSize(width:595.28,height:841.89);info.orientation = .landscape;info.horizontalPagination = .fit;info.topMargin=20;info.bottomMargin=20;info.leftMargin=20;info.rightMargin=20;web.printOperation(with:info).run()}
        if action=="copy",let text=data["text"]{NSPasteboard.general.clearContents();NSPasteboard.general.setString(text,forType:.string)}
        if action=="save",let text=data["text"],let name=data["name"]{let panel=NSSavePanel();panel.nameFieldStringValue=URL(fileURLWithPath:name).lastPathComponent;panel.beginSheetModal(for:window){response in if response == .OK,let url=panel.url {do{try text.write(to:url,atomically:true,encoding:.utf8)}catch{self.fail(error.localizedDescription)}}}}
    }
}
let delegate=App()
let app=NSApplication.shared
app.setActivationPolicy(.regular)
app.delegate=delegate
app.run()
