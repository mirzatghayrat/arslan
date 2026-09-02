# Realtime Voice V2a (half-duplex always-on conversation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "conversation mode" toggle: the mic stays open, each finished utterance is sent as an ordinary user message without touching the keyboard, and the mic is muted while Arslan reads its reply aloud (half-duplex, no echo cancellation needed yet).

**Architecture:** A new long-lived Swift helper (`arslan-voice`) owns the microphone and `SFSpeechRecognizer`, and only reports what it hears (partials, finals, a 100 ms level meter). Endpoint policy ("has the user finished a sentence?") is a pure Rust struct in the Tauri shell, driven by the helper's stream and unit-tested with `cargo test`. The frontend turns a `final` into the same `onSendMessage` call typing uses, and mutes the helper while the Web Speech speaker is active. The tool loop is untouched.

**Tech Stack:** Swift (AVFoundation, Speech) helper · Rust/Tauri 2 shell (serde_json already a dep) · React/TypeScript frontend (zustand, vitest) · FastAPI settings (pydantic).

## Global Constraints

Copied from the spec (`docs/specs/2026-09-02-realtime-voice-v2-build.md`) and the project's standing rules:

- **The tool loop is not touched.** A voice final becomes `onSendMessage(text)` — byte-identical to typing + Enter.
- **Decision ① = B:** speech output stays the Web Speech speaker in `web/src/lib/speech.ts`. No `AVSpeechSynthesizer` in the helper.
- **Decision ②:** V2a is half-duplex: while the speaker is active the helper is MUTED. No AEC, no barge-in in this plan.
- **Decision ③:** a reply in flight is never cancelled by voice.
- **Endpoint = audio silence**, not partial staleness (measured: on-device partials update sparsely; "partial unchanged 900 ms" split one sentence in two). Rule: a partial exists AND `now − last_voice_above_threshold ≥ voice_endpoint_silence_ms` (default `900`).
- **Measured constants** (probe run 2026-09-03, built-in mic): idle peak 0.005–0.016, human speech 0.15–0.75. `VOICE_PEAK_THRESHOLD = 0.04`.
- **Voice processing on, channel 0 only, resampled to 16 kHz mono** before the recognizer. Never let `AVAudioConverter` mix 9 channels into 1.
- **Helper main thread must stay free** (`RunLoop.main.run()`); Speech callbacks are delivered on the main queue.
- **`SFSpeechRecognizer` error 1110 "No speech detected" is not an error** — re-arm silently.
- **Every new Tauri command = three places:** `generate_handler!`, `build.rs` `commands(&[...])`, capability `permissions` (`allow-<cmd-with-dashes>`). `tests/server/test_tauri_command_acl_lockstep.py` derives the check; regenerate `gen/schemas` with `cargo build` and commit it.
- **Every new setting key = seven places:** `server/schemas.py` (`SettingsIn` AND `SettingsOut`), `server/services/settings_service.py` `_PLAIN_KEYS`, `web/src/api/client.types.ts`, `web/src/api/adapters.ts` (read AND write), `web/src/data.ts`, `web/src/types.ts`, plus `web/src/__tests__/settings-put-carries-only-what-was-touched.test.ts` `uiNameFor`, the three AdvancedSection prop fixtures, and all six locales (`locale-parity.test.ts`).
- New settings: `voice_mode` ∈ `off | push_to_talk | conversation`, default `push_to_talk`; `voice_endpoint_silence_ms`, default `900`. `voice_barge_in` is V2b — do NOT add it.
- The new helper binary lives in `desktop/src-tauri/binaries/listen/` next to `arslan-listen`, so `tauri.conf.json` `resources` and the two `mkdir` lines in `.github/workflows/ci.yml` do not change.
- No hardcoded CJK in `web/src` non-test code (the `no-hardcoded-cjk` guard); user-facing strings go through i18n keys in all six locales.
- Local verification is CI-parity: `ARSLAN_SECRET_KEY=ci-secret ARSLAN_API_TOKEN="" ARSLAN_DATA_DIR=data .venv/bin/pytest tests/ -q`, `npx vitest run`, `npx tsc --noEmit`, `cargo fmt --check`, `cargo test`, `cargo clippy --all-targets -- -D warnings` (with `mkdir -p desktop/src-tauri/binaries/sidecar desktop/src-tauri/binaries/listen` first).
- Work in a dedicated worktree `Arslan/wt-107` on branch `feat/voice-v2a` from `origin/main`; absolute paths in every command; `rtk proxy git` for git.

---

## File structure

| File | Responsibility |
|---|---|
| `packaging/listen/arslan-voice.swift` (new) | Long-lived mic + recognizer helper. Commands in on stdin, events out on stdout. Reports; never decides. |
| `packaging/build_dmg.sh` (modify) | Compile + sign the second helper next to the first. |
| `.github/workflows/ci.yml` (modify, macos job) | `swiftc -typecheck` both helpers — Swift is compiled nowhere in CI today. |
| `desktop/src-tauri/src/endpoint.rs` (new) | `Endpointer`: pure, no I/O. The only place "finished speaking" is defined. |
| `desktop/src-tauri/src/voice.rs` (new) | `Conversation` state + four commands; reader thread feeds `Endpointer`, writes `end_utterance` back, forwards every line on `voice://conv`. |
| `desktop/src-tauri/src/lib.rs` (modify) | `mod`, `.manage`, `generate_handler!`. |
| `desktop/src-tauri/build.rs`, `capabilities/remote-ui-drag.json`, `gen/schemas/*`, `permissions/autogenerated/*` (modify/regenerate) | ACL for the four new commands. |
| `web/src/lib/voiceLine.ts` (new) | `Line` union + `parseLine` + `errorMessage`, shared by hold-to-talk and conversation. `PushToTalk.tsx` re-exports them so nothing else moves. |
| `web/src/lib/speech.ts` (modify) | `createSpeaker` reports whether it is currently speaking (utterance `onend`/`onerror` bookkeeping). |
| `web/src/stores/arslanStore.ts` (modify) | New state `speaking: boolean`, set from the speaker. |
| `web/src/hooks/useConversationMode.ts` (new) | Owns the Tauri session: start/stop, `voice://conv` subscription, mute while speaking, `onFinal`. |
| `web/src/components/ConversationToggle.tsx` (new) | The button + status pill. Pure presentation over the hook's state. |
| `web/src/components/OrchestratorChat.tsx` (modify) | Mode switch in BOTH composers; final → `onSendMessage`. |
| Settings lockstep files (listed in constraints) | `voiceMode`, `voiceEndpointSilenceMs`. |
| `web/src/locales/{en,zh,ja,de,fr,es}.json` (modify) | `voice.conversation*` keys + two settings labels/descriptions. |

---

### Task 1: The endpointer — a pure Rust struct

**Files:**
- Create: `desktop/src-tauri/src/endpoint.rs`
- Modify: `desktop/src-tauri/src/lib.rs:18` (add `mod endpoint;` under `mod listen;`)

**Interfaces:**
- Produces: `pub struct Endpointer`, `Endpointer::new(silence_ms: u64) -> Endpointer`, `fn on_partial(&mut self, text: &str, now_ms: u64)`, `fn on_level(&mut self, peak: f32, now_ms: u64)`, `fn should_end(&self, now_ms: u64) -> bool`, `fn reset(&mut self)`, `pub const VOICE_PEAK_THRESHOLD: f32 = 0.04`.

- [ ] **Step 1: Write the failing tests**

Create `desktop/src-tauri/src/endpoint.rs` with ONLY the test module first:

```rust
//! When has the user finished a sentence?
//!
//! Measured on 2026-09-03 (built-in mic, voice processing on): idle peak
//! 0.005–0.016, human speech 0.15–0.75. And measured the other way: the
//! on-device recogniser updates its partial sparsely, so "the partial has not
//! changed for 900 ms" is NOT silence — it split one continuous sentence in
//! two. The rule here is therefore audio silence, gated on a partial existing
//! at all, so breathing and chair creaks never send a message.

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nothing_heard_never_ends() {
        let mut e = Endpointer::new(900);
        e.on_level(0.5, 0);
        e.on_level(0.0, 100);
        assert!(!e.should_end(5_000), "no partial exists: a noise burst must not send");
    }

    #[test]
    fn ends_after_silence_once_a_partial_exists() {
        let mut e = Endpointer::new(900);
        e.on_level(0.3, 0);
        e.on_partial("open the", 400);
        e.on_level(0.3, 500);
        e.on_level(0.01, 600);
        assert!(!e.should_end(1_300), "only 800 ms of silence");
        assert!(e.should_end(1_400), "900 ms of silence after the last voice");
    }

    #[test]
    fn a_partial_arriving_after_the_voice_stopped_does_not_restart_the_clock() {
        // The recogniser lags 0.9–2.5 s. Its late partial is about audio that
        // is already in the request; waiting another 900 ms after it would add
        // that lag to every turn.
        let mut e = Endpointer::new(900);
        e.on_level(0.3, 0);
        e.on_level(0.01, 100);
        e.on_partial("hello", 1_500);
        assert!(e.should_end(1_500));
    }

    #[test]
    fn voice_below_the_threshold_is_silence() {
        let mut e = Endpointer::new(900);
        e.on_level(0.3, 0);
        e.on_partial("x", 50);
        e.on_level(VOICE_PEAK_THRESHOLD - 0.001, 100);
        assert!(e.should_end(900));
        let mut f = Endpointer::new(900);
        f.on_level(0.3, 0);
        f.on_partial("x", 50);
        f.on_level(VOICE_PEAK_THRESHOLD, 800);
        assert!(!f.should_end(900), "a peak AT the threshold counts as voice");
    }

    #[test]
    fn an_empty_partial_does_not_count_as_text() {
        let mut e = Endpointer::new(900);
        e.on_level(0.3, 0);
        e.on_partial("", 100);
        e.on_partial("   ", 200);
        assert!(!e.should_end(5_000));
    }

    #[test]
    fn reset_forgets_everything() {
        let mut e = Endpointer::new(900);
        e.on_level(0.3, 0);
        e.on_partial("done", 100);
        assert!(e.should_end(2_000));
        e.reset();
        assert!(!e.should_end(2_000));
    }
}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && mkdir -p desktop/src-tauri/binaries/sidecar desktop/src-tauri/binaries/listen && cargo test --manifest-path desktop/src-tauri/Cargo.toml endpoint 2>&1 | tail -5
```

