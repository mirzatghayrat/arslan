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

/// From a Cua Driver action result: `structuredContent.effect`.
pub fn from_cua(result: &Value) -> &'static str {
    match result
        .pointer("/structuredContent/effect")
        .and_then(Value::as_str)
    {
        Some("confirmed") => "done",
        Some("partial") => "partly_done",
        Some("suspected_noop") => "no_effect",
        Some("refused") => "refused",
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

    #[test]
    fn cua_effects_map_and_unknown_is_never_done() {
        let res = |e: &str| json!({"structuredContent": {"effect": e}});
        assert_eq!(from_cua(&res("confirmed")), "done");
        assert_eq!(from_cua(&res("partial")), "partly_done");
        assert_eq!(from_cua(&res("suspected_noop")), "no_effect");
        assert_eq!(from_cua(&res("refused")), "refused");
        assert_eq!(from_cua(&res("unverifiable")), "sent_unconfirmed");
        assert_eq!(from_cua(&res("something-new")), "sent_unconfirmed");
        assert_eq!(from_cua(&json!({})), "sent_unconfirmed");
    }
}
