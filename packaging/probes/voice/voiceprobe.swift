// V2 probes P1–P3 (spec docs/specs/2026-09-02-realtime-voice-v2-build.md §5).
// Launched as a signed .app via `open` so TCC treats it as a GUI app.
// Usage (via open --args): voiceprobe <log-path> <mode: all|p1|p2|p3>
import AVFoundation
import CoreAudio
import Foundation
import Speech

let args = CommandLine.arguments
let logPath = args.count > 1 ? args[1] : "/tmp/voiceprobe.log"
let mode = args.count > 2 ? args[2] : "all"
let t0 = Date()
let logLock = NSLock()
func log(_ s: String) {
    logLock.lock(); defer { logLock.unlock() }
    let line = String(format: "[%7.2f] ", Date().timeIntervalSince(t0)) + s + "\n"
    if let h = FileHandle(forWritingAtPath: logPath) { h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); h.closeFile() }
    else { FileManager.default.createFile(atPath: logPath, contents: line.data(using: .utf8)) }
}
func sleepS(_ s: Double) { Thread.sleep(forTimeInterval: s) }

// --- CoreAudio: find + set default devices (restored on exit) ----------------
func allDevices() -> [(AudioDeviceID, String)] {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size)
    var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &ids)
    return ids.map { id in
        var nAddr = AudioObjectPropertyAddress(mSelector: kAudioObjectPropertyName, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var name: Unmanaged<CFString>? = nil
        var nsize = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        AudioObjectGetPropertyData(id, &nAddr, 0, nil, &nsize, &name)
        return (id, (name?.takeUnretainedValue() as String?) ?? "?")
    }
}
func getDefault(_ sel: AudioObjectPropertySelector) -> AudioDeviceID {
    var addr = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var id: AudioDeviceID = 0; var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &id); return id
}
func setDefault(_ sel: AudioObjectPropertySelector, _ id: AudioDeviceID) -> OSStatus {
    var addr = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var v = id
    return AudioObjectSetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, UInt32(MemoryLayout<AudioDeviceID>.size), &v)
}
let devs = allDevices()
log("devices: " + devs.map { "\($0.0)=\($0.1)" }.joined(separator: " | "))
let oldIn = getDefault(kAudioHardwarePropertyDefaultInputDevice)
let oldOut = getDefault(kAudioHardwarePropertyDefaultOutputDevice)
guard let micID = devs.first(where: { $0.1 == "MacBook Pro Microphone" })?.0,
      let spkID = devs.first(where: { $0.1 == "MacBook Pro Speakers" })?.0 else {
    log("FATAL built-in devices not found"); log("DONE"); exit(1)
}
log("default in/out before: \(oldIn)/\(oldOut); pinning built-in \(micID)/\(spkID)")
log("setDefault in=\(setDefault(kAudioHardwarePropertyDefaultInputDevice, micID)) out=\(setDefault(kAudioHardwarePropertyDefaultOutputDevice, spkID))")
func osa(_ script: String) -> String {
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript"); p.arguments = ["-e", script]
    let out = Pipe(); p.standardOutput = out; try? p.run(); p.waitUntilExit()
    return String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
}
let oldVolume = osa("output volume of (get volume settings)")
_ = osa("set volume output volume 80")
log("output volume \(oldVolume) -> 80 for the probe")
func restoreDefaults() {
    _ = osa("set volume output volume \(oldVolume)")
    _ = setDefault(kAudioHardwarePropertyDefaultInputDevice, oldIn)
    _ = setDefault(kAudioHardwarePropertyDefaultOutputDevice, oldOut)
    log("defaults restored to \(oldIn)/\(oldOut)")
}
atexit { restoreDefaults() }
signal(SIGTERM) { _ in restoreDefaults(); exit(0) }

func auDevice(_ node: AVAudioIONode) -> AudioDeviceID {
    guard let au = node.audioUnit else { return 0 }
    var d: AudioDeviceID = 0; var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    AudioUnitGetProperty(au, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &d, &size); return d
}

