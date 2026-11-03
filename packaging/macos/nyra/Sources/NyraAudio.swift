import AppKit
import AVFoundation
import UniformTypeIdentifiers
import CryptoKit

final class NyraAudio: NSObject, AVSpeechSynthesizerDelegate, AVAudioPlayerDelegate {
    let speech = AVSpeechSynthesizer()
    private var player: AVAudioPlayer?
    private var effect: AVAudioPlayer?
    private var activeUtterance: AVSpeechUtterance?
    private var gate = ActionVoiceGate()
    var changed: (() -> Void)?
    var isMuted = true { didSet { if isMuted { stop() } } }
    var automatic = true { didSet { if !automatic { stop() } } }
    var volume: Float = 0.45 { didSet { player?.volume = volume; effect?.volume = volume*0.5; if volume <= 0 { stop() } } }
    var language = "auto"
    var voiceIDs: [String:String] = [:]
    var customDirectory: URL?
    var legacyDirectory: URL?
    var bundledVoiceRoot = Bundle.main.resourceURL?.appendingPathComponent("audio/tian-1413-zh")
    var usesBundledVoice: Bool { resolvedLanguage == "zh" && (voiceIDs["zh"] ?? "").isEmpty }
    func bundledData(_ cue: VoiceCue) throws -> Data {
        guard let root = bundledVoiceRoot else { throw PreviewError.invalidManifest }
        return try BundledVoicePack.read(root).data(cue,root:root)
    }
    private(set) var lastResult = "尚未播放 / Not played"
    private(set) var lastCue = ""
    private(set) var lastOrigin = ""
    private(set) var playbackCount = 0
    private(set) var speechStartCount = 0
    override init() { super.init(); speech.delegate = self }
    var resolvedLanguage: String { Self.resolveLanguage(language, preferred: Locale.preferredLanguages) }
    static func resolveLanguage(_ choice: String, preferred: [String]) -> String {
        choice == "auto" ? ((preferred.first ?? "en").hasPrefix("zh") ? "zh" : "en") : choice
    }
    // Enumerate only voices the running app can actually use. The command-line
    // process may expose a different list. No implicit download or cloud synthesis.
    var voices: [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices().filter { $0.language.hasPrefix(resolvedLanguage) && $0.gender == .female }
            .sorted {
                if $0.quality != $1.quality { return $0.quality.rawValue > $1.quality.rawValue }
                if resolvedLanguage == "zh", $0.identifier.contains("Meijia") != $1.identifier.contains("Meijia") { return $0.identifier.contains("Meijia") }
                let preferred = resolvedLanguage == "zh" ? "zh-CN" : "en-US"
                if ($0.language == preferred) != ($1.language == preferred) { return $0.language == preferred }
                if $0.identifier.contains("super-compact") != $1.identifier.contains("super-compact") { return !$0.identifier.contains("super-compact") }
                return $0.identifier < $1.identifier
            }
    }
    var voice: AVSpeechSynthesisVoice? {
        if let id = voiceIDs[resolvedLanguage], !id.isEmpty { return voices.first { $0.identifier == id } }
        return voices.first
    }
    func customCandidates(_ cue: VoiceCue) -> [URL] {
        guard let root = customDirectory else { return [] }
        var paths = [root.appendingPathComponent("voice-\(resolvedLanguage)-\(cue.rawValue).audio")]
        // Previous generic imports remain greeting-only, never action-wide.
        if cue == .welcome {
            paths.append(root.appendingPathComponent("voice-\(resolvedLanguage).audio"))
            if let old = legacyDirectory, old != root { paths.append(old.appendingPathComponent("voice-\(resolvedLanguage).audio")) }
        }
        return paths
    }
    func customFile(_ cue: VoiceCue) -> URL? {
        customCandidates(cue).first { FileManager.default.fileExists(atPath:$0.path) }
    }
    func importCue(_ cue: VoiceCue, from url: URL) throws {
        guard let root = customDirectory else { throw PreviewError.invalidManifest }
        // Bounded read; validate the exact bytes that will be saved, not a second
        // read of a selected file that may have changed during decoding.
        let reader = try FileHandle(forReadingFrom:url); defer { try? reader.close() }
        let limit = 25*1024*1024
        let data = try reader.read(upToCount:limit) ?? Data()
        guard !data.isEmpty, data.count < limit else { throw PreviewError.invalidManifest }
        let decoded = try AVAudioPlayer(data:data)
        guard decoded.duration.isFinite, decoded.duration > 0, decoded.duration <= 120 else { throw PreviewError.invalidManifest }
        let destination = root.appendingPathComponent("voice-\(resolvedLanguage)-\(cue.rawValue).audio")
        try data.write(to:destination,options:.atomic)
        stop(); lastResult = "此动作音频已保存 / Action audio saved"; changed?()
    }
    func resetCue(_ cue: VoiceCue) throws {
        stop()
        for url in customCandidates(cue) where FileManager.default.fileExists(atPath:url.path) { try FileManager.default.removeItem(at:url) }
        lastResult = "已移除此动作自定义音频 / Custom cue removed"; changed?()
    }
    var sourceLabel: String {
        if usesBundledVoice {
            guard let root = bundledVoiceRoot, (try? BundledVoicePack.read(root)) != nil else {
                return "小田资源不可用；请检查安装包 / Tian recordings unavailable"
            }
            return "小田 / Tian · 中文 · 内置离线短句 / Bundled offline cues"
        }
        guard let voice = voice else { return "所选女声未安装；请选择可用声线 / Selected voice unavailable" }
        return "本机女声 / Local female voice · \(voice.name) · \(voice.language)" + (voice.quality.rawValue > 1 ? " · 高质量 / Enhanced" : "")
    }
    var isPlaying: Bool { activeUtterance != nil || speech.isSpeaking || player?.isPlaying == true || effect?.isPlaying == true }
    var snapshot: [String: Any] {
        ["muted":isMuted,"automatic":automatic,"volume":volume,"language":language,"resolved_language":resolvedLanguage,
         "voice_identifier":usesBundledVoice ? "ttsmaker:1413:default" : (voice?.identifier ?? ""),"source":sourceLabel,"result":lastResult,"speaking":speech.isSpeaking,
         "audio_playing":player?.isPlaying == true || effect?.isPlaying == true,"cue":lastCue,"origin":lastOrigin,
         "playback_count":playbackCount,"speech_start_count":speechStartCount,"custom_exclusive_voice_produced":false,"bundled_voice_selected":usesBundledVoice]
    }
    func stop() { activeUtterance=nil; speech.stopSpeaking(at:.immediate); player?.stop(); effect?.stop(); lastResult = "已停止 / Stopped" }
    func chime(_ kind: String) {
        guard !isMuted, volume > 0, !isPlaying,
              let url = Bundle.main.resourceURL?.appendingPathComponent("audio/\(kind).wav") else { return }
        do { effect = try AVAudioPlayer(contentsOf:url); effect?.volume = volume*0.5; effect?.play() }
        catch { lastResult = "提示音无法加载 / Cue unavailable" }
    }
    func react(_ cue: VoiceCue, event: String, visible: Bool, origin: String = "action") {
        guard gate.allow(cue,event:event,now:ProcessInfo.processInfo.systemUptime,
                         enabled:automatic && !isMuted && volume > 0,visible:visible,busy:isPlaying) else { return }
        speak(cue, origin:origin)
    }
    func speak(_ cue: VoiceCue = .welcome, origin: String = "preview") {
        guard !isMuted, volume > 0 else { lastResult = "已静音；取消静音后可试听 / Unmute to listen"; changed?(); return }
        stop(); lastCue = cue.rawValue; lastOrigin = origin
        if let url = customFile(cue) {
            do {
                player = try AVAudioPlayer(contentsOf:url); player?.volume = volume; player?.delegate = self
                if player?.play() == true { playbackCount += 1; lastResult = "正在播放导入短句 / Playing imported cue" }
                else { lastResult = "导入短句播放失败 / Imported cue failed" }
            } catch { lastResult = "导入短句不可读取；未改播其他音频 / Imported cue unreadable" }
        } else if usesBundledVoice {
            do {
                let data = try bundledData(cue)
                player = try AVAudioPlayer(data:data)
                guard let player = player, player.duration.isFinite, player.duration > 0, player.duration <= 120 else { throw PreviewError.invalidManifest }
                player.volume = volume; player.delegate = self
                if player.play() { playbackCount += 1; lastResult = "正在播放小田 / Playing Tian" }
                else { lastResult = "小田短句播放失败 / Tian playback failed" }
            } catch { lastResult = "小田短句缺失或损坏；未改播其他声线 / Tian cue missing or damaged" }
        } else if let voice = voice {
            let words = AVSpeechUtterance(string:cue.phrase(resolvedLanguage))
            words.voice = voice; words.volume = volume
            words.rate = resolvedLanguage == "zh" ? 0.48 : 0.46
            words.pitchMultiplier = cue == .success ? 1.12 : 1.06
            activeUtterance=words; speech.speak(words); lastResult = "等待本机语音播放 / Queued local speech"
        } else { lastResult = "当前语言缺少可用女声 / No installed female voice" }
        changed?()
    }
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance) {
        guard activeUtterance === utterance else { return }
        playbackCount += 1; speechStartCount += 1; lastResult = "正在播放本机女声 / Speaking locally"; changed?()
    }
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        guard activeUtterance === utterance else { return }; activeUtterance=nil
        lastResult = "播放结束 / Playback ended"; changed?()
    }
    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        guard self.player === player else { return }
        lastResult = flag ? "播放结束 / Playback ended" : "播放失败 / Playback failed"; changed?()
    }
}