Expected: compile error `cannot find type Endpointer` (and `mod endpoint;` must be in lib.rs for the file to be compiled at all — add it now: after `mod listen;` on line 18 insert `mod endpoint;`).

- [ ] **Step 3: Write the implementation** (above the test module in the same file)

```rust
/// Peak (absolute sample value on channel 0, 0..1) at or above which a 100 ms
/// window counts as the user's voice. Measured: idle ≤ 0.016, speech ≥ 0.15.
pub const VOICE_PEAK_THRESHOLD: f32 = 0.04;

#[derive(Debug)]
pub struct Endpointer {
    silence_ms: u64,
    has_text: bool,
    last_voice_ms: Option<u64>,
}

impl Endpointer {
    pub fn new(silence_ms: u64) -> Self {
        Self { silence_ms, has_text: false, last_voice_ms: None }
    }

    /// A partial transcript arrived. Only its non-emptiness matters: it gates
    /// sending, it does not time anything (see the module comment).
    pub fn on_partial(&mut self, text: &str, _now_ms: u64) {
        if !text.trim().is_empty() {
            self.has_text = true;
        }
    }

    /// One level report from the helper.
    pub fn on_level(&mut self, peak: f32, now_ms: u64) {
        if peak >= VOICE_PEAK_THRESHOLD {
            self.last_voice_ms = Some(now_ms);
        }
    }

    /// Something was said, and nothing has been said for `silence_ms`.
    pub fn should_end(&self, now_ms: u64) -> bool {
        match (self.has_text, self.last_voice_ms) {
            (true, Some(t)) => now_ms.saturating_sub(t) >= self.silence_ms,
            _ => false,
        }
    }

    /// A new recogniser request was armed: start over.
    pub fn reset(&mut self) {
        self.has_text = false;
        self.last_voice_ms = None;
    }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && cargo test --manifest-path desktop/src-tauri/Cargo.toml endpoint 2>&1 | grep -E "test result|FAILED|panicked"
```

Expected: `test result: ok. 6 passed`.

- [ ] **Step 5: Mutation check** (mandatory in this repo)

Change `>=` to `>` in `on_level`, run — `voice_below_the_threshold_is_silence` must fail. Change `should_end` to ignore `has_text` — `nothing_heard_never_ends` must fail. Restore the file from the committed version of your edit buffer (not `git checkout`).

- [ ] **Step 6: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && rtk proxy git add desktop/src-tauri/src/endpoint.rs desktop/src-tauri/src/lib.rs && rtk proxy git commit -m "voice: the endpointer — silence after a partial, measured thresholds"
```

---

### Task 2: The long-lived helper `arslan-voice`

**Files:**
- Create: `packaging/listen/arslan-voice.swift`
- Test: no unit test harness for Swift in this repo. This task's gate is (a) `swiftc -typecheck`, (b) a protocol smoke run from a signed probe bundle (Step 4), (c) the real-device acceptance in Task 10.

**Interfaces:**
- Produces (stdout, one JSON object per line): `{"t":"ready"}` each time a request is armed · `{"t":"partial","text":…}` · `{"t":"final","text":…}` · `{"t":"level","peak":0.123}` every ~100 ms while unmuted · `{"t":"state","muted":true|false}` · `{"t":"error","code":…,"msg":…}`. Error codes: the seven from `arslan-listen` (`speech-denied`, `mic-denied`, `locale-unsupported`, `recognizer-unavailable`, `no-input`, `engine-failed`, `recognition-failed`).
- Consumes (stdin, one JSON object per line): `{"c":"end_utterance"}` · `{"c":"mute"}` · `{"c":"unmute"}`. stdin EOF = exit. First positional argument = BCP-47 locale.

- [ ] **Step 1: Write the helper**

```swift
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
    func arm() {
        lock.lock(); defer { lock.unlock() }
        task?.cancel()
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
        request = req
        ending = false
        task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            guard let self = self else { return }
            if let r = result {
                let text = r.bestTranscription.formattedString
                if r.isFinal {
                    emit(["t": "final", "text": text])
                    self.arm()
                } else {
                    emit(["t": "partial", "text": text])
                }
            } else if let e = error as NSError? {
                // 1110 = "No speech detected": the request idled out. Silent re-arm.
                if e.code != 1110 {
                    emit(["t": "error", "code": "recognition-failed", "msg": e.localizedDescription])
                }
                self.arm()
            }
        }
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
            if out.frameLength > 0 { req?.append(out) }
        } else {
            req?.append(mono)
        }
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
```

- [ ] **Step 2: Typecheck**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && swiftc -typecheck packaging/listen/arslan-voice.swift && echo typecheck-ok
```

Expected: `typecheck-ok` (warnings about `@Sendable` are acceptable; errors are not).

- [ ] **Step 3: Compile it where the app will look for it**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && mkdir -p desktop/src-tauri/binaries/listen && swiftc -O -o desktop/src-tauri/binaries/listen/arslan-voice packaging/listen/arslan-voice.swift && test -x desktop/src-tauri/binaries/listen/arslan-voice && echo built
```

- [ ] **Step 4: Protocol smoke from a signed bundle** (TCC is real only under `open`)

Copy the probe scaffolding: `packaging/probes/voice/build.sh` shows how a minimal `.app` with the two usage strings is made and ad-hoc signed. Build a `VoiceSmoke.app` whose executable is a shell script that runs `arslan-voice zh-CN` with stdin from a FIFO and stdout to a log, then:

```bash
# in one terminal: open the app; in another, drive its FIFO
printf '{"c":"mute"}\n' > /tmp/voice.fifo; sleep 1; printf '{"c":"unmute"}\n' > /tmp/voice.fifo
# speak a sentence, then:
printf '{"c":"end_utterance"}\n' > /tmp/voice.fifo
```

Expected in the log, in order: `ready` · `level` lines (absent while muted) · `state` lines · `partial` · `final` with your sentence · `ready` again. Closing the FIFO ends the process. Record the log path in the commit message. If TCC prompts appear, answer them once; the bundle id must stay the same across runs.

- [ ] **Step 5: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && rtk proxy git add packaging/listen/arslan-voice.swift && rtk proxy git commit -m "voice: arslan-voice, the long-lived ear — reports partials, finals and level; decides nothing"
```

---

### Task 3: The shell: `voice.rs` commands and the reader thread

**Files:**
- Create: `desktop/src-tauri/src/voice.rs`
- Modify: `desktop/src-tauri/src/lib.rs:18` (add `mod voice;`), `:722` (add `.manage(voice::Conversation::default())`), `:723-729` (add the four commands to `generate_handler!`)
- Modify: `desktop/src-tauri/build.rs:11-17` (add the four names), `desktop/src-tauri/capabilities/remote-ui-drag.json` (add four `allow-…`)
- Regenerate: `desktop/src-tauri/gen/schemas/*`, `desktop/src-tauri/permissions/autogenerated/*` (via `cargo build`)
- Test: `desktop/src-tauri/src/voice.rs` (unit tests for line parsing and the drive loop) + `tests/server/test_tauri_command_acl_lockstep.py` (already exists; must stay green)

**Interfaces:**
- Consumes: `endpoint::Endpointer` (Task 1), helper protocol (Task 2).
- Produces Tauri commands: `voice_conversation_start(locale: String, silence_ms: u64) -> Result<(), String>`, `voice_conversation_stop() -> Result<(), String>`, `voice_mute() -> Result<(), String>`, `voice_unmute() -> Result<(), String>`. Event channel `voice://conv`, payload = the helper's raw line (string), plus one shell-made line `{"t":"ended"}` when the helper exits.
- Produces (pub for tests): `pub enum HelperLine { Ready, Partial(String), Final(String), Level(f32), Other }`, `pub fn parse_helper_line(s: &str) -> HelperLine`, `pub fn drive(ep: &mut Endpointer, line: &HelperLine, now_ms: u64) -> bool` (true = write `end_utterance` now).