func authorize() {
let authSem = DispatchSemaphore(value: 0)
var speechAuth: SFSpeechRecognizerAuthorizationStatus = .notDetermined
SFSpeechRecognizer.requestAuthorization { s in speechAuth = s; authSem.signal() }
if authSem.wait(timeout: .now() + 120) == .timedOut { log("FATAL speech auth timeout"); log("DONE"); exit(1) }
log("speech auth = \(speechAuth.rawValue) (3=authorized)")
let micSem = DispatchSemaphore(value: 0); var micOK = false
AVCaptureDevice.requestAccess(for: .audio) { g in micOK = g; micSem.signal() }
if micSem.wait(timeout: .now() + 120) == .timedOut { log("FATAL mic auth timeout"); log("DONE"); exit(1) }
log("mic auth = \(micOK)")
guard speechAuth == .authorized, micOK else { log("FATAL not authorized"); log("DONE"); exit(1) }
}


// --- TTS to PCM buffers (for in-engine playback) ------------------------------
let synth = AVSpeechSynthesizer()
func synthesize(_ text: String, lang: String) -> [AVAudioPCMBuffer] {
    var out: [AVAudioPCMBuffer] = []; let done = DispatchSemaphore(value: 0)
    let u = AVSpeechUtterance(string: text); u.voice = AVSpeechSynthesisVoice(language: lang)
    synth.write(u) { buf in
        if let b = buf as? AVAudioPCMBuffer, b.frameLength > 0 { out.append(b) } else { done.signal() }
    }
    _ = done.wait(timeout: .now() + 20)
    return out
}
func sayOtherProcess(_ text: String) {
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/say")
    p.arguments = ["-v", "Samantha", text]      // default output = pinned speakers
    try? p.run(); p.waitUntilExit()
}

// --- one listening session ---------------------------------------------------
struct Session {
    let engine = AVAudioEngine()
    let player = AVAudioPlayerNode()
    var request: SFSpeechAudioBufferRecognitionRequest?
    var task: SFSpeechRecognitionTask?
    let recognizer: SFSpeechRecognizer
    var partials: [(Double, String)] = []
    var finalText: String?
    var lastPartialAt = Date()
    let finalSem = DispatchSemaphore(value: 0)

