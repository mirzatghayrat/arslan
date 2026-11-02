//! Finding the proxy a packaged app cannot see.
//!
//! A GUI app launched from Finder inherits launchd's environment, not a
//! shell's, and launchd carries no proxy variables — `launchctl getenv
//! HTTPS_PROXY` is empty on a machine whose System Settings proxy is switched
//! on and working. Both of our network stacks read only those variables:
//! reqwest (the updater) and httpx (the sidecar) consult `HTTPS_PROXY` and
//! friends, and neither reads macOS's own proxy configuration. So on every
//! machine that reaches the internet THROUGH a proxy, the packaged app has no
//! internet at all: the update check fails to connect, and so does every LLM
//! call. The dev build works, because a terminal has the variables.
//!
//! This module asks macOS what the system proxy is and hands it to both, which
//! is the piece that was missing rather than a new capability.
//!
//! 🔴 It changes one security property, stated plainly: `net_pin` pins each
//! resolved hop to a validated address, and that guarantee holds only for
//! connections IT makes. When a proxy is configured the connection is made by
//! the proxy, so what the proxy does with the address is outside the guard —
//! SSRF protection is delegated to it. `net_pin` already documents this for
//! the case where a user set the variables by hand; this makes that case the
//! common one on proxied machines. The alternative is an app with no network.

use std::collections::HashMap;

/// Loopback must never be proxied: the shell talks to its own sidecar over
/// 127.0.0.1, and a local model server (Ollama, LM Studio, vLLM, llama.cpp)
/// is a localhost URL too. Sending either through a proxy would break a
/// working setup in the name of fixing a broken one.
pub const NO_PROXY: &str = "localhost,127.0.0.1,::1,.local";

/// What `scutil --proxy` said, reduced to the one URL both stacks want.
#[derive(Debug, PartialEq, Eq)]
pub struct SystemProxy {
    pub url: String,
}

/// Parse the output of `scutil --proxy`.
///
/// Kept separate from running the command so the parsing — the part with the
/// decisions in it — is testable without a machine in a particular state.
///
/// Returns `None` when there is nothing usable: no proxy enabled, or a PAC
/// script, which is a program to be evaluated per-URL and cannot be reduced to
/// one address. Guessing in the PAC case would send traffic somewhere the user
/// never designated, so we leave the variables unset and stay direct.
pub fn parse_scutil(output: &str) -> Option<SystemProxy> {
    let mut kv: HashMap<&str, &str> = HashMap::new();
    for line in output.lines() {
        if let Some((k, v)) = line.split_once(':') {
            kv.insert(k.trim(), v.trim());
        }
    }

    if kv.get("ProxyAutoConfigEnable").is_some_and(|v| *v == "1") {
        return None;
    }

    // HTTPS first: every host we talk to is https, so an http-only proxy entry
    // is the fallback, not the preference.
    for (enable, host, port) in [
        ("HTTPSEnable", "HTTPSProxy", "HTTPSPort"),
        ("HTTPEnable", "HTTPProxy", "HTTPPort"),
    ] {
        if kv.get(enable).is_some_and(|v| *v == "1") {
            if let (Some(h), Some(p)) = (kv.get(host), kv.get(port)) {
                if !h.is_empty() && !p.is_empty() {
                    // The scheme is how we reach the PROXY, which is plain
                    // HTTP for both entries; it does not describe the traffic.
                    return Some(SystemProxy {
                        url: format!("http://{h}:{p}"),
                    });
                }
            }
        }
    }
    None
}

/// The proxy to use, or `None` to stay direct.
///
/// An explicit `HTTPS_PROXY`/`ALL_PROXY` in the environment wins: someone who
/// launched the app from a configured terminal, or set one with `launchctl
/// setenv`, has said what they want and is not asking to be second-guessed.
pub fn resolve() -> Option<String> {
    for var in ["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"] {
        if let Ok(v) = std::env::var(var) {
            if !v.trim().is_empty() {
                return Some(v);
            }
        }
    }
    system_proxy().map(|p| p.url)
}

/// What the updater's HTTP client is told.
///
/// `resolve` is the only decision. Since tauri-plugin-updater 2.11, reqwest's
/// `system-proxy` feature is on, and a client given no proxy reads the macOS
/// HTTP/HTTPS entries itself and ignores PAC, which this module refuses to
/// guess at. So "nothing resolved" has to become an explicit `Direct`
/// (`no_proxy()`), never reqwest's default (review on #684, v0.1.64 DEP1).
#[derive(Debug, PartialEq)]
pub enum UpdaterProxy {
    Via(tauri::Url),
    Direct,
    /// The value came from the user's own environment and doesn't parse:
    /// carry on direct and say so once, rather than failing the whole check.
    Unusable {
        value: String,
        error: String,
    },
}

pub fn updater_proxy(resolved: Option<String>) -> UpdaterProxy {
    match resolved {
        None => UpdaterProxy::Direct,
        Some(value) => {
            // `host:port` without a scheme is common in HTTPS_PROXY. reqwest's own
            // parsing, httpx (the sidecar) and curl take it as http, so retry with
            // http:// when the value has no host as written.
            let v = value.trim();
            let parsed = match v.parse::<tauri::Url>() {
                Ok(url) if url.has_host() => Ok(url),
                _ => format!("http://{v}").parse::<tauri::Url>(),
            };
            match parsed {
                Ok(url) => UpdaterProxy::Via(url),
                Err(e) => UpdaterProxy::Unusable {
                    error: format!("{e}"),
                    value,
                },
            }
        }
    }
}

