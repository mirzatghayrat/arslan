//! The contract: the only agent-desktop command lines Hands ever builds.
//!
//! Twelve commands (spec §1: the task book's eleven plus `select`). Requests are structured; this module turns one
//! into argv and refuses everything else — no `--headed`, `--screenshot`,
//! `--debug`, `--force`, no launch, clipboard, notification, screenshot or
//! mouse-coordinate command can be expressed. Values a model chose (text, app
//! names, options) never land where agent-desktop could read them as a flag:
//! options are written `--name=value` and positionals follow `--` (measured:
//! without it, a value `--headed` is parsed as the flag).
//!
//! The same cases are checked from the backend side against
//! `tests/fixtures/hands_contract/`.

use serde_json::Value;

/// A request Hands will not turn into a command line.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Refusal {
    pub code: &'static str,
    pub message: String,
}

pub fn refuse(code: &'static str, message: impl Into<String>) -> Refusal {
    Refusal {
        code,
        message: message.into(),
    }
}

pub const MAX_TEXT: usize = 20_000;
const MAX_APP: usize = 120;
const FIND_LIMIT: &str = "30";

/// The agent-desktop commands Arslan uses, by Hands op name (the task book's
/// eleven, plus `select` for pop-ups and lists).
pub const OPS: [&str; 12] = [
    "snapshot",
    "find",
    "get",
    "click",
    "type",
    "set_value",
    "select",
    "press",
    "scroll",
    "list_apps",
    "list_windows",
    "wait",
];

fn str_arg<'a>(args: &'a Value, key: &str) -> Option<&'a str> {
    args.get(key).and_then(Value::as_str)
}

fn required<'a>(args: &'a Value, key: &str) -> Result<&'a str, Refusal> {
    str_arg(args, key).ok_or_else(|| refuse("bad_request", format!("`{key}` is required")))
}

fn no_controls(text: &str) -> bool {
    !text
        .chars()
        .any(|c| c == '\0' || (c.is_control() && c != '\n' && c != '\t'))
}

/// An app name or bundle id: short, one line.
pub fn app_name(args: &Value) -> Result<&str, Refusal> {
    let app = required(args, "app")?.trim();
    if app.is_empty() || app.len() > MAX_APP || app.contains('\n') || !no_controls(app) {
        return Err(refuse(
            "bad_request",
            "`app` must be an app name or bundle id",
        ));
    }
    Ok(app)
}

/// A snapshot-qualified ref, `@<snapshot id>:e<N>` — the only form accepted, so
/// the snapshot (and with it the app the ref was read from) is always known.
pub fn parse_ref(text: &str) -> Option<(&str, &str)> {
    let rest = text.strip_prefix("@s")?;
    let (id, element) = rest.split_once(":e")?;
    let id_ok = (4..=40).contains(&id.len())
        && id
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit());
    let element_ok =
        (1..=6).contains(&element.len()) && element.bytes().all(|b| b.is_ascii_digit());
    if id_ok && element_ok {
        Some((
            &text[1..2 + id.len()],
            &text[text.len() - element.len() - 1..],
        ))
    } else {
        None
    }
}

fn ref_arg(args: &Value) -> Result<&str, Refusal> {
    let r = required(args, "ref")?;
    parse_ref(r).map(|_| r).ok_or_else(|| {
        refuse(
            "bad_ref",
            "`ref` must be a ref from a look, like @s1a2b3c4:e7",
        )
    })
}

fn text_arg<'a>(args: &'a Value, key: &str) -> Result<&'a str, Refusal> {
    let t = required(args, key)?;
    if t.chars().count() > MAX_TEXT || t.contains('\0') {
        return Err(refuse(
            "bad_request",
            format!("`{key}` is too long or has a NUL"),
        ));
    }
    Ok(t)
}

