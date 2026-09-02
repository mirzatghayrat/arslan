// arslan-voice — the ear for conversation mode. Long-lived: one process per
// session, not one per utterance. It reports what it hears and does nothing
// else; deciding that a sentence has ended is the shell's job (endpoint.rs),
// which is where it can be unit-tested.
//
// Spawned INSIDE the app bundle for the same reason arslan-listen is: TCC
// reads the usage strings from the bundle's Info.plist and a child that lives
// there inherits them. Dies when stdin closes, so a force-quit cannot leave
// the microphone open.
//
// stdout, one JSON object per line:
//   {"t":"ready"}                     a recogniser request is armed
//   {"t":"partial","text":"..."}
//   {"t":"final","text":"..."}        then a new request is armed at once
//   {"t":"level","peak":0.12}         every ~100 ms while unmuted
//   {"t":"state","muted":true}
//   {"t":"error","code":"...","msg":"..."}
// stdin, one JSON object per line:
//   {"c":"end_utterance"}  {"c":"mute"}  {"c":"unmute"}
//
// Measured (2026-09-03, docs/specs/2026-09-02-realtime-voice-v2-build.md §0.3):
//   - with voice processing on, inputNode's format is 48 kHz × 9 identical
//     channels; the recogniser gets channel 0 resampled to 16 kHz mono. A
//     converter asked to mix 9→1 produces garbage the recogniser calls silence.
//   - Speech callbacks arrive on the main queue: the main thread runs the
//     run loop and nothing else.
//   - error 1110 "No speech detected" is how the recogniser says "the request
//     has been silent a while"; re-arm, do not report.
import AVFoundation
import Foundation
import Speech

let outQueue = DispatchQueue(label: "arslan.voice.out")
func emit(_ obj: [String: Any]) {
    outQueue.sync {
        guard let d = try? JSONSerialization.data(withJSONObject: obj),
              let s = String(data: d, encoding: .utf8) else { return }
        print(s); fflush(stdout)
    }
}
func fail(_ code: String, _ msg: String) -> Never {
    emit(["t": "error", "code": code, "msg": msg]); exit(1)
}

let localeId = CommandLine.arguments.dropFirst().first ?? "en-US"

// --- everything below runs off the main thread ------------------------------
let work = DispatchQueue(label: "arslan.voice.work")
final class Ear {
    let recognizer: SFSpeechRecognizer
    let engine = AVAudioEngine()
    var request: SFSpeechAudioBufferRecognitionRequest?
    var task: SFSpeechRecognitionTask?
    var muted = false
    var ending = false
    let lock = NSLock()
    var peak: Float = 0
    var peakFrames = 0
    let mono16: AVAudioFormat
    var converter: AVAudioConverter?
    var monoIn: AVAudioFormat?

