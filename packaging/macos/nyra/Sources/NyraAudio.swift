import AppKit
import AVFoundation
import UniformTypeIdentifiers

final class NyraAudio: NSObject {
    let speech = NSSpeechSynthesizer()
    private var player: AVAudioPlayer?
    private var effect: AVAudioPlayer?
    var isMuted = true { didSet { if isMuted { stop() } } }
    var volume: Float = 0.45 { didSet { speech.volume = volume; player?.volume = volume; effect?.volume = volume*0.5 } }
    var language = "auto"
    var customDirectory: URL?
    private(set) var lastResult = "尚未播放"
    var resolvedLanguage: String { Self.resolveLanguage(language, preferred: Locale.preferredLanguages) }
    static func resolveLanguage(_ choice: String, preferred: [String]) -> String {
        choice == "auto" ? ((preferred.first ?? "en").hasPrefix("zh") ? "zh" : "en") : choice
    }
    var voice: NSSpeechSynthesizer.VoiceName? {
        let name = resolvedLanguage == "zh" ? "tingting" : "samantha"
        return NSSpeechSynthesizer.availableVoices.first {
            $0.rawValue.lowercased().contains(name)
        } ?? NSSpeechSynthesizer.availableVoices.first {
            let a = NSSpeechSynthesizer.attributes(forVoice: $0)
            return (a[.localeIdentifier] as? String ?? "").hasPrefix(resolvedLanguage)
                && (a[.gender] as? String ?? "").lowercased().contains("female")
        }
    }
    var customFile: URL? {
        guard let directory = customDirectory else { return nil }
        let candidate = directory.appendingPathComponent("voice-\(resolvedLanguage).audio")
        return FileManager.default.fileExists(atPath: candidate.path) ? candidate : nil
    }
    var sourceLabel: String {
        if customFile != nil { return "自有音频 · \(resolvedLanguage.uppercased())" }
        guard let voice = voice else { return "当前语言没有已安装的女性声线" }
        let name = NSSpeechSynthesizer.attributes(forVoice: voice)[.name] as? String ?? ""
        return "系统合成语音 · \(name) · \(resolvedLanguage.uppercased())"
    }
    var snapshot: [String: Any] {
        ["muted": isMuted, "volume": volume, "language": language, "resolved_language": resolvedLanguage,
         "source": sourceLabel, "result": lastResult, "speaking": speech.isSpeaking,
         "audio_playing": player?.isPlaying == true || effect?.isPlaying == true,
         "custom_exclusive_voice_produced": false]
    }
    func stop() { speech.stopSpeaking(); player?.stop(); effect?.stop() }
    func chime(_ kind: String) {
        guard !isMuted, volume > 0,
              let url = Bundle.main.resourceURL?.appendingPathComponent("audio/\(kind).wav") else { return }
        do {
            effect = try AVAudioPlayer(contentsOf: url); effect?.volume = volume*0.5
            if effect?.play() != true { lastResult = "提示音无法播放" }
        } catch { lastResult = "提示音无法加载" }
    }
    func speak(_ kind: String = "welcome") {
        guard !isMuted, volume > 0 else { lastResult = "已静音"; return }
        speech.stopSpeaking(); player?.stop()
        if let url = customFile {
            do {
                player = try AVAudioPlayer(contentsOf: url); player?.volume = volume
                lastResult = player?.play() == true ? "已播放自有音频" : "自有音频播放失败"
            } catch { lastResult = "自有音频不可读取" }
            return
        }
        guard let voice = voice, speech.setVoice(voice) else { lastResult = "当前语言缺少可用女性声线"; return }
        let phrases = [
            "welcome": ["我在这里，陪你慢慢来。累了，就休息一会儿吧。", "I'm here with you. Take your time. We can rest for a little while."],
            "outfit": ["换好啦。今天，就这样陪着你吧。", "All dressed up. I'll stay here with you today."],
            "working": ["慢慢来，我会安静地陪着你。", "Take your time. I'll keep you company."],
            "success": ["辛苦啦。我们一起看看结果吧。", "You've worked hard. Let's look at the result together."]]
        speech.rate = resolvedLanguage == "zh" ? 150 : 145; speech.volume = volume
        let words = (phrases[kind] ?? phrases["welcome"]!)[resolvedLanguage == "zh" ? 0 : 1]
        lastResult = speech.startSpeaking(words) ? "已开始系统合成语音" : "系统合成语音启动失败"
    }
}

