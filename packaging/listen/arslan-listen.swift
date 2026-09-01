// arslan-listen — turns held-down speech into one line of text.
//
// A separate binary rather than code inside the shell because Speech and
// AVAudioEngine are Swift APIs on a real-time audio thread, and because the
// shell already knows how to own a child process: this one dies the same way
// the sidecar does, when its stdin closes. A force-quit of the app therefore
// cannot leave the microphone held open by an orphan.
//
// It is spawned INSIDE the app bundle, which is what makes it legal: TCC reads
// the usage strings from the bundle's Info.plist, and a child that lives there
// inherits them. Measured — a helper spawned this way prompts under the app
// and does not crash, while the same binary with no usage string in the
// bundle is killed outright by TCC (namespace TCC, "must contain an
// NSMicrophoneUsageDescription key").
//
// Protocol, one JSON object per line on stdout:
//   {"t":"ready"}                      recognizer armed
//   {"t":"partial","text":"..."}       best guess so far
//   {"t":"final","text":"..."}         what it settled on
//   {"t":"error","code":"...","msg":"..."}
// Errors are a line, never a crash: the caller has a text box to fall back to.

import AVFoundation
import Foundation
import Speech

let stdoutQueue = DispatchQueue(label: "arslan.listen.out")

func emit(_ obj: [String: Any]) {
    stdoutQueue.sync {
        guard let d = try? JSONSerialization.data(withJSONObject: obj),
              let s = String(data: d, encoding: .utf8) else { return }
        print(s)
        fflush(stdout)
    }
}

func fail(_ code: String, _ msg: String) -> Never {
    emit(["t": "error", "code": code, "msg": msg])
    exit(1)
}

// The locale is chosen by the caller, which knows what the user is speaking;
// guessing it here would repeat the mistake the reading-aloud feature made,
// where the voice followed the interface language instead of the content.
let localeId = CommandLine.arguments.dropFirst().first ?? "en-US"

// --- releasing the button, watched from the first moment ---------------------
// 🔴 This used to start only AFTER authorization returned, and a real run
// found the hole: while the permission prompt is still on screen the helper
// ignored the release entirely and kept running with the microphone claimed,
// outliving the process that spawned it. Letting go has to mean letting go at
// every stage, including the stage where nothing has been granted yet.
let released = DispatchSemaphore(value: 0)
var releasedFlag = false
let releaseLock = NSLock()
func markReleased() {
    releaseLock.lock(); releasedFlag = true; releaseLock.unlock()
    released.signal()
}
func wasReleased() -> Bool {
    releaseLock.lock(); defer { releaseLock.unlock() }; return releasedFlag
}
DispatchQueue.global().async {
    while FileHandle.standardInput.availableData.count > 0 { }
    markReleased()
}

// --- authorization -----------------------------------------------------------
// Asked for explicitly so a refusal is a message the UI can show, rather than
// silence that looks like a broken microphone.
let authSem = DispatchSemaphore(value: 0)
var speechAuth: SFSpeechRecognizerAuthorizationStatus = .notDetermined
SFSpeechRecognizer.requestAuthorization { s in speechAuth = s; authSem.signal() }
while authSem.wait(timeout: .now() + 0.2) == .timedOut {
    // Released before anyone answered: leave without a word rather than hold
    // the recogniser open behind a prompt nobody is looking at.
    if wasReleased() { emit(["t": "final", "text": ""]); exit(0) }
}
guard speechAuth == .authorized else {
    fail("speech-denied", "speech recognition is off for Arslan in System Settings")
}

let micSem = DispatchSemaphore(value: 0)
var micOK = false
AVCaptureDevice.requestAccess(for: .audio) { g in micOK = g; micSem.signal() }
while micSem.wait(timeout: .now() + 0.2) == .timedOut {
    if wasReleased() { emit(["t": "final", "text": ""]); exit(0) }
}
guard micOK else { fail("mic-denied", "the microphone is off for Arslan in System Settings") }

// --- recognizer --------------------------------------------------------------
guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeId)) else {
    fail("locale-unsupported", "no recognizer for \(localeId)")
}
guard recognizer.isAvailable else {
    fail("recognizer-unavailable", "the recognizer for \(localeId) is not available right now")
}

let request = SFSpeechAudioBufferRecognitionRequest()
request.shouldReportPartialResults = true
// On-device where the locale supports it — measured true for zh-CN and en-US.
// This is not only a latency choice: it keeps what the user says on the
// machine, which is the whole premise of a personal agent.
if recognizer.supportsOnDeviceRecognition {
    request.requiresOnDeviceRecognition = true
}

let engine = AVAudioEngine()
let input = engine.inputNode
let format = input.outputFormat(forBus: 0)
guard format.sampleRate > 0 else {
    fail("no-input", "the system reports no usable audio input")
}

var finished = false
let finishLock = NSLock()
/// Emits the final line exactly once, whichever path gets here first —
/// recognizer callback, stdin EOF, or an error.
func finish(_ text: String?, error: String?) {
    finishLock.lock()
    defer { finishLock.unlock() }
    if finished { return }
    finished = true
    if let e = error {
        emit(["t": "error", "code": "recognition-failed", "msg": e])
    } else {
        emit(["t": "final", "text": text ?? ""])
    }
    engine.stop()
    input.removeTap(onBus: 0)
    exit(error == nil ? 0 : 1)
}

let task = recognizer.recognitionTask(with: request) { result, error in
    if let r = result {
        let text = r.bestTranscription.formattedString
        if r.isFinal {
            finish(text, error: nil)
        } else {
            emit(["t": "partial", "text": text])
        }
    } else if let e = error {
        finish(nil, error: e.localizedDescription)
    }
}

input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
    request.append(buffer)
}

engine.prepare()
do { try engine.start() } catch {
    fail("engine-failed", error.localizedDescription)
}
emit(["t": "ready"])

// --- the release of the key --------------------------------------------------
// Closing our stdin is how the shell says "the user let go". It is the same
// signal that kills us if the app dies, so a crashed app cannot leave the
// microphone running — one mechanism, two jobs.
DispatchQueue.global().async {
    // Either the button is already up (the watcher above fired while we were
    // arming) or we wait here for it.
    if !wasReleased() { released.wait() }
    // Stop feeding audio and let the recognizer settle what it heard; cutting
    // the task off here instead would throw away the last word.
    engine.stop()
    input.removeTap(onBus: 0)
    request.endAudio()
    // If the recognizer never comes back, do not hang holding the microphone.
    DispatchQueue.global().asyncAfter(deadline: .now() + 8) {
        finish(nil, error: "the recognizer did not return after the audio ended")
    }
}

withExtendedLifetime(task) { RunLoop.main.run() }