    init(locale: String, voiceProcessing: Bool, label: String) {
        recognizer = SFSpeechRecognizer(locale: Locale(identifier: locale))!
        let input = engine.inputNode
        let f0 = input.outputFormat(forBus: 0)
        log("[\(label)] input format before VP: \(f0.sampleRate)Hz ch=\(f0.channelCount) fmt=\(f0.commonFormat.rawValue)")
        if voiceProcessing {
            do { try input.setVoiceProcessingEnabled(true); log("[\(label)] setVoiceProcessingEnabled(true) ok; isVoiceProcessingEnabled=\(input.isVoiceProcessingEnabled)") }
            catch { log("[\(label)] setVoiceProcessingEnabled FAILED: \(error)") }
            if #available(macOS 14.0, *) {
                log("[\(label)] outputNode.isVoiceProcessingEnabled=\(engine.outputNode.isVoiceProcessingEnabled)")
            }
        }
        let f1 = input.outputFormat(forBus: 0)
        log("[\(label)] input format after VP: \(f1.sampleRate)Hz ch=\(f1.channelCount); AU device=\(auDevice(input))")
        engine.attach(player)
        let of = engine.outputNode.outputFormat(forBus: 0)
        log("[\(label)] output format: \(of.sampleRate)/\(of.channelCount); sys default in/out now \(getDefault(kAudioHardwarePropertyDefaultInputDevice))/\(getDefault(kAudioHardwarePropertyDefaultOutputDevice))")
        if voiceProcessing {
            engine.connect(player, to: engine.mainMixerNode, format: AVAudioFormat(standardFormatWithSampleRate: of.sampleRate, channels: 1))
            engine.connect(engine.mainMixerNode, to: engine.outputNode, format: of)
        } else {
            engine.connect(player, to: engine.mainMixerNode, format: AVAudioFormat(standardFormatWithSampleRate: 22050, channels: 1))
        }
        player.volume = 1.0
    }

    mutating func arm() {
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
        request = req
        partials = []; finalText = nil
        let sem = finalSem
        task = recognizer.recognitionTask(with: req) { result, error in
            if let r = result {
                let text = r.bestTranscription.formattedString
                if r.isFinal { probeState.onFinal(text); sem.signal() }
                else { probeState.onPartial(text) }
            } else if let e = error {
                log("  recognizer error: \((e as NSError).domain)/\((e as NSError).code) \(e.localizedDescription)"); probeState.onFinal(nil); sem.signal()
            }
        }
    }
    func startEngine(label: String) {
        let input = engine.inputNode
        let f = input.outputFormat(forBus: 0)
        let monoIn = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: f.sampleRate, channels: 1, interleaved: false)!
        let mono16 = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false)!
        let conv = AVAudioConverter(from: monoIn, to: mono16)
        log("[\(label)] tap \(f.sampleRate)/\(f.channelCount) -> channel 0 only -> 16000/1 (converter \(conv == nil ? "MISSING" : "ok"))")
        input.installTap(onBus: 0, bufferSize: 1024, format: f) { buffer, _ in
            guard let ch = buffer.floatChannelData else { return }
            let n = Int(buffer.frameLength)
            // per-channel peaks (which of the 9 VP channels carries the voice?)
            for c in 0..<Int(f.channelCount) { var pk: Float = 0; for i in 0..<n { pk = max(pk, abs(ch[c][i])) }; probeState.chPeak[c] = max(probeState.chPeak[c], pk) }
            probeState.frames += n
            let m = AVAudioPCMBuffer(pcmFormat: monoIn, frameCapacity: AVAudioFrameCount(n))!; m.frameLength = AVAudioFrameCount(n)
            memcpy(m.floatChannelData![0], ch[0], n * 4)
            if let c = conv {
                let ob = AVAudioPCMBuffer(pcmFormat: mono16, frameCapacity: AVAudioFrameCount(Double(n) * 16000 / f.sampleRate) + 16)!
                var err: NSError? = nil; var fed = false
                c.convert(to: ob, error: &err) { _, st in if fed { st.pointee = .noDataNow; return nil }; fed = true; st.pointee = .haveData; return m }
                if ob.frameLength > 0 { probeState.append(ob) }
            } else { probeState.append(m) }
        }
        // after a VP session the default output device can be gone for a moment; do not start into a 0 Hz output
        var tries = 0
        while engine.outputNode.outputFormat(forBus: 0).sampleRate == 0 && tries < 50 { sleepS(0.1); tries += 1 }
        if tries > 0 { log("[\(label)] waited \(tries * 100)ms for the output device") }
        engine.prepare()
        do { try engine.start(); log("[\(label)] engine started; running=\(engine.isRunning)") }
        catch { log("[\(label)] engine start FAILED: \(error)") }
    }
    func playInEngine(_ buffers: [AVAudioPCMBuffer]) {
        guard let first = buffers.first else { log("  no TTS buffers"); return }
        let target = player.outputFormat(forBus: 0)
        log("  TTS \(buffers.count) buffers \(first.format.sampleRate)/\(first.format.channelCount) -> player \(target.sampleRate)/\(target.channelCount)")
        guard let conv = AVAudioConverter(from: first.format, to: target) else { log("  no converter"); return }
        var out: [AVAudioPCMBuffer] = []
        for b in buffers {
            let cap = AVAudioFrameCount(Double(b.frameLength) * target.sampleRate / first.format.sampleRate) + 64
            let ob = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: cap)!
            var err: NSError? = nil; var fed = false
            conv.convert(to: ob, error: &err) { _, st in if fed { st.pointee = .noDataNow; return nil }; fed = true; st.pointee = .haveData; return b }
            if ob.frameLength > 0 { out.append(ob) }
        }
        let done = DispatchSemaphore(value: 0)
        for (i, b) in out.enumerated() {
            if i == out.count - 1 { player.scheduleBuffer(b) { done.signal() } } else { player.scheduleBuffer(b) }
        }
        player.play()
        _ = done.wait(timeout: .now() + 20)
        sleepS(0.3)
    }
    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }
}

