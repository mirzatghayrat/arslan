//! One vocabulary for what an action achieved, whichever engine ran it
//! (spec docs/specs/2026-10-08-0157-hands-v2.md §5.3).
//!
//! - `done`: delivered, and the change was read back (or a window change seen);
//! - `sent_unconfirmed`: delivered, no proof either way — look before building on it;
//! - `no_effect`: delivered, nothing seems to have changed;
//! - `partly_done`: some of it was delivered (typing);
//! - `refused`: nothing was delivered.
//!
//! Anything an engine does not say plainly is `sent_unconfirmed`, never `done`.

use serde_json::Value;

/// From agent-desktop's envelope: `data.disposition.delivery`.
pub fn from_agent_desktop(envelope: &Value) -> &'static str {
    match envelope
        .pointer("/data/disposition/delivery")
        .and_then(Value::as_str)
    {
        Some("delivered_verified") => "done",
        _ => "sent_unconfirmed",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn agent_desktop_is_done_only_when_verified() {
        let env = |d: &str| json!({"data": {"disposition": {"delivery": d}}});
        assert_eq!(from_agent_desktop(&env("delivered_verified")), "done");
        assert_eq!(
            from_agent_desktop(&env("delivered_unverified")),
            "sent_unconfirmed"
        );
        assert_eq!(from_agent_desktop(&json!({"data": {}})), "sent_unconfirmed");
    }
}