#[cfg(target_os = "macos")]
fn system_proxy() -> Option<SystemProxy> {
    let out = std::process::Command::new("scutil")
        .arg("--proxy")
        .output()
        .ok()?;
    parse_scutil(&String::from_utf8_lossy(&out.stdout))
}

#[cfg(not(target_os = "macos"))]
fn system_proxy() -> Option<SystemProxy> {
    // Only macOS ships today. Elsewhere the environment is the only source,
    // which `resolve` has already consulted.
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The shape this bug was found on: proxy on, both entries present.
    const REAL: &str = "<dictionary> {
  HTTPEnable : 1
  HTTPPort : 7899
  HTTPProxy : 127.0.0.1
  HTTPSEnable : 1
  HTTPSPort : 7899
  HTTPSProxy : 127.0.0.1
  ProxyAutoConfigEnable : 0
}";

    #[test]
    fn reads_the_https_entry_from_a_real_scutil_dump() {
        assert_eq!(
            parse_scutil(REAL),
            Some(SystemProxy {
                url: "http://127.0.0.1:7899".into()
            })
        );
    }

    #[test]
    fn falls_back_to_the_http_entry_when_https_is_off() {
        let out = "  HTTPEnable : 1\n  HTTPProxy : 10.0.0.2\n  HTTPPort : 3128\n  HTTPSEnable : 0";
        assert_eq!(
            parse_scutil(out),
            Some(SystemProxy {
                url: "http://10.0.0.2:3128".into()
            })
        );
    }

    #[test]
    fn proxy_switched_off_means_direct() {
        // The distinguishing case: the keys are PRESENT, the switch is 0.
        // Reading the host without checking the flag would proxy everything
        // for a user who turned it off.
        let out = "  HTTPEnable : 0\n  HTTPProxy : 127.0.0.1\n  HTTPPort : 7899\n  HTTPSEnable : 0\n  HTTPSProxy : 127.0.0.1\n  HTTPSPort : 7899";
        assert_eq!(parse_scutil(out), None);
    }

    #[test]
    fn a_pac_script_is_not_guessed_at() {
        let out = "  ProxyAutoConfigEnable : 1\n  ProxyAutoConfigURLString : http://wpad/x.pac\n  HTTPSEnable : 1\n  HTTPSProxy : 127.0.0.1\n  HTTPSPort : 7899";
        assert_eq!(
            parse_scutil(out),
            None,
            "a PAC is per-URL logic, not an address"
        );
    }

    #[test]
    fn nothing_configured_means_direct() {
        assert_eq!(
            parse_scutil("<dictionary> {\n  ExceptionsList : <array> {\n  }\n}"),
            None
        );
    }

    #[test]
    fn an_enabled_entry_with_no_host_is_not_a_proxy() {
        let out = "  HTTPSEnable : 1\n  HTTPSProxy : \n  HTTPSPort : ";
        assert_eq!(parse_scutil(out), None);
    }

    #[test]
    fn loopback_is_never_proxied() {
        // The sidecar lives on 127.0.0.1 and so does a local model server;
        // proxying either would break a working setup.
        for host in ["localhost", "127.0.0.1", "::1"] {
            assert!(NO_PROXY.contains(host), "{host} must be exempt");
        }
    }

    #[test]
    fn the_updater_goes_direct_when_nothing_was_resolved() {
        // A PAC (parse_scutil -> None) must not let reqwest's own system-proxy pick the static entry.
        assert_eq!(updater_proxy(None), UpdaterProxy::Direct);
    }

    #[test]
    fn the_updater_uses_the_resolved_proxy() {
        assert_eq!(
            updater_proxy(Some("http://127.0.0.1:7899".into())),
            UpdaterProxy::Via("http://127.0.0.1:7899".parse().unwrap())
        );
    }

    #[test]
    fn a_proxy_without_a_scheme_is_taken_as_http() {
        // HTTPS_PROXY=127.0.0.1:7899 is common; reqwest's own parsing, httpx (the
        // sidecar) and curl all take it as http://, and 2.10.1's updater did too.
        for (value, want) in [
            ("127.0.0.1:7899", "http://127.0.0.1:7899"),
            ("localhost:7899", "http://localhost:7899"),
            ("[::1]:7899", "http://[::1]:7899"),
            ("user:pw@10.0.0.2:3128", "http://user:pw@10.0.0.2:3128"),
        ] {
            assert_eq!(
                updater_proxy(Some(value.into())),
                UpdaterProxy::Via(want.parse().unwrap()),
                "{value}"
            );
        }
    }

    #[test]
    fn an_unusable_proxy_value_goes_direct_and_says_why() {
        match updater_proxy(Some("not a url".into())) {
            UpdaterProxy::Unusable { value, .. } => assert_eq!(value, "not a url"),
            other => panic!("expected Unusable, got {other:?}"),
        }
    }
}
