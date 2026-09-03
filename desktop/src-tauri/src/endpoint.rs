//! When has the user finished a sentence?
//!
//! Measured on 2026-09-03 (built-in mic, voice processing on): idle peak
//! 0.005–0.016, human speech 0.15–0.75. And measured the other way: the
//! on-device recogniser updates its partial sparsely, so "the partial has not
//! changed for 900 ms" is NOT silence — it split one continuous sentence in
//! two. The rule here is therefore audio silence, gated on a partial existing
//! at all, so breathing and chair creaks never send a message.

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
        Self {
            silence_ms,
            has_text: false,
            last_voice_ms: None,
        }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nothing_heard_never_ends() {
        let mut e = Endpointer::new(900);
        e.on_level(0.5, 0);
        e.on_level(0.0, 100);
        assert!(
            !e.should_end(5_000),
            "no partial exists: a noise burst must not send"
        );
    }

    #[test]
    fn ends_after_silence_once_a_partial_exists() {
        let mut e = Endpointer::new(900);
        e.on_level(0.3, 0);
        e.on_partial("open the", 400);
        e.on_level(0.3, 500);
        e.on_level(0.01, 600);
        assert!(!e.should_end(1_300), "only 800 ms of silence");
        assert!(
            e.should_end(1_400),
            "900 ms of silence after the last voice"
        );
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
        assert!(
            !f.should_end(900),
            "a peak AT the threshold counts as voice"
        );
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