// Shared mutable state the recognizer callbacks write into (single-threaded by the probe's sequencing).
final class ProbeState {
    var current: SFSpeechAudioBufferRecognitionRequest?
    var partials: [(Double, String)] = []
    var finalText: String?
    var lastChange = Date()
    var lastText = ""
    var peak: Float = 0
    var chPeak = [Float](repeating: 0, count: 16)
    var frames: Int = 0
    func append(_ b: AVAudioPCMBuffer) { current?.append(b) }
    func onPartial(_ t: String) {
        if t != lastText { lastText = t; lastChange = Date() }
        partials.append((Date().timeIntervalSince(t0), t))
    }
    func onFinal(_ t: String?) { finalText = t ?? "" }
    func reset() { partials = []; finalText = nil; lastText = ""; lastChange = Date(); peak = 0; frames = 0; chPeak = [Float](repeating: 0, count: 16) }
    func meter() -> String {
        let used = chPeak.enumerated().filter { $0.offset < 9 }.map { String(format: "%.3f", $0.element) }
        let m = "frames=\(frames) chPeaks=[" + used.joined(separator: " ") + "]"
        chPeak = [Float](repeating: 0, count: 16); return m
    }
}
let probeState = ProbeState()

let sentence = "The purple elephant carried seventeen umbrellas to the library."
let keywords = ["purple", "elephant", "seventeen", "umbrella", "library"]
func score(_ t: String) -> Int { let l = t.lowercased(); return keywords.filter { l.contains($0) }.count }

// One P1 case: listen, play the sentence (in-engine or from another process), see what the recognizer heard.
func p1Case(label: String, vp: Bool, inEngine: Bool) {
    log("=== \(label): VP=\(vp) source=\(inEngine ? "in-engine playerNode" : "other process (/usr/bin/say)") ===")
    var s = Session(locale: "en-US", voiceProcessing: vp, label: label)
    probeState.reset()
    s.arm(); probeState.current = s.request
    s.startEngine(label: label)
    sleepS(1.0)
    log("  mic idle: \(probeState.meter()) | engine dev=\(auDevice(s.engine.inputNode)) | sys default \(getDefault(kAudioHardwarePropertyDefaultInputDevice))/\(getDefault(kAudioHardwarePropertyDefaultOutputDevice))")
    if probeState.frames == 0 { log("  RESULT \(label): NO INPUT FRAMES — case void"); s.task?.cancel(); s.stop(); sleepS(1.5); return }
    let tPlay = Date()
    if inEngine { s.playInEngine(synthesize(sentence, lang: "en-US")) } else { sayOtherProcess(sentence) }
    log("  playback took \(String(format: "%.1f", Date().timeIntervalSince(tPlay)))s; mic during playback: \(probeState.meter()); listening 2.5s more")
    sleepS(2.5)
    s.request?.endAudio()
    if s.finalSem.wait(timeout: .now() + 8) == .timedOut { log("  final never came (8s)") }
    let heard = probeState.finalText ?? probeState.partials.last?.1 ?? ""
    let best = max(score(heard), probeState.partials.map { score($0.1) }.max() ?? 0)
    log("  mic \(probeState.meter()) | partials=\(probeState.partials.count) final='\(heard)'")
    log("  RESULT \(label): keywords heard \(best)/\(keywords.count) -> \(best == 0 ? "ECHO CANCELLED (nothing heard)" : best >= 3 ? "ECHO HEARD" : "RESIDUAL (\(best) words)")")
    s.task?.cancel(); s.stop()
    sleepS(1.5)
}