/// A session id Hands itself created (agent-desktop's own format).
pub fn session_ok(session: &str) -> bool {
    (1..=64).contains(&session.len())
        && session
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

/// A key combo: `return`, `cmd+n`, `shift+tab`… lowercase words joined by `+`.
pub fn combo_ok(combo: &str) -> bool {
    !combo.is_empty()
        && combo.len() <= 40
        && combo.split('+').all(|part| {
            !part.is_empty()
                && part
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
        })
}

/// argv (without the program) for one op, plus `--session` when the request is
/// part of a job's session. Options precede `--`; positionals follow it.
pub fn build(op: &str, args: &Value, session: Option<&str>) -> Result<Vec<String>, Refusal> {
    let mut opts: Vec<String> = Vec::new();
    let mut pos: Vec<String> = Vec::new();
    let command = match op {
        "list_apps" => "list-apps",
        "list_windows" => {
            opts.push(format!("--app={}", app_name(args)?));
            "list-windows"
        }
        "snapshot" => {
            opts.push(format!("--app={}", app_name(args)?));
            window_arg(args, &mut opts)?;
            opts.push("--compact".into());
            match str_arg(args, "root") {
                Some(_) => opts.push(format!("--root={}", ref_arg(&root_as_ref(args))?)),
                None => opts.push("--skeleton".into()),
            }
            if args.get("interactive_only").and_then(Value::as_bool) == Some(true) {
                opts.push("-i".into());
            }
            "snapshot"
        }
        "find" => {
            opts.push(format!("--app={}", app_name(args)?));
            window_arg(args, &mut opts)?;
            let mut any = false;
            for key in ["role", "name", "text"] {
                if let Some(v) = str_arg(args, key) {
                    if v.is_empty() || v.chars().count() > 200 || !no_controls(v) {
                        return Err(refuse("bad_request", format!("`{key}` is not usable")));
                    }
                    opts.push(format!("--{key}={v}"));
                    any = true;
                }
            }
            if !any {
                return Err(refuse("bad_request", "find needs `text`, `name` or `role`"));
            }
            opts.push(format!("--limit={FIND_LIMIT}"));
            "find"
        }
        "get" => {
            let property = str_arg(args, "property").unwrap_or("text");
            if !matches!(property, "text" | "value" | "title" | "role" | "states") {
                return Err(refuse(
                    "bad_request",
                    "`property` is text, value, title, role or states",
                ));
            }
            opts.push(format!("--property={property}"));
            pos.push(ref_arg(args)?.into());
            "get"
        }
        "click" => {
            pos.push(ref_arg(args)?.into());
            "click"
        }
        "type" => {
            pos.push(ref_arg(args)?.into());
            pos.push(text_arg(args, "text")?.into());
            "type"
        }
        "set_value" => {
            pos.push(ref_arg(args)?.into());
            pos.push(text_arg(args, "value")?.into());
            "set-value"
        }
        "select" => {
            pos.push(ref_arg(args)?.into());
            let v = text_arg(args, "value")?;
            if v.chars().count() > 200 {
                return Err(refuse("bad_request", "`value` is too long"));
            }
            pos.push(v.into());
            "select"
        }
        "scroll" => {
            let direction = str_arg(args, "direction").unwrap_or("down");
            if !matches!(direction, "up" | "down" | "left" | "right") {
                return Err(refuse(
                    "bad_request",
                    "`direction` is up, down, left or right",
                ));
            }
            let amount = args.get("amount").and_then(Value::as_u64).unwrap_or(3);
            if !(1..=20).contains(&amount) {
                return Err(refuse("bad_request", "`amount` is 1 to 20"));
            }
            opts.push(format!("--direction={direction}"));
            opts.push(format!("--amount={amount}"));
            pos.push(ref_arg(args)?.into());
            "scroll"
        }
        "press" => {
            let combo = required(args, "keys")?;
            if !combo_ok(combo) {
                return Err(refuse(
                    "bad_request",
                    "`keys` is a combo like return, cmd+n, shift+tab",
                ));
            }
            opts.push(format!("--app={}", app_name(args)?));
            pos.push(combo.into());
            "press"
        }
        "wait" => {
            let text = text_arg(args, "text")?;
            if text.is_empty() || text.chars().count() > 200 {
                return Err(refuse(
                    "bad_request",
                    "`text` to wait for is 1 to 200 characters",
                ));
            }
            let timeout = args
                .get("timeout_ms")
                .and_then(Value::as_u64)
                .unwrap_or(5_000);
            if !(100..=30_000).contains(&timeout) {
                return Err(refuse("bad_request", "`timeout_ms` is 100 to 30000"));
            }
            opts.push(format!("--app={}", app_name(args)?));
            opts.push(format!("--text={text}"));
            opts.push(format!("--timeout={timeout}"));
            "wait"
        }
        _ => {
            return Err(refuse(
                "op_not_allowed",
                format!("`{op}` is not something Hands does"),
            ))
        }
    };
    if let Some(session) = session {
        if !session_ok(session) {
            return Err(refuse("bad_request", "bad session id"));
        }
        opts.push(format!("--session={session}"));
    }
    let mut argv = vec![command.to_string()];
    argv.extend(opts);
    if !pos.is_empty() {
        argv.push("--".into());
        argv.extend(pos);
    }
    Ok(argv)
}

/// `window_id` from list-windows (`w-1234`): look at that window of the app.
fn window_arg(args: &Value, opts: &mut Vec<String>) -> Result<(), Refusal> {
    if let Some(id) = str_arg(args, "window_id") {
        let ok = id
            .strip_prefix("w-")
            .is_some_and(|n| (1..=12).contains(&n.len()) && n.bytes().all(|b| b.is_ascii_digit()));
        if !ok {
            return Err(refuse(
                "bad_request",
                "`window_id` comes from list_windows, like w-1234",
            ));
        }
        opts.push(format!("--window-id={id}"));
    }
    Ok(())
}

fn root_as_ref(args: &Value) -> Value {
    serde_json::json!({ "ref": args.get("root").cloned().unwrap_or(Value::Null) })
}

/// The ops whose target is a ref (checked against the app before running).
pub fn targets_ref(op: &str) -> bool {
    matches!(
        op,
        "get" | "click" | "type" | "set_value" | "select" | "scroll"
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn values_never_become_flags() {
        let argv = build(
            "set_value",
            &json!({"ref": "@sabc123:e1", "value": "--headed"}),
            None,
        )
        .unwrap();
        assert_eq!(argv, ["set-value", "--", "@sabc123:e1", "--headed"]);
        let argv = build("find", &json!({"app": "--headed", "text": "--force"}), None).unwrap();
        assert_eq!(
            argv,
            ["find", "--app=--headed", "--text=--force", "--limit=30"]
        );
    }

    #[test]
    fn nothing_outside_the_eleven_can_be_built() {
        for op in [
            "launch",
            "screenshot",
            "clipboard_get",
            "clipboard-get",
            "list_notifications",
            "batch",
            "mouse_click",
            "drag",
            "hover",
            "close_app",
            "permissions",
            "skills",
            "trace",
            "",
        ] {
            assert_eq!(
                build(op, &json!({"app": "Notes"}), None).unwrap_err().code,
                "op_not_allowed",
                "{op}"
            );
        }
        for op in OPS {
            let built = build(
                op,
                &json!({"app": "Notes", "ref": "@sabc123:e1", "text": "x", "value": "x", "keys": "return"}),
                None,
            );
            let argv = built.unwrap_or_default();
            for forbidden in ["--headed", "--screenshot", "--debug", "--force", "--cdp"] {
                assert!(!argv.iter().any(|a| a == forbidden), "{op}: {argv:?}");
            }
        }
    }

    #[test]
    fn refs_must_be_snapshot_qualified() {
        assert_eq!(parse_ref("@sabc123:e17"), Some(("sabc123", "e17")));
        for bad in [
            "@e1",
            "@1",
            "@sABC123:e1",
            "@s../x:e1",
            "@sabc123:e",
            "@sabc123:e1x",
            "sabc123:e1",
            "@s:e1",
        ] {
            assert_eq!(parse_ref(bad), None, "{bad}");
        }
        assert_eq!(
            build("click", &json!({"ref": "@e1"}), None)
                .unwrap_err()
                .code,
            "bad_ref"
        );
    }

    #[test]
    fn a_window_is_named_by_its_list_windows_id_only() {
        let argv = build(
            "snapshot",
            &json!({"app": "Finder", "window_id": "w-60185"}),
            None,
        )
        .unwrap();
        assert_eq!(
            argv,
            [
                "snapshot",
                "--app=Finder",
                "--window-id=w-60185",
                "--compact",
                "--skeleton"
            ]
        );
        for bad in ["60185", "w-", "w-12a", "--headed", "w-1234567890123"] {
            let r = build(
                "find",
                &json!({"app": "Finder", "text": "x", "window_id": bad}),
                None,
            );
            assert_eq!(r.unwrap_err().code, "bad_request", "{bad}");
        }
    }

    #[test]
    fn combos_and_sessions_are_plain_tokens() {
        assert!(combo_ok("cmd+shift+n") && combo_ok("return"));
        assert!(!combo_ok("--force") && !combo_ok("cmd++") && !combo_ok("Cmd+N") && !combo_ok(""));
        assert!(session_ok("sess-1_a") && !session_ok("../x") && !session_ok(""));
        let argv = build("click", &json!({"ref": "@sabc123:e1"}), Some("s1")).unwrap();
        assert_eq!(argv, ["click", "--session=s1", "--", "@sabc123:e1"]);
    }
}