final class VoicePanelView: NSView {
    var close: (() -> Void)?
    override var acceptsFirstResponder: Bool { true }
    override func cancelOperation(_ sender: Any?) { close?() }
}

final class AudioSettingsController: NSViewController {
    let audio: NyraAudio
    var changed: (() -> Void)?
    var importAudio: ((VoiceCue) -> Void)?
    var resetAudio: ((VoiceCue) -> Void)?
    var close: (() -> Void)?
    let info = text("",size:11,color:.secondaryLabelColor)
    let result = text("",size:11,color:.secondaryLabelColor)
    var muted: NSButton!
    var reactions: NSButton!
    var voiceChoice: NSPopUpButton!
    var cueChoice: NSPopUpButton!
    var selectedCue: VoiceCue { VoiceCue.allCases[max(0,cueChoice.indexOfSelectedItem)] }
    init(audio: NyraAudio) { self.audio = audio; super.init(nibName:nil,bundle:nil) }
    required init?(coder: NSCoder) { fatalError() }
    override func loadView() {
        let root = VoicePanelView(frame:NSRect(x:0,y:0,width:410,height:480)); view = root
        root.close = { [weak self] in self?.close?() }
        view.appearance = NSAppearance(named:.darkAqua)
        view.wantsLayer = true
        view.layer?.backgroundColor = ink.cgColor
        let heading = text("夜璃的声音 / Voice",size:18,color:.labelColor)
        heading.frame = NSRect(x:20,y:438,width:270,height:26); view.addSubview(heading)
        let dismiss = button("关闭 / Close",self,#selector(closePanel),hint:"关闭声音面板 / Close voice panel")
        dismiss.keyEquivalent = "\u{1b}"; dismiss.frame = NSRect(x:300,y:436,width:90,height:30); view.addSubview(dismiss)
        let language = NSSegmentedControl(labels:["跟随系统","中文","English"],trackingMode:.selectOne,target:self,action:#selector(changeLanguage))
        language.selectedSegment = ["auto","zh","en"].firstIndex(of:audio.language) ?? 0
        language.setAccessibilityLabel("语音语言 / Voice language"); language.frame = NSRect(x:20,y:396,width:370,height:30); view.addSubview(language)
        voiceChoice = NSPopUpButton(frame:NSRect(x:20,y:360,width:370,height:28)); voiceChoice.target = self; voiceChoice.action = #selector(changeVoice)
        voiceChoice.setAccessibilityLabel("女声 / Female voice"); view.addSubview(voiceChoice); reloadVoices()
        info.frame = NSRect(x:20,y:316,width:370,height:38); view.addSubview(info)
        muted = NSButton(checkboxWithTitle:"静音 / Mute",target:self,action:#selector(changeMute)); muted.state = audio.isMuted ? .on : .off
        muted.frame = NSRect(x:20,y:280,width:130,height:26); view.addSubview(muted)
        reactions = NSButton(checkboxWithTitle:"跟随动作说话 / Action voice",target:self,action:#selector(changeAutomatic)); reactions.state = audio.automatic ? .on : .off
        reactions.frame = NSRect(x:155,y:280,width:240,height:26); view.addSubview(reactions)
        let label = text("音量 / Volume",size:12,color:.labelColor); label.frame = NSRect(x:20,y:248,width:90,height:22); view.addSubview(label)
        let slider = NSSlider(value:Double(audio.volume),minValue:0,maxValue:1,target:self,action:#selector(changeVolume))
        slider.setAccessibilityLabel("声音音量 / Voice volume"); slider.frame = NSRect(x:115,y:245,width:275,height:26); view.addSubview(slider)
        cueChoice = NSPopUpButton(frame:NSRect(x:20,y:207,width:370,height:28)); cueChoice.addItems(withTitles:VoiceCue.allCases.map(\.label)); cueChoice.target=self; cueChoice.action=#selector(changeCue)
        cueChoice.setAccessibilityLabel("动作短句 / Action phrase"); view.addSubview(cueChoice)
        let specs: [(String,Selector)] = [("试听短句 / Preview",#selector(preview)),("停止 / Stop",#selector(stop)),("导入此动作音频… / Import…",#selector(importFile)),("恢复此动作女声 / Reset cue",#selector(resetFile))]
        for (i,spec) in specs.enumerated() {
            let b = button(spec.0,self,spec.1,hint:spec.0)
            b.frame = NSRect(x:20+CGFloat(i%2)*190,y:166-CGFloat(i/2)*36,width:180,height:30); view.addSubview(b)
        }
        result.frame = NSRect(x:20,y:72,width:370,height:48); view.addSubview(result)
        let note = text("只在动作开始时说一句；有冷却、不叠音。\nLocal cues on action changes; cooldown, no overlap.",size:11,color:.secondaryLabelColor)
        note.frame = NSRect(x:20,y:20,width:370,height:42); view.addSubview(note)
        refresh()
    }
    override func viewDidAppear() { super.viewDidAppear(); view.window?.makeFirstResponder(view) }
    func reloadVoices() {
        voiceChoice.removeAllItems(); voiceChoice.addItem(withTitle:audio.resolvedLanguage == "zh" ? "小田 · 内置短句 / Tian · bundled cues" : "本机女声（自动） / Local female voice (auto)")
        voiceChoice.lastItem?.representedObject = ""
        for voice in audio.voices {
            voiceChoice.addItem(withTitle:"\(voice.name) · \(voice.language)" + (voice.quality.rawValue > 1 ? " · Enhanced" : ""))
            voiceChoice.lastItem?.representedObject = voice.identifier
        }
        let id = audio.voiceIDs[audio.resolvedLanguage] ?? ""
        if let index = voiceChoice.itemArray.firstIndex(where: { $0.representedObject as? String == id }) { voiceChoice.selectItem(at:index) }
        else { voiceChoice.addItem(withTitle:"所选声线不可用 / Selected voice unavailable"); voiceChoice.lastItem?.representedObject = id; voiceChoice.select(voiceChoice.lastItem) }
    }
    func refresh() {
        guard isViewLoaded else { return }
        info.stringValue = audio.customFile(selectedCue) != nil ? "此动作使用导入音频 / This action uses imported audio" : audio.sourceLabel
        result.stringValue = (audio.customFile(selectedCue) != nil ? "此动作使用导入音频 / Imported cue\n" : selectedCue.phrase(audio.resolvedLanguage)+"\n") + audio.lastResult
    }
    func persist() { refresh(); changed?() }
    @objc func closePanel() { close?() }
    @objc func changeLanguage(_ sender:NSSegmentedControl) { audio.stop(); audio.language=["auto","zh","en"][sender.selectedSegment]; reloadVoices(); persist() }
    @objc func changeVoice() { audio.stop(); audio.voiceIDs[audio.resolvedLanguage]=voiceChoice.selectedItem?.representedObject as? String ?? ""; persist() }
    @objc func changeCue() { refresh() }
    @objc func changeMute() { audio.isMuted=muted.state == .on; persist() }
    @objc func changeAutomatic() { audio.automatic=reactions.state == .on; persist() }
    @objc func changeVolume(_ sender:NSSlider) { audio.volume=sender.floatValue; persist() }
    @objc func preview() { audio.speak(selectedCue); refresh() }
    @objc func stop() { audio.stop(); refresh() }
    @objc func importFile() { importAudio?(selectedCue) }
    @objc func resetFile() { resetAudio?(selectedCue); refresh() }
}

extension Companion {
    @objc func showSoundFromMenu() {
        if soundPopover?.isShown == true { soundPopover?.close(); return }
        if let stage = stage, stage.isVisible, let control = stageView?.actions.first(where: { $0.action == #selector(showSound) }) { showSound(control); return }
        showPanel(); panelView.expanded=true; panelView.refreshVisibility(); showSound(panelView.controls[2])
    }
    @objc func showSound(_ sender:NSButton) {
        if soundPopover?.isShown == true { soundPopover?.close(); return }
        // Both distribution forms use the same preference location; opening the
        // panel must not silently switch away from existing imported audio.
        sound.customDirectory=preferenceDirectory
        sound.legacyDirectory=stateDirectory
        let vc=AudioSettingsController(audio:sound)
        vc.changed = { [weak self] in self?.saveSettings(); self?.rebuildMenu(); self?.writePlaybackState("audio_settings") }
        vc.close = { [weak self] in self?.soundPopover?.close() }
        sound.changed = { [weak self, weak vc] in vc?.refresh(); self?.writePlaybackState("audio_playback") }
        vc.importAudio = { [weak self] cue in
            guard let self=self else { return }
            self.soundPopover?.close(); NSApp.activate(ignoringOtherApps:true)
            let panel=NSOpenPanel(); panel.title="导入动作短句 / Import action cue · \(cue.label)"
            panel.allowedContentTypes=[.audio]; panel.canChooseDirectories=false; panel.allowsMultipleSelection=false
            guard panel.runModal() == .OK, let url=panel.url else { return }
            do {
                try self.sound.importCue(cue,from:url)
                self.writePlaybackState("local_action_voice_imported")
            } catch {
                let alert=NSAlert(); alert.messageText="音频无法导入 / Cannot import audio"
                alert.informativeText="请选择可播放、120 秒以内且小于 25MB 的音频。 / Choose playable audio under 120 seconds and 25MB."; alert.runModal()
            }
        }
        vc.resetAudio = { [weak self] cue in
            guard let self=self else { return }
            do { try self.sound.resetCue(cue) }
            catch { let alert=NSAlert(); alert.messageText="恢复失败 / Could not reset audio"; alert.informativeText="原音频保留；请检查目录权限。 / Existing audio remains; check folder access."; alert.runModal() }
        }
        let popover=NSPopover(); popover.behavior = .transient; popover.animates=false; popover.contentViewController=vc
        soundPopover=popover; popover.show(relativeTo:sender.bounds,of:sender,preferredEdge:.minX)
    }
}

// SIMULATED local-file fixtures; no synthesis, network or Owner preferences.
func runAudioStorageTests() throws {
    func require(_ value: Bool, line: Int = #line) throws { if !value { throw NSError(domain:"Audio storage fixture at line \(line)",code:1) } }
    let root=FileManager.default.temporaryDirectory.appendingPathComponent("nyra-audio-test-"+UUID().uuidString)
    try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
    defer { try? FileManager.default.removeItem(at:root) }
    let legacy=root.appendingPathComponent("legacy"); try FileManager.default.createDirectory(at:legacy,withIntermediateDirectories:true)
    let audio=NyraAudio(); audio.customDirectory=root; audio.legacyDirectory=legacy; audio.language="zh"
    var wave=Data()
    func ascii(_ value:String) { wave.append(contentsOf:value.utf8) }
    func u16(_ value:UInt16) { var v=value.littleEndian; withUnsafeBytes(of:&v) { wave.append(contentsOf:$0) } }
    func u32(_ value:UInt32) { var v=value.littleEndian; withUnsafeBytes(of:&v) { wave.append(contentsOf:$0) } }
    ascii("RIFF"); u32(3636); ascii("WAVEfmt "); u32(16); u16(1); u16(1); u32(18000); u32(36000); u16(2); u16(16); ascii("data"); u32(3600); wave.append(Data(repeating:0,count:3600))
    let input=root.appendingPathComponent("TEST-中文短句.wav"); try wave.write(to:input)
    try audio.importCue(.rest,from:input)
    let saved=audio.customFile(.rest)!
    try require(try Data(contentsOf:saved) == wave)
    try require(audio.playbackCount == 0 && !audio.isPlaying)
    let bad=root.appendingPathComponent("invalid.wav"); try Data("not audio".utf8).write(to:bad)
    do { try audio.importCue(.rest,from:bad); throw NSError(domain:"TEST accepted corrupt audio",code:1) }
    catch is PreviewError {} catch let e as NSError { if e.domain == "TEST accepted corrupt audio" { throw e } }
    try require(try Data(contentsOf:saved) == wave)
    let large=root.appendingPathComponent("large.wav"); try wave.write(to:large)
    let handle=try FileHandle(forWritingTo:large); try handle.truncate(atOffset:25*1024*1024); try handle.close()
    do { try audio.importCue(.rest,from:large); throw NSError(domain:"TEST accepted oversized audio",code:1) }
    catch is PreviewError {} // No existing cue may be replaced on failure.
    try require(try Data(contentsOf:saved) == wave)
    audio.language="en"; try require(audio.customFile(.rest) == nil)
    audio.language="zh"; try require(audio.customFile(.success) == nil)
    try wave.write(to:legacy.appendingPathComponent("voice-zh.audio"))
    try require(audio.customFile(.welcome)?.deletingLastPathComponent().path == legacy.path)
    try audio.importCue(.welcome,from:input); try audio.resetCue(.welcome)
    try require(audio.customFile(.welcome) == nil && audio.customFile(.rest) != nil)
    try audio.resetCue(.rest); try require(audio.customFile(.rest) == nil)
    audio.speak(.rest); try require(audio.playbackCount == 0 && !audio.isPlaying)
    try require(NyraAudio.resolveLanguage("auto",preferred:["zh-Hans"]) == "zh")
    try require(NyraAudio.resolveLanguage("auto",preferred:["fr-FR"]) == "en")
    try require(NyraAudio.resolveLanguage("en",preferred:["zh-Hans"]) == "en")
    // Bundled TEST fixture: exact cue bytes, no network or generated speech.
    let bundled = root.appendingPathComponent("TEST-bundled")
    try FileManager.default.createDirectory(at:bundled,withIntermediateDirectories:true)
    let digest = SHA256.hash(data:wave).map { String(format:"%02x",$0) }.joined()
    var clips: [String:Any] = [:]
    for cue in VoiceCue.allCases {
        try wave.write(to:bundled.appendingPathComponent(cue.rawValue+".wav"))
        clips[cue.rawValue] = ["file":cue.rawValue+".wav","sha256":digest,"text":cue.phrase("zh")]
    }
    func writeManifest(_ clips: [String:Any]) throws {
        try JSONSerialization.data(withJSONObject:["schema":1,"voice_id":"ttsmaker:1413:default","display_name":"小田 / Tian","language":"zh","clips":clips]).write(to:bundled.appendingPathComponent("manifest.json"))
    }
    try writeManifest(clips)
    audio.bundledVoiceRoot = bundled
    try require(audio.usesBundledVoice && audio.sourceLabel.contains("小田"))
    try require(try audio.bundledData(.rest) == wave)
    audio.voiceIDs["zh"] = "TEST-system-voice"
    try require(!audio.usesBundledVoice)
    audio.voiceIDs["zh"] = ""
    audio.language = "en"; try require(!audio.usesBundledVoice)
    audio.language = "zh"
    try Data("damaged".utf8).write(to:bundled.appendingPathComponent("rest.wav"))
    do { _ = try audio.bundledData(.rest); throw NSError(domain:"TEST accepted bad digest",code:1) }
    catch is PreviewError {}
    try wave.write(to:bundled.appendingPathComponent("rest.wav"))
    clips["rest"] = ["file":"../TEST-中文短句.wav","sha256":digest,"text":VoiceCue.rest.phrase("zh")]
    try writeManifest(clips)
    do { _ = try audio.bundledData(.rest); throw NSError(domain:"TEST accepted traversal",code:1) }
    catch is PreviewError {}
    clips["rest"] = ["file":"rest.wav","sha256":digest,"text":"wrong cue"]
    try writeManifest(clips)
    do { _ = try audio.bundledData(.rest); throw NSError(domain:"TEST accepted wrong phrase",code:1) }
    catch is PreviewError {}
    clips["rest"] = nil; try writeManifest(clips)
    do { _ = try audio.bundledData(.rest); throw NSError(domain:"TEST accepted incomplete pack",code:1) }
    catch is PreviewError {}
    print("PASS: bundled voice TEST fixtures — selection, locale, exact bytes, corruption, traversal, phrase and completeness")
    print("PASS: audio storage TEST fixtures — exact bytes, corrupt/size rejection, legacy retention/reset, per-action/language isolation and muted preview")
}