    init(recognizer: SFSpeechRecognizer) {
        self.recognizer = recognizer
        mono16 = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false)!
    }

    /// Arm a fresh request. Called at start and after every final.
    func arm() { rearm(after: nil) }

    /// The real implementation. `finishedTask`, when given, is the task
    /// whose completion handler triggered this call — it has already
    /// delivered `isFinal` or an error, so it is done and must never be
    /// cancelled from its own stack.
    ///
    /// Must never run on the recognition callback's own stack: the
    /// callback hands off to `work.async` before calling this, because
    /// `NSLock` is not reentrant and `SFSpeechRecognitionTask.cancel()`
    /// can synchronously re-invoke its own completion handler. Taking
    /// `lock` here while that handler is still on the stack (as `arm()`
    /// used to, calling itself straight from the callback) would try to
    /// lock a lock this same stack already holds and hang forever —
    /// taking every later `endUtterance()`/`setMuted()` down with it,
    /// since stdin's command loop blocks on the same `lock`.
    private func rearm(after finishedTask: SFSpeechRecognitionTask?) {
        lock.lock()
        // Cancel only a task that is still running. One that just
        // finished (isFinal/error already delivered) needs no
        // cancellation, and identity — not nil-ness — is what tells
        // them apart, since `task` still points at it here.
        if let current = task, current !== finishedTask {
            current.cancel()
        }
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
        request = req
        ending = false
        // `newTask` is captured by its own completion handler before this
        // line finishes assigning it — safe because the handler only ever
        // runs later, asynchronously, once `recognitionTask` has returned.
        var newTask: SFSpeechRecognitionTask?
        newTask = recognizer.recognitionTask(with: req) { [weak self] result, error in
            guard let self = self else { return }
            if let r = result {
                let text = r.bestTranscription.formattedString
                if r.isFinal {
                    emit(["t": "final", "text": text])
                    work.async { self.rearm(after: newTask) }
                } else {
                    emit(["t": "partial", "text": text])
                }
            } else if let e = error as NSError? {
                // 1110 = "No speech detected": the request idled out. Silent re-arm.
                if e.code != 1110 {
                    emit(["t": "error", "code": "recognition-failed", "msg": e.localizedDescription])
                }
                work.async { self.rearm(after: newTask) }
            }
        }
        task = newTask
        lock.unlock()
        // Emitted after the lock is released: `emit` blocks on a
        // `DispatchQueue.sync` plus JSON serialisation and a flushed
        // `print`, none of which should happen while other threads are
        // waiting on `lock`.
        emit(["t": "ready"])
    }

    func endUtterance() {
        lock.lock(); defer { lock.unlock() }
        if ending { return }
        ending = true
        request?.endAudio()
    }

    func setMuted(_ m: Bool) {
        lock.lock(); muted = m; lock.unlock()
        emit(["t": "state", "muted": m])
    }

    func start() {
        let input = engine.inputNode
        do { try input.setVoiceProcessingEnabled(true) } catch {
            // Noise suppression is a nicety in V2a (the mic is muted while the
            // reply plays); the plain input is still speech.
            emit(["t": "state", "voiceProcessing": false, "reason": error.localizedDescription])
        }
        let f = input.outputFormat(forBus: 0)
        guard f.sampleRate > 0 else { fail("no-input", "the system reports no usable audio input") }
        let mIn = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: f.sampleRate, channels: 1, interleaved: false)!
        monoIn = mIn
        converter = AVAudioConverter(from: mIn, to: mono16)
        input.installTap(onBus: 0, bufferSize: 1024, format: f) { [weak self] buffer, _ in
            self?.consume(buffer)
        }
        engine.prepare()
        do { try engine.start() } catch { fail("engine-failed", error.localizedDescription) }
        arm()
    }

    private func consume(_ buffer: AVAudioPCMBuffer) {
        guard let ch = buffer.floatChannelData, let mIn = monoIn else { return }
        let n = Int(buffer.frameLength)
        var pk: Float = 0
        for i in 0..<n { pk = max(pk, abs(ch[0][i])) }
        lock.lock()
        let isMuted = muted
        peak = max(peak, pk); peakFrames += n
        // ~100 ms at 48 kHz = 4800 frames
        let flush = peakFrames >= Int(mIn.sampleRate / 10)
        let level = peak
        if flush { peak = 0; peakFrames = 0 }
        let req = request
        lock.unlock()
        if flush && !isMuted { emit(["t": "level", "peak": Double(level)]) }
        if isMuted { return }
        // channel 0 only, then resample — never a 9→1 mix
        let mono = AVAudioPCMBuffer(pcmFormat: mIn, frameCapacity: AVAudioFrameCount(n))!
        mono.frameLength = AVAudioFrameCount(n)
        memcpy(mono.floatChannelData![0], ch[0], n * MemoryLayout<Float>.size)
        if let conv = converter {
            let cap = AVAudioFrameCount(Double(n) * 16000 / mIn.sampleRate) + 16
            let out = AVAudioPCMBuffer(pcmFormat: mono16, frameCapacity: cap)!
            var err: NSError? = nil; var fed = false
            conv.convert(to: out, error: &err) { _, status in
                if fed { status.pointee = .noDataNow; return nil }
                fed = true; status.pointee = .haveData; return mono
            }
            if out.frameLength > 0 { append(out, ifStill: req) }
        } else {
            append(mono, ifStill: req)
        }
    }

    /// The only path that ever calls `SFSpeechAudioBufferRecognitionRequest.append`.
    /// `req` is the request `consume()` saw under `lock` before doing the
    /// (lock-free) channel copy and conversion above; by the time this runs,
    /// `end_utterance` may have called `endAudio()` on it, or `arm()` may
    /// have already replaced it with a new one. Re-checking `!ending` and
    /// `req === request` inside `lock` — right before the append — is what
    /// keeps the tap from ever appending to a request that has already
    /// finished.
    private func append(_ buffer: AVAudioPCMBuffer, ifStill req: SFSpeechAudioBufferRecognitionRequest?) {
        lock.lock(); defer { lock.unlock() }
        guard !ending, let req = req, req === request else { return }
        req.append(buffer)
    }
}

work.async {
    // --- authorization (a refusal is a line, never silence) ---
    let authSem = DispatchSemaphore(value: 0)
    var speechAuth: SFSpeechRecognizerAuthorizationStatus = .notDetermined
    SFSpeechRecognizer.requestAuthorization { s in speechAuth = s; authSem.signal() }
    authSem.wait()
    guard speechAuth == .authorized else { fail("speech-denied", "speech recognition is off for Arslan in System Settings") }
    let micSem = DispatchSemaphore(value: 0); var micOK = false
    AVCaptureDevice.requestAccess(for: .audio) { g in micOK = g; micSem.signal() }
    micSem.wait()
    guard micOK else { fail("mic-denied", "the microphone is off for Arslan in System Settings") }

    guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeId)) else {
        fail("locale-unsupported", "no recognizer for \(localeId)")
    }
    guard recognizer.isAvailable else { fail("recognizer-unavailable", "the recognizer for \(localeId) is not available right now") }

    let ear = Ear(recognizer: recognizer)
    ear.start()

    // --- commands until stdin closes ---
    while let line = readLine(strippingNewline: true) {
        guard let d = line.data(using: .utf8),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let c = o["c"] as? String else { continue }
        switch c {
        case "end_utterance": ear.endUtterance()
        case "mute": ear.setMuted(true)
        case "unmute": ear.setMuted(false)
        default: break
        }
    }
    // stdin closed: the shell is gone or the session ended. Let go of the mic.
    ear.engine.stop()
    exit(0)
}
RunLoop.main.run()