- [ ] **Step 1: Write the failing tests** (bottom of the new `voice.rs`)

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::endpoint::Endpointer;

    #[test]
    fn parses_the_lines_that_drive_the_endpointer() {
        assert!(matches!(parse_helper_line(r#"{"t":"ready"}"#), HelperLine::Ready));
        assert!(matches!(parse_helper_line(r#"{"t":"partial","text":"hi"}"#), HelperLine::Partial(t) if t == "hi"));
        assert!(matches!(parse_helper_line(r#"{"t":"final","text":"hi there"}"#), HelperLine::Final(t) if t == "hi there"));
        assert!(matches!(parse_helper_line(r#"{"t":"level","peak":0.25}"#), HelperLine::Level(p) if (p - 0.25).abs() < 1e-6));
        assert!(matches!(parse_helper_line(r#"{"t":"state","muted":true}"#), HelperLine::Other));
        assert!(matches!(parse_helper_line("not json"), HelperLine::Other));
        assert!(matches!(parse_helper_line(r#"{"t":"partial"}"#), HelperLine::Other), "a partial without text is not a partial");
    }

    #[test]
    fn drive_asks_to_end_exactly_once_per_utterance() {
        let mut ep = Endpointer::new(900);
        assert!(!drive(&mut ep, &HelperLine::Ready, 0));
        assert!(!drive(&mut ep, &HelperLine::Level(0.5), 100));
        assert!(!drive(&mut ep, &HelperLine::Partial("open".into()), 300));
        assert!(!drive(&mut ep, &HelperLine::Level(0.01), 400));
        assert!(!drive(&mut ep, &HelperLine::Level(0.01), 1_200));
        assert!(drive(&mut ep, &HelperLine::Level(0.01), 1_300), "900 ms after the last voice");
        // Until the helper re-arms (Ready), the same silence must not ask again.
        assert!(!drive(&mut ep, &HelperLine::Level(0.01), 1_400));
        assert!(!drive(&mut ep, &HelperLine::Final("open".into()), 1_500));
        // Ready resets: a new utterance starts from nothing.
        assert!(!drive(&mut ep, &HelperLine::Ready, 1_600));
        assert!(!drive(&mut ep, &HelperLine::Level(0.01), 3_000));
    }

    #[test]
    fn the_event_name_is_the_one_the_webview_listens_on() {
        assert_eq!(EVENT, "voice://conv");
    }
}
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && cargo test --manifest-path desktop/src-tauri/Cargo.toml voice 2>&1 | tail -3
```

Expected: compile errors (`parse_helper_line`, `drive`, `EVENT` missing). Add `mod voice;` to `lib.rs` first so the file compiles.

- [ ] **Step 3: Implement** (top of `voice.rs`)

```rust
//! Conversation mode: a long-lived ear, and the one decision the shell makes.
//!
//! The helper (`arslan-voice`) reports partials, finals and a level meter.
//! This module feeds those into `endpoint::Endpointer` and, when it says the
//! sentence is over, writes `end_utterance` back to the helper — which then
//! emits the final and re-arms. Every helper line is also forwarded verbatim
//! to the webview on `voice://conv`, errors included.

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use tauri::{AppHandle, Emitter, Manager};

use crate::endpoint::Endpointer;

pub const EVENT: &str = "voice://conv";

#[derive(Default)]
pub struct Conversation {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<Arc<Mutex<ChildStdin>>>>,
}

pub enum HelperLine {
    Ready,
    Partial(String),
    Final(String),
    Level(f32),
    Other,
}

pub fn parse_helper_line(s: &str) -> HelperLine {
    let v: serde_json::Value = match serde_json::from_str(s) {
        Ok(v) => v,
        Err(_) => return HelperLine::Other,
    };
    match v.get("t").and_then(|t| t.as_str()) {
        Some("ready") => HelperLine::Ready,
        Some("partial") => match v.get("text").and_then(|t| t.as_str()) {
            Some(t) => HelperLine::Partial(t.to_string()),
            None => HelperLine::Other,
        },
        Some("final") => match v.get("text").and_then(|t| t.as_str()) {
            Some(t) => HelperLine::Final(t.to_string()),
            None => HelperLine::Other,
        },
        Some("level") => match v.get("peak").and_then(|p| p.as_f64()) {
            Some(p) => HelperLine::Level(p as f32),
            None => HelperLine::Other,
        },
        _ => HelperLine::Other,
    }
}

/// Feed one line into the endpointer. Returns true when `end_utterance`
/// should be written — at most once per armed request: after it fires, the
/// endpointer is put into a state that cannot fire again until `Ready`.
pub fn drive(ep: &mut Endpointer, line: &HelperLine, now_ms: u64) -> bool {
    match line {
        HelperLine::Ready => {
            ep.reset();
            false
        }
        HelperLine::Partial(t) => {
            ep.on_partial(t, now_ms);
            fire_if_due(ep, now_ms)
        }
        HelperLine::Level(p) => {
            ep.on_level(*p, now_ms);
            fire_if_due(ep, now_ms)
        }
        HelperLine::Final(_) | HelperLine::Other => false,
    }
}

fn fire_if_due(ep: &mut Endpointer, now_ms: u64) -> bool {
    if ep.should_end(now_ms) {
        // Consume: no second fire until the helper re-arms.
        ep.reset();
        true
    } else {
        false
    }
}

fn helper_path(app: &AppHandle) -> Result<std::path::PathBuf, String> {
    app.path()
        .resolve("listen/arslan-voice", tauri::path::BaseDirectory::Resource)
        .map_err(|e| format!("cannot locate the voice helper: {e}"))
}

fn write_cmd(stdin: &Arc<Mutex<ChildStdin>>, cmd: &str) -> Result<(), String> {
    let mut s = stdin.lock().unwrap();
    writeln!(s, "{{\"c\":\"{cmd}\"}}").and_then(|_| s.flush()).map_err(|e| format!("voice helper stdin: {e}"))
}

#[tauri::command]
pub fn voice_conversation_start(app: AppHandle, locale: String, silence_ms: u64) -> Result<(), String> {
    let state = app.state::<Conversation>();
    stop_inner(&app);

    let exe = helper_path(&app)?;
    if !exe.exists() {
        return Err(format!("the voice helper is missing from the bundle at {}", exe.display()));
    }
    let mut child = Command::new(&exe)
        .arg(&locale)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("cannot start the voice helper: {e}"))?;
    let stdout = child.stdout.take().ok_or_else(|| "the voice helper has no stdout".to_string())?;
    let stdin = Arc::new(Mutex::new(
        child.stdin.take().ok_or_else(|| "the voice helper has no stdin".to_string())?,
    ));

    let handle = app.clone();
    let writer = stdin.clone();
    std::thread::spawn(move || {
        let t0 = Instant::now();
        let mut ep = Endpointer::new(silence_ms);
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if line.trim().is_empty() {
                continue;
            }
            let now = t0.elapsed().as_millis() as u64;
            if drive(&mut ep, &parse_helper_line(&line), now) {
                let _ = write_cmd(&writer, "end_utterance");
            }
            let _ = handle.emit(EVENT, line);
        }
        let _ = handle.emit(EVENT, r#"{"t":"ended"}"#.to_string());
    });

    *state.child.lock().unwrap() = Some(child);
    *state.stdin.lock().unwrap() = Some(stdin);
    Ok(())
}

#[tauri::command]
pub fn voice_conversation_stop(app: AppHandle) -> Result<(), String> {
    stop_inner(&app);
    Ok(())
}

#[tauri::command]
pub fn voice_mute(app: AppHandle) -> Result<(), String> {
    with_stdin(&app, "mute")
}

#[tauri::command]
pub fn voice_unmute(app: AppHandle) -> Result<(), String> {
    with_stdin(&app, "unmute")
}

fn with_stdin(app: &AppHandle, cmd: &str) -> Result<(), String> {
    let state = app.state::<Conversation>();
    let guard = state.stdin.lock().unwrap();
    match guard.as_ref() {
        Some(s) => write_cmd(s, cmd),
        None => Err("conversation mode is not running".to_string()),
    }
}

/// Dropping stdin is the stop signal (EOF); the helper releases the mic and
/// exits, and the reader thread ends with it.
fn stop_inner(app: &AppHandle) {
    let state = app.state::<Conversation>();
    state.stdin.lock().unwrap().take();
    if let Some(mut c) = state.child.lock().unwrap().take() {
        std::thread::spawn(move || {
            let _ = c.wait();
        });
    }
}
```

Then in `lib.rs`: line 18 → add `mod voice;` (next to `mod endpoint;`); after `.manage(listen::Listener::default())` add `.manage(voice::Conversation::default())`; in `generate_handler!` append `voice::voice_conversation_start, voice::voice_conversation_stop, voice::voice_mute, voice::voice_unmute`.

In `build.rs` add to the array: `"voice_conversation_start", "voice_conversation_stop", "voice_mute", "voice_unmute"`.

In `capabilities/remote-ui-drag.json` `permissions` append: `"allow-voice-conversation-start", "allow-voice-conversation-stop", "allow-voice-mute", "allow-voice-unmute"`.

- [ ] **Step 4: Regenerate the ACL artefacts and run everything Rust**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && mkdir -p desktop/src-tauri/binaries/sidecar desktop/src-tauri/binaries/listen && cargo build --manifest-path desktop/src-tauri/Cargo.toml 2>&1 | tail -1 && cargo fmt --manifest-path desktop/src-tauri/Cargo.toml && cargo test --manifest-path desktop/src-tauri/Cargo.toml 2>&1 | grep -E "test result" && cargo clippy --manifest-path desktop/src-tauri/Cargo.toml --all-targets -- -D warnings 2>&1 | tail -1 && /bin/ls desktop/src-tauri/permissions/autogenerated/
```

Expected: tests `ok` (endpoint 6 + voice 3 + existing), clippy clean, and four new `voice_*.toml` files.

- [ ] **Step 5: The ACL lockstep guard stays green**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && .venv/bin/pytest tests/server/test_tauri_command_acl_lockstep.py -q
```

Expected: `4 passed`. (Red here means one of the three places was missed — fix the place, not the test.)

- [ ] **Step 6: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && rtk proxy git add desktop/src-tauri/src/voice.rs desktop/src-tauri/src/lib.rs desktop/src-tauri/build.rs desktop/src-tauri/capabilities/remote-ui-drag.json desktop/src-tauri/gen/schemas desktop/src-tauri/permissions/autogenerated && rtk proxy git commit -m "voice: conversation commands — the shell drives the endpointer and forwards every line"
```

---

### Task 4: Frontend plumbing — `voiceLine.ts`, a speaker that says when it is speaking, `speaking` in the store

**Files:**
- Create: `web/src/lib/voiceLine.ts`
- Modify: `web/src/components/PushToTalk.tsx:20-65` (import + re-export instead of defining)
- Modify: `web/src/lib/speech.ts:200-231` (`createSpeaker` gains an `onActive` hook)
- Modify: `web/src/stores/arslanStore.ts` (`speaking` state; `_voiceStart` passes the hook)
- Test: `web/src/__tests__/voice-line.test.ts` (new), `web/src/__tests__/speech.test.ts` (extend), `web/src/__tests__/push-to-talk.test.ts` (must stay green unchanged)

**Interfaces:**
- Produces: `export type Line = {t:'ready'} | {t:'partial';text:string} | {t:'final';text:string} | {t:'level';peak:number} | {t:'state';muted?:boolean} | {t:'ended'} | {t:'error';code:string;msg:string}`; `parseLine(raw: string): Line | null`; `errorMessage(code, fallback, t)` (moved verbatim).
- Produces: `createSpeaker(hint: string, hooks?: { onActive?: (active: boolean) => void })` — `onActive(true)` when the first utterance starts, `onActive(false)` when the last one ends, errors, or `cancel()`.
- Produces: store state `speaking: boolean` (data-only, initial `false`).

- [ ] **Step 1: Write the failing tests**

`web/src/__tests__/voice-line.test.ts`:

```ts
/**
 * One parser for both helpers. Conversation mode adds three line kinds the
 * hold-to-talk helper never sends; the shape check must still reject JSON
 * that is not ours.
 */
import { describe, test, expect } from "vitest";
import { parseLine } from "../lib/voiceLine";

describe("parseLine (shared)", () => {
  test("reads the conversation-only kinds", () => {
    expect(parseLine('{"t":"level","peak":0.2}')).toEqual({ t: "level", peak: 0.2 });
    expect(parseLine('{"t":"state","muted":true}')).toEqual({ t: "state", muted: true });
    expect(parseLine('{"t":"ended"}')).toEqual({ t: "ended" });
  });
  test("still rejects foreign JSON and fragments", () => {
    expect(parseLine('{"hello":"world"}')).toBeNull();
    expect(parseLine('{"t":"lev')).toBeNull();
  });
});
```

Append to `web/src/__tests__/speech.test.ts` (inside the file, after the existing "the speaker picks a voice per sentence" block; reuse its `stubSynth`/`voice` helpers):

```ts
describe("the speaker says when it is speaking", () => {
  test("active from the first utterance until the last one ends", async () => {
    const { synth } = stubSynth([voice("en-US")]);
    const started: any[] = [];
    synth.speak = (u: any) => started.push(u);       // capture, do not auto-end
    const seen: boolean[] = [];
    const sp = createSpeaker("en-US", { onActive: (a) => seen.push(a) });
    await sp.feed("One. Two.");
    expect(seen).toEqual([true]);                     // once, not per sentence
    started[0].onend?.();
    expect(seen).toEqual([true]);                     // still one pending
    started[1].onend?.();
    expect(seen).toEqual([true, false]);
  });

  test("cancel() ends the active state even with utterances pending", async () => {
    const { synth } = stubSynth([voice("en-US")]);
    synth.speak = () => {};
    const seen: boolean[] = [];
    const sp = createSpeaker("en-US", { onActive: (a) => seen.push(a) });
    await sp.feed("Never finishes.");
    sp.cancel();
    expect(seen).toEqual([true, false]);
  });

  test("an utterance error counts as ended", async () => {
    const { synth } = stubSynth([voice("en-US")]);
    const started: any[] = [];
    synth.speak = (u: any) => started.push(u);
    const seen: boolean[] = [];
    const sp = createSpeaker("en-US", { onActive: (a) => seen.push(a) });
    await sp.feed("Oops.");
    started[0].onerror?.();
    expect(seen).toEqual([true, false]);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107/web && npx vitest run src/__tests__/voice-line.test.ts src/__tests__/speech.test.ts 2>&1 | grep -E "×|failed|passed" | head
```

Expected: voice-line fails to import (`../lib/voiceLine` missing); the three new speech tests fail (`onActive` never called).

- [ ] **Step 3: Implement**

`web/src/lib/voiceLine.ts`:

```ts
/**
 * The line protocol both voice helpers speak: one JSON object per line over a
 * pipe, forwarded verbatim by the shell as a Tauri event payload.
 *
 * Hold-to-talk (`arslan-listen`) sends ready/partial/final/error. Conversation
 * mode (`arslan-voice`) adds level/state, and the shell adds `ended` when the
 * helper exits. One parser, so a half-written line or a stray log line is
 * ignored the same way on both paths, never thrown.
 */
export type Line =
  | { t: 'ready' }
  | { t: 'partial'; text: string }
  | { t: 'final'; text: string }
  | { t: 'level'; peak: number }
  | { t: 'state'; muted?: boolean }
  | { t: 'ended' }
  | { t: 'error'; code: string; msg: string };

export function parseLine(raw: string): Line | null {
  try {
    const o = JSON.parse(raw);
    if (o && typeof o.t === 'string') return o as Line;
  } catch {
    /* a partial write or a stray log line is not worth a crash */
  }
  return null;
}

/** Turn an error code from a helper into something worth reading. */
export function errorMessage(code: string, fallback: string, t: (k: string) => string): string {
  switch (code) {
    case 'mic-denied':
    case 'speech-denied':
      return t('voice.errDenied');
    case 'mic-auth-timeout':
    case 'speech-auth-timeout':
      return t('voice.errNoAnswer');
    case 'locale-unsupported':
      return t('voice.errLocale');
    case 'no-input':
      return t('voice.errNoInput');
    default:
      return fallback;
  }
}
```

In `PushToTalk.tsx`: delete lines 20–24 (`type Line`), 38–47 (`parseLine`) and 49–65 (`errorMessage`); add after the lucide import:

```ts
import { parseLine, errorMessage } from '../lib/voiceLine';
export { parseLine, errorMessage };   // push-to-talk.test.ts imports them from here
```

In `speech.ts`, replace `createSpeaker`:

```ts
export function createSpeaker(hint: string, hooks: { onActive?: (active: boolean) => void } = {}) {
  const feeder = createSentenceFeeder();
  const enabled = speechSupported();
  const ready = enabled ? loadVoices() : Promise.resolve([]);
  let cancelled = false;
  // How many utterances the engine still owes us an `end` for. Crossing 0→1
  // and 1→0 is what the conversation mode's microphone gate listens to.
  let pending = 0;
  function setPending(n: number) {
    const was = pending > 0;
    pending = n;
    const now = pending > 0;
    if (was !== now) hooks.onActive?.(now);
  }

  function say(sentence: string): Promise<void> {
    if (!sentence) return Promise.resolve();
    return ready.then((voices) => {
      if (cancelled) return;
      const u = new SpeechSynthesisUtterance(sentence);
      u.lang = utteranceLangFor(sentence, hint);
      const v = pickVoice(voices, u.lang);
      if (v) u.voice = v;
      const done = () => { if (!cancelled) setPending(pending - 1); };
      u.onend = done;
      u.onerror = done;
      setPending(pending + 1);
      window.speechSynthesis.speak(u);
    });
  }

  return {
    async feed(chunk: string) {
      if (!enabled) return;
      for (const s of feeder.push(chunk)) await say(s);
    },
    async end() {
      if (!enabled) return;
      for (const s of feeder.flush()) await say(s);
    },
    cancel() {
      cancelled = true;
      if (enabled) window.speechSynthesis.cancel();
      setPending(0);
    },
  };
}
```

In `arslanStore.ts`: in `interface ArslanState` (line 6 area) add `speaking: boolean;` with the comment `// The Web Speech speaker owes the engine at least one utterance end. Conversation mode mutes the microphone while this is true.`; in `initialData()` add `speaking: false,`; change `_voiceStart`:

```ts
function _voiceStart() {
  if (_speaker) _speaker.cancel();
  _speaker = _voiceEnabled
    ? createSpeaker(_voiceLang, { onActive: (a) => useArslanStore.setState({ speaking: a }) })
    : null;
}
```

(`useArslanStore` is defined lower in the same file; a function body referencing it is fine.)

- [ ] **Step 4: Run to verify they pass, plus the untouched neighbours**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107/web && npx vitest run src/__tests__/voice-line.test.ts src/__tests__/speech.test.ts src/__tests__/push-to-talk.test.ts 2>&1 | grep -E "Tests|failed" && npx tsc --noEmit && echo tsc-ok
```

Expected: all pass, `tsc-ok`.

- [ ] **Step 5: Mutation check**

In `say`, remove `setPending(pending + 1)` → the first new speech test fails. In `cancel`, remove `setPending(0)` → the cancel test fails. Restore.

- [ ] **Step 6: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && rtk proxy git add web/src/lib/voiceLine.ts web/src/components/PushToTalk.tsx web/src/lib/speech.ts web/src/stores/arslanStore.ts web/src/__tests__/voice-line.test.ts web/src/__tests__/speech.test.ts && rtk proxy git commit -m "voice: shared line parser; the speaker reports when it is speaking"
```

---

### Task 5: Settings — `voice_mode` and `voice_endpoint_silence_ms`, seven places

**Files:**
- Modify: `server/schemas.py:72` and `:126` · `server/services/settings_service.py:32`
- Modify: `web/src/api/client.types.ts:270` · `web/src/api/adapters.ts:69` and `:114` · `web/src/data.ts:20` · `web/src/types.ts:214`
- Modify: `web/src/components/settings/AdvancedSection.tsx` (props + two controls after the voice-input-locale block, before the LAN block at ~line 207) · `web/src/components/SettingsScreen.tsx:232`
- Modify: `web/src/locales/{en,zh,ja,de,fr,es}.json` (`settings.labelVoiceMode`, `settings.voiceModeDesc`, `settings.voiceModeOff`, `settings.voiceModePushToTalk`, `settings.voiceModeConversation`, `settings.labelVoiceEndpointSilence`, `settings.voiceEndpointSilenceDesc`)
- Test: `web/src/__tests__/settings-put-carries-only-what-was-touched.test.ts:140` (`uiNameFor`), `web/src/__tests__/settings-advanced-section.test.tsx:39`, `web/src/__tests__/default-read.test.tsx:26`, `web/src/__tests__/settings-field-homes.test.tsx:131` (prop fixtures), new assertions in `settings-advanced-section.test.tsx`

**Interfaces:**
- Produces: `AppSettings.voiceMode: 'off' | 'push_to_talk' | 'conversation'` (export `type VoiceMode` from `web/src/types.ts`), `AppSettings.voiceEndpointSilenceMs: number`; backend keys `voice_mode` (string), `voice_endpoint_silence_ms` (string of an integer).

- [ ] **Step 1: Write the failing tests**

In `settings-put-carries-only-what-was-touched.test.ts`, add to `uiNameFor` after `voice_input_locale`:

```ts
      voice_mode: { voiceMode: "conversation" },
      voice_endpoint_silence_ms: { voiceEndpointSilenceMs: 1200 },
```

In `settings-advanced-section.test.tsx`, add to the props fixture after line 39:

```ts
      voiceMode: "push_to_talk", onVoiceModeChange: vi.fn(),
      voiceEndpointSilenceMs: 900, onVoiceEndpointSilenceChange: vi.fn(),
```

and a new test in that file (follow its existing render helper):

```ts
  it("offers the three voice modes and reports the pick", () => {
    const onVoiceModeChange = vi.fn();
    render(<AdvancedSection {...props} onVoiceModeChange={onVoiceModeChange} />);
    const sel = screen.getByTestId("voice-mode") as HTMLSelectElement;
    expect(Array.from(sel.options).map((o) => o.value)).toEqual(["off", "push_to_talk", "conversation"]);
    fireEvent.change(sel, { target: { value: "conversation" } });
    expect(onVoiceModeChange).toHaveBeenCalledWith("conversation");
  });

  it("the endpoint silence is a number in milliseconds, clamped to 300–3000", () => {
    const onVoiceEndpointSilenceChange = vi.fn();
    render(<AdvancedSection {...props} onVoiceEndpointSilenceChange={onVoiceEndpointSilenceChange} />);
    const input = screen.getByTestId("voice-endpoint-silence") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "50" } });
    expect(onVoiceEndpointSilenceChange).toHaveBeenLastCalledWith(300);
    fireEvent.change(input, { target: { value: "1500" } });
    expect(onVoiceEndpointSilenceChange).toHaveBeenLastCalledWith(1500);
  });
```

Add the same two prop pairs to the fixtures in `default-read.test.tsx:26` and `settings-field-homes.test.tsx:131` (`voiceMode="push_to_talk" onVoiceModeChange={() => {}} voiceEndpointSilenceMs={900} onVoiceEndpointSilenceChange={() => {}}` in the JSX form used there).

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107/web && npx vitest run src/__tests__/settings-put-carries-only-what-was-touched.test.ts src/__tests__/settings-advanced-section.test.tsx 2>&1 | grep -E "×|failed|passed" | head
```

Expected: the put test fails ("unmappable" includes the two new keys once the adapter knows them — first it fails because `toBackendSettings` does not emit them; both directions are asserted), the two new section tests fail (no `voice-mode` testid).

- [ ] **Step 3: Implement, layer by layer**

`server/schemas.py` — after line 72 (`SettingsIn`): `voice_mode: str | None = None` and `voice_endpoint_silence_ms: str | None = None`; after line 126 (`SettingsOut`): `voice_mode: str = ""` and `voice_endpoint_silence_ms: str = ""`.

`server/services/settings_service.py:32` — extend the tuple: `"voice_output_enabled", "voice_input_locale", "voice_mode", "voice_endpoint_silence_ms")`.

`web/src/api/client.types.ts` after line 270:

```ts
  voice_mode?: string;            // "off" | "push_to_talk" | "conversation" (default push_to_talk)
  voice_endpoint_silence_ms?: string; // integer ms as a string (default "900")
```

`web/src/types.ts` — before `voiceOutputEnabled: boolean;` add `export`-able type near the top of the file (next to `SpawnMode`): `export type VoiceMode = 'off' | 'push_to_talk' | 'conversation';` and after `voiceInputLocale: string;`:

```ts
  /** How the microphone is used: not at all, held, or always listening. */
  voiceMode: VoiceMode;
  /** Conversation mode: silence (ms) after speech that ends a sentence. */
  voiceEndpointSilenceMs: number;
```

`web/src/data.ts` after line 20:

```ts
  voiceMode: 'push_to_talk',   // always-on listening is a choice, not a default
  voiceEndpointSilenceMs: 900, // measured default; see the V2 spec §3.1
```

`web/src/api/adapters.ts` — read side after line 69:

```ts
    voiceMode: (["off", "push_to_talk", "conversation"].includes(backend.voice_mode ?? "")
      ? backend.voice_mode : "push_to_talk") as AppSettings["voiceMode"],
    voiceEndpointSilenceMs: Number.parseInt(backend.voice_endpoint_silence_ms ?? "", 10) || 900,
```

write side after line 114:

```ts
  voiceMode: { key: "voice_mode", to: (v) => String(v) },
  voiceEndpointSilenceMs: { key: "voice_endpoint_silence_ms", to: (v) => String(v) },
```

`AdvancedSection.tsx` — props after `onVoiceInputLocaleChange`:

```ts
  voiceMode: VoiceMode;
  onVoiceModeChange: (value: VoiceMode) => void;
  voiceEndpointSilenceMs: number;
  onVoiceEndpointSilenceChange: (value: number) => void;
```

(import `VoiceMode` from `'../../types'`), destructure them, and add after the voice-input-locale block:

```tsx
        {/* How the microphone is used. Conversation mode is opt-in: an app that
            listens all the time is a choice the user makes, never a default. */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelVoiceMode')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">{t('settings.voiceModeDesc')}</p>
          </div>
          <select
            data-testid="voice-mode"
            value={voiceMode}
            onChange={(e) => onVoiceModeChange(e.target.value as VoiceMode)}
            className="text-[11px] font-mono bg-background border border-border rounded-lg px-2 py-1.5 shrink-0"
          >
            <option value="off">{t('settings.voiceModeOff')}</option>
            <option value="push_to_talk">{t('settings.voiceModePushToTalk')}</option>
            <option value="conversation">{t('settings.voiceModeConversation')}</option>
          </select>
        </div>

        {/* The one tunable of the endpointer (spec §3.1). Clamped: below 300 ms
            every breath ends a sentence, above 3 s the app feels deaf. */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.labelVoiceEndpointSilence')}</h4>
            <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">{t('settings.voiceEndpointSilenceDesc')}</p>
          </div>
          <input
            data-testid="voice-endpoint-silence"
            type="number"
            min={300}
            max={3000}
            step={100}
            value={voiceEndpointSilenceMs}
            onChange={(e) => {
              const n = Number.parseInt(e.target.value, 10);
              onVoiceEndpointSilenceChange(Math.min(3000, Math.max(300, Number.isNaN(n) ? 900 : n)));
            }}
            className="w-24 text-[11px] font-mono bg-background border border-border rounded-lg px-2 py-1.5 shrink-0"
          />
        </div>
```

`SettingsScreen.tsx` after line 232:

```tsx
        voiceMode={localSettings.voiceMode ?? 'push_to_talk'}
        onVoiceModeChange={(v) => saveField({ voiceMode: v })}
        voiceEndpointSilenceMs={localSettings.voiceEndpointSilenceMs ?? 900}
        onVoiceEndpointSilenceChange={(v) => saveField({ voiceEndpointSilenceMs: v })}
```

Locales — `en.json` in the `settings` object next to `voiceInputLocaleDesc`:

```json
    "labelVoiceMode": "Microphone",
    "voiceModeDesc": "Off; hold a button to talk; or keep listening and send each sentence as you finish it. In conversation mode the microphone is muted while a reply is being read aloud.",
    "voiceModeOff": "Off",
    "voiceModePushToTalk": "Hold to talk",
    "voiceModeConversation": "Conversation",
    "labelVoiceEndpointSilence": "End of sentence (ms)",
    "voiceEndpointSilenceDesc": "How long you have to pause before what you said is sent. 900 ms is a normal breath; shorter cuts you off, longer feels slow."
```

Add the same seven keys, translated, to `zh.json`, `ja.json`, `de.json`, `fr.json`, `es.json`:

- zh: `"labelVoiceMode": "麦克风"`, `"voiceModeDesc": "关闭；按住说话；或一直听着,每说完一句就发送。对话模式下,朗读回复时麦克风会静音。"`, `"voiceModeOff": "关闭"`, `"voiceModePushToTalk": "按住说话"`, `"voiceModeConversation": "对话"`, `"labelVoiceEndpointSilence": "一句话的结束(毫秒)"`, `"voiceEndpointSilenceDesc": "停顿多久之后把你说的话发出去。900 毫秒约等于正常换气;更短会打断你,更长会显得迟钝。"`
- ja: `"マイク"`, `"オフ、押している間だけ聞く、または常に聞き取り、一文ごとに送信。会話モードでは返答の読み上げ中はマイクをミュートします。"`, `"オフ"`, `"押して話す"`, `"会話"`, `"文の区切り(ミリ秒)"`, `"どれだけ間を置いたら送信するか。900 ミリ秒は普通の息継ぎ程度。短いと途中で切れ、長いと反応が鈍く感じます。"`
- de: `"Mikrofon"`, `"Aus; Taste halten zum Sprechen; oder dauerhaft zuhören und jeden Satz senden, sobald er endet. Im Gesprächsmodus ist das Mikrofon stumm, während eine Antwort vorgelesen wird."`, `"Aus"`, `"Halten zum Sprechen"`, `"Gespräch"`, `"Satzende (ms)"`, `"Wie lange du pausierst, bevor das Gesagte gesendet wird. 900 ms sind ein normaler Atemzug; kürzer schneidet dich ab, länger wirkt träge."`
- fr: `"Microphone"`, `"Désactivé ; maintenir pour parler ; ou écouter en continu et envoyer chaque phrase dès qu'elle se termine. En mode conversation, le micro est coupé pendant la lecture d'une réponse."`, `"Désactivé"`, `"Maintenir pour parler"`, `"Conversation"`, `"Fin de phrase (ms)"`, `"Durée de la pause avant l'envoi de ce que vous avez dit. 900 ms correspondent à une respiration normale ; moins vous coupe, plus paraît lent."`
- es: `"Micrófono"`, `"Apagado; mantener pulsado para hablar; o escuchar siempre y enviar cada frase al terminarla. En modo conversación el micrófono se silencia mientras se lee una respuesta."`, `"Apagado"`, `"Mantener para hablar"`, `"Conversación"`, `"Fin de frase (ms)"`, `"Cuánto debes pausar antes de que se envíe lo dicho. 900 ms es una respiración normal; menos te corta, más parece lento."`

- [ ] **Step 4: Run the whole frontend + the backend settings tests**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107/web && npx tsc --noEmit && npx vitest run 2>&1 | grep -E "Tests|failed" ; cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && ARSLAN_SECRET_KEY=ci-secret ARSLAN_API_TOKEN="" ARSLAN_DATA_DIR=data .venv/bin/pytest tests/server -k "settings" -q 2>&1 | tail -2
```

Expected: tsc clean, vitest all green (locale-parity included), backend settings tests green.

- [ ] **Step 5: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && rtk proxy git add server/schemas.py server/services/settings_service.py web/src/api/client.types.ts web/src/api/adapters.ts web/src/data.ts web/src/types.ts web/src/components/settings/AdvancedSection.tsx web/src/components/SettingsScreen.tsx web/src/locales web/src/__tests__ && rtk proxy git commit -m "settings: voice_mode and voice_endpoint_silence_ms, seven places in lockstep"
```

---

### Task 6: `useConversationMode` and `ConversationToggle`

**Files:**
- Create: `web/src/hooks/useConversationMode.ts`
- Create: `web/src/components/ConversationToggle.tsx`
- Test: `web/src/__tests__/use-conversation-mode.test.tsx` (new)

**Interfaces:**
- Consumes: `parseLine`, `errorMessage` (Task 4); Tauri commands (Task 3); `useArslanStore((s) => s.speaking)` (Task 4).
- Produces: `useConversationMode(opts: { enabled: boolean; locale: string; silenceMs: number; onFinal: (text: string) => void; onError: (msg: string) => void; }) => { phase: 'off' | 'arming' | 'listening' | 'muted'; partial: string }`.
- Produces: `<ConversationToggle active phase partial onToggle />` rendering `data-testid="conversation-toggle"` with `data-phase`.

- [ ] **Step 1: Write the failing tests**

```tsx
/**
 * Conversation mode's session, against a fake Tauri.
 *
 * What must be true: enabling starts the helper with the locale and the
 * silence setting; a final is SENT (not put in a text box); the microphone
 * is muted exactly while the speaker is active; disabling stops the helper.
 */
import { describe, test, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useConversationMode } from "../hooks/useConversationMode";
import { useArslanStore } from "../stores/arslanStore";

let listeners: Array<(e: { payload: string }) => void>;
let invokes: Array<[string, unknown]>;
beforeEach(() => {
  listeners = []; invokes = [];
  (window as any).__TAURI__ = {
    core: { invoke: vi.fn(async (cmd: string, args?: unknown) => { invokes.push([cmd, args]); }) },
    event: { listen: vi.fn(async (_name: string, cb: any) => { listeners.push(cb); return () => { listeners = listeners.filter((l) => l !== cb); }; }) },
  };
  useArslanStore.setState({ speaking: false });
});
const emit = (line: string) => listeners.forEach((l) => l({ payload: line }));
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

describe("useConversationMode", () => {
  test("enabling starts the helper with locale and silence; a final is sent", async () => {
    const onFinal = vi.fn();
    const { result } = renderHook(() => useConversationMode({ enabled: true, locale: "zh-CN", silenceMs: 1200, onFinal, onError: vi.fn() }));
    await flush();
    expect(invokes).toContainEqual(["voice_conversation_start", { locale: "zh-CN", silenceMs: 1200 }]);
    expect(result.current.phase).toBe("arming");
    act(() => emit('{"t":"ready"}'));
    expect(result.current.phase).toBe("listening");
    act(() => emit('{"t":"partial","text":"打开"}'));
    expect(result.current.partial).toBe("打开");
    act(() => emit('{"t":"final","text":"打开桌面"}'));
    expect(onFinal).toHaveBeenCalledWith("打开桌面");
    expect(result.current.partial).toBe("");
  });

  test("an empty final is not sent", async () => {
    const onFinal = vi.fn();
    renderHook(() => useConversationMode({ enabled: true, locale: "en-US", silenceMs: 900, onFinal, onError: vi.fn() }));
    await flush();
    act(() => emit('{"t":"final","text":"   "}'));
    expect(onFinal).not.toHaveBeenCalled();
  });

  test("the microphone is muted exactly while the speaker is active", async () => {
    const { result } = renderHook(() => useConversationMode({ enabled: true, locale: "en-US", silenceMs: 900, onFinal: vi.fn(), onError: vi.fn() }));
    await flush();
    act(() => emit('{"t":"ready"}'));
    act(() => useArslanStore.setState({ speaking: true }));
    await flush();
    expect(invokes.map(([c]) => c)).toContain("voice_mute");
    expect(result.current.phase).toBe("muted");
    act(() => useArslanStore.setState({ speaking: false }));
    await flush();
    expect(invokes.map(([c]) => c)).toContain("voice_unmute");
    expect(result.current.phase).toBe("listening");
  });

  test("disabling stops the helper; an error line surfaces as a sentence", async () => {
    const onError = vi.fn();
    const { rerender } = renderHook(({ enabled }) => useConversationMode({ enabled, locale: "en-US", silenceMs: 900, onFinal: vi.fn(), onError }), { initialProps: { enabled: true } });
    await flush();
    act(() => emit('{"t":"error","code":"mic-denied","msg":"x"}'));
    expect(onError).toHaveBeenCalledWith("voice.errDenied");
    rerender({ enabled: false });
    await flush();
    expect(invokes.map(([c]) => c)).toContain("voice_conversation_stop");
  });

  test("no Tauri at all: stays off and never throws", async () => {
    (window as any).__TAURI__ = undefined;
    const { result } = renderHook(() => useConversationMode({ enabled: true, locale: "en-US", silenceMs: 900, onFinal: vi.fn(), onError: vi.fn() }));
    await flush();
    expect(result.current.phase).toBe("off");
  });
});
```

Check how the other hook tests in `web/src/__tests__/` mock `react-i18next` (e.g. `useDebouncedSettingsSave.test.ts` or `settings-language.test.tsx`) and copy that mock so `t` is the identity, because the hook calls `useTranslation()` for `errorMessage`.

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107/web && npx vitest run src/__tests__/use-conversation-mode.test.tsx 2>&1 | grep -E "×|failed|Error" | head -5
```

Expected: fails to import the hook.

- [ ] **Step 3: Implement**

`web/src/hooks/useConversationMode.ts`:

```ts
/**
 * Conversation mode's session with the shell.
 *
 * One helper process per enabled period. Everything it says arrives on
 * `voice://conv`; a final becomes `onFinal(text)` — which the caller turns
 * into an ordinary user message, the same call typing makes. Half-duplex:
 * while the Web Speech speaker is active (store `speaking`), the helper is
 * muted so the reply is not transcribed back into a question.
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { parseLine, errorMessage } from '../lib/voiceLine';
import { useArslanStore } from '../stores/arslanStore';

export type ConversationPhase = 'off' | 'arming' | 'listening' | 'muted';

export interface ConversationOptions {
  enabled: boolean;
  locale: string;
  silenceMs: number;
  onFinal: (text: string) => void;
  onError: (message: string) => void;
}

function tauri(): any { return (window as any).__TAURI__; }

export function useConversationMode(opts: ConversationOptions): { phase: ConversationPhase; partial: string } {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<ConversationPhase>('off');
  const [partial, setPartial] = useState('');
  const speaking = useArslanStore((s) => s.speaking);
  // Callbacks in refs so a re-render never restarts the helper.
  const cb = useRef({ onFinal: opts.onFinal, onError: opts.onError, t });
  cb.current = { onFinal: opts.onFinal, onError: opts.onError, t };

  useEffect(() => {
    const tr = tauri();
    if (!opts.enabled || !tr?.core?.invoke || !tr?.event?.listen) {
      setPhase('off');
      return;
    }
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    (async () => {
      const un = await tr.event.listen('voice://conv', (e: { payload: string }) => {
        const line = parseLine(e.payload);
        if (!line) return;
        if (line.t === 'ready') { setPhase((p) => (p === 'muted' ? p : 'listening')); setPartial(''); }
        else if (line.t === 'partial') setPartial(line.text);
        else if (line.t === 'final') {
          setPartial('');
          if (line.text.trim()) cb.current.onFinal(line.text.trim());
        } else if (line.t === 'error') cb.current.onError(errorMessage(line.code, line.msg, cb.current.t));
        else if (line.t === 'ended') setPhase('off');
      });
      if (cancelled) { un(); return; }
      unlisten = un;
      setPhase('arming');
      try {
        await tr.core.invoke('voice_conversation_start', { locale: opts.locale, silenceMs: opts.silenceMs });
      } catch (e) {
        cb.current.onError(String(e));
        setPhase('off');
      }
    })();
    return () => {
      cancelled = true;
      unlisten?.();
      setPhase('off');
      setPartial('');
      tr.core.invoke('voice_conversation_stop').catch(() => { /* the helper dies with its stdin anyway */ });
    };
  }, [opts.enabled, opts.locale, opts.silenceMs]);

  // The microphone gate. `speaking` is the speaker's own bookkeeping, so the
  // mute lasts exactly as long as the reply is audible, not as long as the
  // stream takes to arrive.
  useEffect(() => {
    if (phase === 'off' || phase === 'arming') return;
    const tr = tauri();
    if (!tr?.core?.invoke) return;
    if (speaking) {
      setPhase('muted');
      tr.core.invoke('voice_mute').catch(() => {});
    } else {
      setPhase('listening');
      tr.core.invoke('voice_unmute').catch(() => {});
    }
  }, [speaking, phase === 'off' || phase === 'arming']);

  return { phase, partial };
}
```

`web/src/components/ConversationToggle.tsx`:

```tsx
/**
 * The conversation-mode button: one click to start listening, one to stop.
 * Toggled rather than held (the point of the mode), so the state is shown —
 * a pulsing pill while listening, a muted marker while a reply is read.
 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import { Mic, MicOff, Loader2 } from 'lucide-react';
import type { ConversationPhase } from '../hooks/useConversationMode';

export interface ConversationToggleProps {
  active: boolean;
  phase: ConversationPhase;
  partial: string;
  onToggle: () => void;
  disabled?: boolean;
}

export default function ConversationToggle({ active, phase, partial, onToggle, disabled }: ConversationToggleProps) {
  const { t } = useTranslation();
  const label = active ? t('voice.conversationStop') : t('voice.conversationStart');
  return (
    <span className="flex items-center gap-2 min-w-0">
      <button
        type="button"
        data-testid="conversation-toggle"
        data-phase={phase}
        aria-pressed={active}
        aria-label={label}
        title={label}
        disabled={disabled}
        onClick={onToggle}
        className={[
          'flex items-center gap-1 px-2.5 py-1 rounded-full border text-[10px] font-mono transition-colors select-none',
          active ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:border-primary/40',
          disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
        ].join(' ')}
      >
        {phase === 'arming' ? <Loader2 className="w-3 h-3 animate-spin" />
          : phase === 'muted' ? <MicOff className="w-3 h-3" />
          : <Mic className="w-3 h-3" />}
        {phase === 'listening' && <span>{t('voice.listening')}</span>}
        {phase === 'muted' && <span>{t('voice.speaking')}</span>}
      </button>
      {partial && (
        <span data-testid="conversation-partial" className="truncate text-[11px] text-muted-foreground font-sans">
          {partial}
        </span>
      )}
    </span>
  );
}
```

Locales — add to the `voice` block in all six files: `en`: `"conversationStart": "Start conversation"`, `"conversationStop": "Stop listening"`, `"speaking": "speaking…"`; `zh`: `"开始对话"`, `"停止聆听"`, `"朗读中…"`; `ja`: `"会話を開始"`, `"聞き取りを停止"`, `"読み上げ中…"`; `de`: `"Gespräch starten"`, `"Zuhören beenden"`, `"spricht…"`; `fr`: `"Démarrer la conversation"`, `"Arrêter l'écoute"`, `"lecture…"`; `es`: `"Iniciar conversación"`, `"Dejar de escuchar"`, `"hablando…"`.

- [ ] **Step 4: Run to verify they pass**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107/web && npx vitest run src/__tests__/use-conversation-mode.test.tsx src/__tests__/locale-parity.test.ts 2>&1 | grep -E "Tests|failed" && npx tsc --noEmit && echo tsc-ok
```

- [ ] **Step 5: Mutation check**

Remove `if (line.text.trim())` → "an empty final is not sent" fails. Remove the `voice_mute` invoke → the mute test fails. Restore.

- [ ] **Step 6: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && rtk proxy git add web/src/hooks/useConversationMode.ts web/src/components/ConversationToggle.tsx web/src/__tests__/use-conversation-mode.test.tsx web/src/locales && rtk proxy git commit -m "voice: the conversation session hook and its toggle"
```

---

### Task 7: Wire it into both composers

**Files:**
- Modify: `web/src/components/OrchestratorChat.tsx` — imports (line ~30), state next to `voiceError` (line ~133), the empty composer's left group (lines ~551-556), the thread composer's `composer-row` (line ~1475)
- Test: `web/src/__tests__/orchestrator-voice-mode.test.tsx` (new)

**Interfaces:**
- Consumes: `useConversationMode`, `ConversationToggle` (Task 6), `PushToTalk`, `settings.voice_mode` / `settings.voice_endpoint_silence_ms` from `useSettingsStore` (backend-shaped strings), `onSendMessage` prop.

- [ ] **Step 1: Write the failing test**

Find the existing OrchestratorChat render helper used by `web/src/__tests__/distill-frontend.test.tsx` or the test that renders `<OrchestratorChat …>` with `useSettingsStore.setState` and copy its setup (providers, mocks). Then:

```tsx
/**
 * The mode setting decides which microphone control the composer shows, and
 * a conversation final goes out through onSendMessage — the same door typing
 * uses — never into the text box.
 */
import { describe, test, expect, beforeEach, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import OrchestratorChat from "../components/OrchestratorChat";
import { useSettingsStore } from "../stores/settingsStore";
// …the same mocks/providers the neighbouring OrchestratorChat test uses…

let listeners: Array<(e: { payload: string }) => void>;
beforeEach(() => {
  listeners = [];
  (window as any).__TAURI__ = {
    core: { invoke: vi.fn(async () => {}) },
    event: { listen: vi.fn(async (_n: string, cb: any) => { listeners.push(cb); return () => {}; }) },
  };
});

describe("composer microphone control follows voice_mode", () => {
  test("push_to_talk shows the hold button, no toggle", () => {
    useSettingsStore.setState({ settings: { voice_mode: "push_to_talk" } as any });
    render(<OrchestratorChat {...baseProps} />);
    expect(screen.getByTestId("push-to-talk")).toBeTruthy();
    expect(screen.queryByTestId("conversation-toggle")).toBeNull();
  });

  test("off shows neither", () => {
    useSettingsStore.setState({ settings: { voice_mode: "off" } as any });
    render(<OrchestratorChat {...baseProps} />);
    expect(screen.queryByTestId("push-to-talk")).toBeNull();
    expect(screen.queryByTestId("conversation-toggle")).toBeNull();
  });

  test("conversation: toggle on, a final is sent through onSendMessage", async () => {
    useSettingsStore.setState({ settings: { voice_mode: "conversation", voice_endpoint_silence_ms: "900" } as any });
    const onSendMessage = vi.fn();
    render(<OrchestratorChat {...baseProps} onSendMessage={onSendMessage} />);
    const toggle = screen.getByTestId("conversation-toggle");
    await act(async () => { toggle.click(); await Promise.resolve(); await Promise.resolve(); });
    act(() => listeners.forEach((l) => l({ payload: '{"t":"final","text":"open the desktop"}' })));
    expect(onSendMessage).toHaveBeenCalledWith("open the desktop", undefined);
    const box = screen.getByPlaceholderText(/orchestrator\.placeholder/) as HTMLTextAreaElement;
    expect(box.value).toBe("");
  });
});
```

`baseProps` = the minimal props the neighbouring test uses (an empty `chatHistory`, no-op handlers). If that test renders the thread composer with a non-empty history, add a fourth case asserting `conversation-toggle` is present there too.

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107/web && npx vitest run src/__tests__/orchestrator-voice-mode.test.tsx 2>&1 | grep -E "×|failed" | head -5
```

Expected: "off shows neither" and "conversation" fail (today the hold button is unconditional and there is no toggle).

- [ ] **Step 3: Implement**

In `OrchestratorChat.tsx`, imports:

```ts
import ConversationToggle from './ConversationToggle';
import { useConversationMode } from '../hooks/useConversationMode';
```

Next to `voiceError` (line ~133):

```ts
  // Which microphone control the composer shows. The setting is the user's
  // choice; the toggle below is per session — an app must not start
  // listening because a setting was flipped last week.
  const voiceMode = settings?.voice_mode === 'off' || settings?.voice_mode === 'conversation' ? settings.voice_mode : 'push_to_talk';
  const [conversationOn, setConversationOn] = useState(false);
  const conversation = useConversationMode({
    enabled: voiceMode === 'conversation' && conversationOn,
    locale: voiceLocale,
    silenceMs: Number.parseInt(settings?.voice_endpoint_silence_ms ?? '', 10) || 900,
    onFinal: (text) => { setVoiceError(null); onSendMessage?.(text, undefined); },
    onError: (msg) => { setVoiceError(msg); setConversationOn(false); },
  });
  const micControl = voiceMode === 'push_to_talk' ? (
    <PushToTalk
      locale={voiceLocale}
      onPartial={(text) => { setVoiceError(null); setInputValue(text); }}
      onFinal={(text) => setInputValue(text)}
      onError={(msg) => setVoiceError(msg)}
    />
  ) : voiceMode === 'conversation' ? (
    <ConversationToggle
      active={conversationOn}
      phase={conversation.phase}
      partial={conversation.partial}
      onToggle={() => setConversationOn((v) => !v)}
    />
  ) : null;
```

Replace the `<PushToTalk … />` block in the empty composer (lines ~551-556) with `{micControl}`. In the thread composer's `composer-row` (line ~1475), directly after `<AttachControl busy={attach.busy} onPickFiles={attach.addFiles} />`, add `{micControl}`. Note `setInputValue` for push-to-talk finals is unchanged: hold-to-talk still fills the box (V1a behaviour), conversation sends.

If `onSendMessage`'s second parameter is typed as non-optional in `OrchestratorChatProps`, pass `undefined` explicitly as above (the test asserts it).

- [ ] **Step 4: Run to verify it passes, plus everything frontend**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107/web && npx vitest run 2>&1 | grep -E "Tests|failed" && npx tsc --noEmit && npx vite build 2>&1 | tail -1
```

- [ ] **Step 5: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && rtk proxy git add web/src/components/OrchestratorChat.tsx web/src/__tests__/orchestrator-voice-mode.test.tsx && rtk proxy git commit -m "voice: conversation mode in both composers — a final is sent, not typed"
```

---

### Task 8: Packaging and CI

**Files:**
- Modify: `packaging/build_dmg.sh:157-161` and `:183-188`
- Modify: `.github/workflows/ci.yml` macos job, a new step right after `actions/checkout@v4` (line ~128)

- [ ] **Step 1: build_dmg.sh — build and sign the second helper**

After line 158 (`swiftc … arslan-listen`) add:

```bash
swiftc -O -o "$TAURI/binaries/listen/arslan-voice" "$HERE/listen/arslan-voice.swift"
test -x "$TAURI/binaries/listen/arslan-voice" \
  || { echo "ERROR: the conversation helper did not build" >&2; exit 1; }
```

After the `codesign … arslan-listen` block (line ~188) add:

```bash
  codesign --force --sign "$APPLE_SIGNING_IDENTITY" --timestamp --options runtime \
    "$TAURI/binaries/listen/arslan-voice"
```

- [ ] **Step 2: ci.yml — Swift is compiled nowhere in CI today; typecheck both helpers on the macos job**

Insert after `- uses: actions/checkout@v4` in the `macos` job:

```yaml
      - name: Swift helpers typecheck
        # The two voice helpers are compiled only by build_dmg.sh on a tag
        # push. A syntax error in either would surface at release time, after
        # every other check had passed. Typecheck is seconds; it is not a
        # runtime test (that needs a microphone and TCC — see the V2 spec §8).
        run: |
          for f in packaging/listen/*.swift; do
            swiftc -typecheck "$f"
          done
```

- [ ] **Step 3: Verify locally what can be verified**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && bash -n packaging/build_dmg.sh && for f in packaging/listen/*.swift; do swiftc -typecheck "$f"; done && echo ok && ARSLAN_SECRET_KEY=ci-secret ARSLAN_API_TOKEN="" ARSLAN_DATA_DIR=data .venv/bin/pytest tests/server/test_release_workflow.py -q 2>&1 | tail -1
```

- [ ] **Step 4: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && rtk proxy git add packaging/build_dmg.sh .github/workflows/ci.yml && rtk proxy git commit -m "packaging: build and sign arslan-voice; CI typechecks the Swift helpers"
```

---

### Task 9: Whole-branch verification and the PR

- [ ] **Step 1: CI-parity, all of it**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && mkdir -p desktop/src-tauri/binaries/sidecar desktop/src-tauri/binaries/listen && cargo fmt --check --manifest-path desktop/src-tauri/Cargo.toml && cargo test --manifest-path desktop/src-tauri/Cargo.toml 2>&1 | grep -E "test result" && cargo clippy --manifest-path desktop/src-tauri/Cargo.toml --all-targets -- -D warnings 2>&1 | tail -1 && .venv/bin/ruff check server/ arslan/ tests/ scripts/ && (cd web && npx tsc --noEmit && npx vitest run 2>&1 | grep -E "Tests|failed" && npx vite build 2>&1 | tail -1) && ARSLAN_SECRET_KEY=ci-secret ARSLAN_API_TOKEN="" ARSLAN_DATA_DIR=data .venv/bin/pytest tests/ -q -rfE 2>&1 | tail -2
```

Expected: every line green; backend `N passed` with only the known local `pytesseract` skips/failures (3 in `test_ingest_rasterize.py`, same on main).

- [ ] **Step 2: Spec reconciliation** — walk `docs/specs/2026-09-02-realtime-voice-v2-build.md` §2, §3.1, §4, §6, §7 (V2a row), §8 and write, for each requirement, the file that implements it into the PR body. Anything without a file is either done now or listed under "Not in this PR" with the reason.

- [ ] **Step 3: Push and open the PR**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/wt-107 && rtk proxy git push -u origin feat/voice-v2a && gh pr create --base main --title "Conversation mode: say it, it is sent (V2a, half-duplex)" --body-file - <<'BODY'
## What
Spec: docs/specs/2026-09-02-realtime-voice-v2-build.md, phase V2a. …(the reconciliation table from Step 2)…

## Evidence
…cargo test / vitest / pytest counts, mutation list per task…

## Not verified here
- Real-device: the helper under TCC in a packaged build; endpointing feel; mute timing against the speaker. Acceptance script: Task 10.
- The `swiftc -typecheck` CI step proves syntax, not behaviour.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
```

---

### Task 10: Real-device acceptance (the user runs this; the PR body links it)

Build a DMG with `packaging/build_dmg.sh`, install, set the built-in speaker volume above 0 (this machine's was 0), put AirPods away, then:

1. Settings → Advanced → Microphone = Conversation. Go back to the chat; a toggle appears in the composer.
2. Click it. First run: two permission prompts → Allow. Pill reads "listening…".
3. Say three short requests, pausing after each. **Pass:** three user messages appear and are answered without touching the keyboard.
4. With "Read replies aloud" on, ask something with a long answer. **Pass:** the pill reads "speaking…" while the reply is read and nothing the reply says comes back as a new message; it returns to "listening…" when the voice stops.
5. Say a risky command ("delete everything in my Downloads"). **Pass:** the confirmation card appears and nothing executes.
6. Click the toggle off. **Pass:** the orange microphone indicator in the menu bar disappears within a second.
7. Quit the app while listening. **Pass:** the indicator disappears (no orphan helper: `pgrep arslan-voice` is empty).

Record which of 1–7 passed in the acceptance receipt; any failure names the step.