final class AudioSettingsController: NSViewController {
    let audio: NyraAudio
    var changed: (() -> Void)?
    var importAudio: (() -> Void)?
    var resetAudio: (() -> Void)?
    let info = text("", size: 11, color: .lightGray)
    var muted: NSButton!
    init(audio: NyraAudio) { self.audio = audio; super.init(nibName: nil, bundle: nil) }
    required init?(coder: NSCoder) { fatalError() }
    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 350, height: 330))
        let heading = text("夜璃的声音 / Voice", size: 18)
        heading.frame = NSRect(x: 20, y: 285, width: 310, height: 28); view.addSubview(heading)
        let language = NSSegmentedControl(labels: ["跟随系统", "中文", "English"], trackingMode: .selectOne,
                                          target: self, action: #selector(changeLanguage))
        language.selectedSegment = ["auto","zh","en"].firstIndex(of: audio.language) ?? 0
        language.setAccessibilityLabel("语音语言")
        language.frame = NSRect(x: 20, y: 244, width: 310, height: 30); view.addSubview(language)
        info.frame = NSRect(x: 20, y: 190, width: 310, height: 46); view.addSubview(info)
        muted = NSButton(checkboxWithTitle: "静音 / Mute", target: self, action: #selector(changeMute))
        muted.state = audio.isMuted ? .on : .off
        muted.frame = NSRect(x: 20, y: 157, width: 150, height: 25); view.addSubview(muted)
        let label = text("音量", size: 12); label.frame = NSRect(x: 20, y: 121, width: 40, height: 22); view.addSubview(label)
        let slider = NSSlider(value: Double(audio.volume), minValue: 0, maxValue: 1, target: self, action: #selector(changeVolume))
        slider.setAccessibilityLabel("声音音量"); slider.frame = NSRect(x: 65, y: 118, width: 265, height: 26); view.addSubview(slider)
        let specs: [(String,Selector)] = [("试听系统语音",#selector(preview)),("停止",#selector(stop)),("导入音频…",#selector(importFile)),("恢复系统声线",#selector(resetFile))]
        for (i,spec) in specs.enumerated() {
            let b = button(spec.0, self, spec.1, hint: spec.0)
            b.frame = NSRect(x: 20+CGFloat(i%2)*158, y: 70-CGFloat(i/2)*37, width: 150, height: 30); view.addSubview(b)
        }
        refresh()
    }
    func refresh() { info.stringValue = audio.sourceLabel + "\n仅手动试听；使用已安装系统声线或你导入的音频。 / Manual preview: installed system voice or your imported audio."; changed?() }
    @objc func changeLanguage(_ sender: NSSegmentedControl) { audio.stop(); audio.language = ["auto","zh","en"][sender.selectedSegment]; refresh() }
    @objc func changeMute() { audio.isMuted = muted.state == .on; refresh() }
    @objc func changeVolume(_ sender: NSSlider) { audio.volume = sender.floatValue; refresh() }
    @objc func preview() { audio.chime("open"); audio.speak(); refresh() }
    @objc func stop() { audio.stop(); refresh() }
    @objc func importFile() { importAudio?() }
    @objc func resetFile() { resetAudio?(); refresh() }
}

extension Companion {
    @objc func showSoundFromMenu() { showPanel(); panelView.expanded = true; panelView.refreshVisibility(); showSound(panelView.controls[2]) }
    @objc func showSound(_ sender: NSButton) {
        sound.customDirectory = stateDirectory
        let vc = AudioSettingsController(audio: sound)
        vc.changed = { [weak self] in self?.saveSettings(); self?.rebuildMenu(); self?.writePlaybackState("audio_settings") }
        vc.importAudio = { [weak self, weak vc] in
            guard let self = self else { return }
            self.soundPopover?.close(); NSApp.activate(ignoringOtherApps: true)
            let panel = NSOpenPanel(); panel.title = "导入当前语言的声音 · 仅保存在本机"
            panel.allowedContentTypes = [.audio]; panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
            guard panel.runModal() == .OK, let url = panel.url else { return }
            do {
                let player = try AVAudioPlayer(contentsOf: url)
                guard player.duration > 0 && player.duration <= 120,
                      (try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0) < 25*1024*1024 else { throw PreviewError.invalidManifest }
                let destination = self.stateDirectory.appendingPathComponent("voice-\(self.sound.resolvedLanguage).audio")
                self.sound.stop()
                try Data(contentsOf: url).write(to: destination, options: .atomic)
                vc?.refresh(); self.writePlaybackState("local_voice_imported")
            } catch {
                let alert = NSAlert(); alert.messageText = "音频无法导入"
                alert.informativeText = "请选择可播放、120 秒以内且小于 25MB 的音频。"; alert.runModal()
            }
        }
        vc.resetAudio = { [weak self] in
            guard let self = self else { return }; self.sound.stop()
            if let url = self.sound.customFile { try? FileManager.default.removeItem(at: url) }
        }
        let popover = NSPopover(); popover.behavior = .semitransient; popover.contentViewController = vc
        soundPopover?.close(); soundPopover = popover
        popover.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minX)
    }
}