// P2: continuous listening with our own endpointing; stimulus = say, three sentences with pauses.
func p2() {
    log("=== P2: continuous re-arm, VP=false, endpoint = 900ms of no partial change ===")
    var s = Session(locale: "en-US", voiceProcessing: false, label: "P2")
    let stim = ["First sentence about the weather.", "Second sentence about the library.", "Third sentence about elephants."]
    DispatchQueue.global().async {
        sleepS(1.0)
        for x in stim { sayOtherProcess(x); sleepS(2.0) }
    }
    var utterances: [String] = []
    var armAt = Date()
    s.arm(); probeState.reset(); probeState.current = s.request; armAt = Date()
    s.startEngine(label: "P2")
    let end = Date().addingTimeInterval(16)
    var firstPartialLogged = false
    while Date() < end {
        sleepS(0.05)
        if !firstPartialLogged, let fp = probeState.partials.first {
            log("  first partial \(String(format: "%.2f", fp.0 - armAt.timeIntervalSince(t0)))s after arm: '\(fp.1)'"); firstPartialLogged = true
        }
        let text = probeState.lastText
        if !text.isEmpty, Date().timeIntervalSince(probeState.lastChange) >= 0.9 {
            let tEnd = Date()
            s.request?.endAudio()
            let got = s.finalSem.wait(timeout: .now() + 5) != .timedOut
            let fin = probeState.finalText ?? ""
            log("  ENDPOINT -> endAudio -> final in \(String(format: "%.2f", Date().timeIntervalSince(tEnd)))s (got=\(got)): '\(fin)'")
            utterances.append(fin)
            s.task?.cancel()
            s.arm(); probeState.reset(); probeState.current = s.request; armAt = Date(); firstPartialLogged = false
        }
    }
    s.request?.endAudio(); s.task?.cancel(); s.stop()
    let dups = Set(utterances).count != utterances.count
    log("  RESULT P2: \(utterances.count) utterances for \(stim.count) stimuli; duplicates=\(dups); on-device=\(s.recognizer.supportsOnDeviceRecognition)")
    sleepS(0.5)
}

// P3: VP on, the human speaks (prompted by TTS), does the recognizer take the VP input format?
func p3speak() {
    log("=== P3: VP=true, human speaks zh-CN after the prompt ===")
    var s = Session(locale: "zh-CN", voiceProcessing: true, label: "P3")
    s.arm(); probeState.reset(); probeState.current = s.request
    s.startEngine(label: "P3")
    sleepS(1.0)
    log("  mic idle: \(probeState.meter())")
    s.playInEngine(synthesize("请现在说一句话", lang: "zh-CN"))
    log("  mic during prompt: \(probeState.meter())")
    sleepS(7.0)
    s.request?.endAudio()
    _ = s.finalSem.wait(timeout: .now() + 8)
    log("  mic \(probeState.meter()) | partials=\(probeState.partials.count) final='\(probeState.finalText ?? "")'")
    log("  RESULT P3: \(probeState.partials.isEmpty ? "NOTHING recognized under VP (format rejected OR nobody spoke)" : "recognizer WORKS on VP input")")
    s.task?.cancel(); s.stop()
}

func p0calibrate() {
    log("=== P0: VP=false, human speaks zh-CN after the prompt (calibration: mic level + recognizer alive) ===")
    var s = Session(locale: "zh-CN", voiceProcessing: false, label: "P0")
    s.arm(); probeState.reset(); probeState.current = s.request
    s.startEngine(label: "P0")
    sleepS(0.5)
    s.playInEngine(synthesize("请现在说一句话", lang: "zh-CN"))
    log("  prompt played; mic during prompt: \(probeState.meter())")
    sleepS(7.0)
    s.request?.endAudio()
    _ = s.finalSem.wait(timeout: .now() + 8)
    log("  mic during your speech: \(probeState.meter()) | partials=\(probeState.partials.count) final='\(probeState.finalText ?? "")'")
    log("  RESULT P0: \(probeState.partials.isEmpty ? "recognizer heard NOTHING (mic dead, too quiet, or nobody spoke)" : "recognizer alive; human voice recognized")")
    s.task?.cancel(); s.stop()
    sleepS(1.0)
}

log("mode=\(mode) macOS=\(ProcessInfo.processInfo.operatingSystemVersionString)")
DispatchQueue(label: "probe.sequence").async {
authorize()
if mode == "all" || mode == "p0" { p0calibrate() }
if mode == "all" || mode == "p1" {
    p1Case(label: "P1a", vp: false, inEngine: true)    // control: echo must be heard
    p1Case(label: "P1c", vp: false, inEngine: false)   // control: other process heard
}
if mode == "all" || mode == "p2" { p2() }
if mode == "all" || mode == "p3" { p3speak() }          // VP on + human: is the recognizer deaf under VP?
if mode == "all" || mode == "p1" {
    p1Case(label: "P1b", vp: true,  inEngine: true)    // AEC by construction
    p1Case(label: "P1d", vp: true,  inEngine: false)   // THE question: system-wide AEC?
}
log("DONE")
exit(0)
}
RunLoop.main.run()
