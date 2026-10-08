//! Hands v2: Cua Driver as Hands' private worker, end to end over Hands' socket, with a
//! fake worker that speaks the real wire protocol (cua-driver-sdk `worker.rs`, v1) and
//! records what it was given. Runs on Linux CI too (nothing here touches the desktop).
//! Spec: docs/specs/2026-10-08-0157-hands-v2.md §3.

use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant};

// The Stop generation is process-wide: these tests take turns.
static SERIAL: Mutex<()> = Mutex::new(());

/// A private worker: proves itself on `initialize`, answers tools from a tiny world of
/// four apps, records its environment, argv and every request next to itself.
const FAKE: &str = r#"#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
here = Path(sys.argv[0]).resolve().parent
mode = json.loads((here / "mode.json").read_text()) if (here / "mode.json").exists() else {}
(here / "env.json").write_text(json.dumps(dict(os.environ)))
(here / "argv.json").write_text(json.dumps(sys.argv[1:]))
with (here / "spawns.log").open("a") as f:
    f.write("spawn\n")
generation = sys.argv[3]
def send(request_id, ok=True, result=None, completion="completed", error=None, code=None):
    out = {"protocol_version": 1, "request_id": request_id, "generation": generation, "ok": ok,
           "completion": completion}
    if result is not None: out["result"] = result
    if error is not None: out["error"] = error; out["error_code"] = code or "worker_request_failed"
    sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()
APPS = [{"name": "Hands Fixture", "bundle_id": "com.arslan.hands-fixture", "pid": 100, "running": True},
        {"name": "Notes", "bundle_id": "com.apple.Notes", "pid": 200, "running": True},
        {"name": "Keychain Access", "bundle_id": "com.apple.keychainaccess", "pid": 300, "running": True},
        {"name": "Safari", "bundle_id": "com.apple.Safari", "pid": 400, "running": True},
        {"name": "Terminal", "bundle_id": "com.apple.Terminal", "pid": 500, "running": True},
        {"name": "Installed Only", "bundle_id": "com.example.installed", "pid": 0, "running": False}]
for line in sys.stdin:
    request = json.loads(line)
    with (here / "requests.log").open("a") as f:
        f.write(json.dumps(request) + "\n")
    rid, op = request["request_id"], request["operation"]
    if op == "initialize":
        host = request["arguments"]["host_bundle_id"]
        send(rid, result={"ready": True, "pid": os.getpid(),
                          "host_bundle_id": "someone-else" if mode.get("bad_proof") else host})
        continue
    if op == "shutdown":
        send(rid, result={"shutdown": True}); break
    if op != "call":
        send(rid, ok=False, error="unknown private worker operation: " + op); continue
    name, args = request["name"], request.get("arguments") or {}
    if args.get("session") == "expired":
        refusal = {"code": "session_ended", "message": "session 'expired' has ended"}
        send(rid, result={"content": [{"type": "text", "text": refusal["message"]}], "isError": True,
                          "structuredContent": {"refusal": refusal, "status": "refused"}}); continue
    if args.get("text") == "refuse-me":
        refusal = {"code": "element_disabled", "message": "the element is disabled"}
        send(rid, result={"content": [{"type": "text", "text": refusal["message"]}], "isError": True,
                          "structuredContent": {"refusal": refusal, "status": "refused"}}); continue
    if args.get("text") == "crash":
        sys.exit(3)
    if args.get("text") == "hang":
        time.sleep(60)
    if name == "list_apps":
        text = ", ".join(a["name"] for a in APPS)
        send(rid, result={"content": [{"type": "text", "text": text}], "structuredContent": {"apps": APPS}})
    elif name == "get_window_state":
        pid = args["pid"]
        elements = [
            {"role": "AXButton", "label": "Save", "element_token": "s0000000%d:0" % (pid // 100),
             "frame": {"x": 10, "y": 20, "w": 40, "h": 20}},
            {"role": "AXTextField", "label": "Title", "element_token": "s0000000%d:1" % (pid // 100)},
            {"role": "AXSecureTextField", "label": "", "element_token": "s0000000%d:2" % (pid // 100)},
            {"role": "AXTextField", "label": "Password", "element_token": "s0000000%d:3" % (pid // 100)},
            {"role": "AXMenuBarItem", "label": "Apple", "depth": 2},
            {"role": "AXMenuItem", "label": "Log Out Someone", "depth": 4},
        ]
        send(rid, result={"content": [], "structuredContent": {"pid": pid, "window_id": args.get("window_id", 1),
                                                               "elements": elements, "tree_markdown": "- Log Out Someone"}})
    else:
        send(rid, result={"content": [{"type": "text", "text": "done"}],
                          "structuredContent": {"effect": "confirmed", "route": "accessibility"}})
"#;

struct Hands {
    dir: PathBuf,
    token: String,
}

impl Hands {
    fn folder(&self) -> PathBuf {
        self.dir.join("f")
    }

    fn worker_dir(&self) -> PathBuf {
        self.dir.join("bin")
    }

    fn raw(&self, line: &str) -> Value {
        let mut stream = UnixStream::connect(self.folder().join("s.sock")).unwrap();
        writeln!(stream, "{line}").unwrap();
        let mut reply = String::new();
        BufReader::new(stream).read_line(&mut reply).unwrap();
        serde_json::from_str(&reply).unwrap()
    }

    fn ask(&self, op: &str, args: Value) -> Value {
        self.raw(&json!({"token": self.token, "id": 1, "op": op, "args": args}).to_string())
    }

    fn cua(&self, tool: &str, args: Value) -> Value {
        self.ask("cua", json!({"tool": tool, "args": args}))
    }

    /// The tool calls the worker received (not `initialize`).
    fn calls(&self) -> Vec<Value> {
        std::fs::read_to_string(self.worker_dir().join("requests.log"))
            .unwrap_or_default()
            .lines()
            .map(|l| serde_json::from_str::<Value>(l).unwrap())
            .filter(|r| r["operation"] == "call")
            .collect()
    }

    fn called(&self, tool: &str) -> usize {
        self.calls().iter().filter(|r| r["name"] == tool).count()
    }

    fn spawns(&self) -> usize {
        std::fs::read_to_string(self.worker_dir().join("spawns.log"))
            .unwrap_or_default()
            .lines()
            .count()
    }
}

impl Drop for Hands {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

fn code(reply: &Value) -> &str {
    reply["refused"]["code"].as_str().unwrap_or("")
}

/// Start Hands with the fake worker; `prepare` may write mode.json or return a sha256
/// the worker must have.
fn start(name: &str, prepare: impl FnOnce(&Path, &Path) -> Option<String>) -> Hands {
    // Short: macOS socket paths are capped at 103 bytes.
    let dir = PathBuf::from("/tmp").join(format!("hc-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let bin = dir.join("bin");
    std::fs::create_dir_all(&bin).unwrap();
    let worker = bin.join("cua-driver");
    std::fs::write(&worker, FAKE).unwrap();
    std::fs::set_permissions(&worker, std::fs::Permissions::from_mode(0o755)).unwrap();
    let pinned = prepare(&bin, &worker);
    let folder = dir.join("f");
    let config = arslan_hands::server::Config {
        folder: folder.clone(),
        agent_desktop: PathBuf::from("/nonexistent/agent-desktop"),
        agent_desktop_sha256: None,
        home: dir.clone(),
        idle: Duration::from_secs(3600),
        team: None,
        cua_driver: Some(worker),
        cua_driver_sha256: pinned,
        host_bundle_id: "com.arslan.desktop.hands.test".into(),
    };
    std::thread::spawn(move || {
        let _ = arslan_hands::server::run(config);
    });
    let ready = folder.join("ready.json");
    let started = Instant::now();
    while !ready.exists() {
        assert!(
            started.elapsed() < Duration::from_secs(5),
            "Hands did not start"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
    let doc: Value = serde_json::from_slice(&std::fs::read(&ready).unwrap()).unwrap();
    Hands {
        dir,
        token: doc["token"].as_str().unwrap().to_string(),
    }
}

fn plain(name: &str) -> Hands {
    start(name, |_, _| None)
}

#[test]
fn the_worker_runs_on_hands_terms_only() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    // A canary in Hands' own environment (the test process is Hands' process here).
    std::env::set_var("HANDS_TEST_CANARY", "leaked");
    let hands = plain("env");
    assert_eq!(hands.cua("check_permissions", json!({}))["ok"], true);
    let argv: Vec<String> = serde_json::from_str(
        &std::fs::read_to_string(hands.worker_dir().join("argv.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(argv[..2], ["__private-worker", "--generation"]);
    assert!(argv[2].len() == 32 && argv[2].bytes().all(|b| b.is_ascii_hexdigit()));
    let env: serde_json::Map<String, Value> = serde_json::from_str(
        &std::fs::read_to_string(hands.worker_dir().join("env.json")).unwrap(),
    )
    .unwrap();
    assert!(
        !env.contains_key("HANDS_TEST_CANARY"),
        "Hands' own environment reached the worker"
    );
    // Exactly what Hands sets. (macOS's /usr/bin/python3 shim, which runs this fake
    // worker, adds its own SDK variables after Hands' exec: not Hands' doing.)
    let shim = ["CPATH", "LIBRARY_PATH", "MANPATH", "SDKROOT"];
    let mut names: Vec<&str> = env
        .keys()
        .map(String::as_str)
        .filter(|k| !k.starts_with("__CF") && !shim.contains(k))
        .collect();
    names.sort_unstable();
    assert_eq!(
        names,
        [
            "CUA_DRIVER_RS_TELEMETRY_ENABLED",
            "CUA_DRIVER_WINDOW_CHANGE_TIMEOUT_MS",
            "DO_NOT_TRACK",
            "HOME",
            "LANG",
            "PATH"
        ]
    );
    assert_eq!(
        env["HOME"],
        hands.folder().join("cua-home").display().to_string()
    );
    assert_eq!(env["PATH"], "/usr/bin:/bin:/usr/sbin:/sbin");
    assert_eq!(env["DO_NOT_TRACK"], "1");
    assert_eq!(env["CUA_DRIVER_RS_TELEMETRY_ENABLED"], "false");
    let mode = std::fs::metadata(hands.folder().join("cua-home"))
        .unwrap()
        .permissions()
        .mode()
        & 0o777;
    assert_eq!(mode, 0o700);
    // One worker for the whole run: a second call does not start another.
    hands.cua("list_apps", json!({}));
    assert_eq!(hands.spawns(), 1);
    // The worker's initialization asked for the standard mode only.
    let init: Value = std::fs::read_to_string(hands.worker_dir().join("requests.log"))
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str::<Value>(l).unwrap())
        .find(|r| r["operation"] == "initialize")
        .unwrap();
    assert_eq!(
        init["arguments"]["host_bundle_id"],
        "com.arslan.desktop.hands.test"
    );
    assert_eq!(
        init["arguments"]["configured_driver"]["authorization"]["allowed_modes"],
        json!(["standard"])
    );
    let status = hands.ask("status", json!({}));
    assert_eq!(status["cua_driver"], true);
}

#[test]
fn a_worker_that_cannot_prove_it_is_hands_own_is_not_used() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("proof", |bin, _| {
        std::fs::write(bin.join("mode.json"), r#"{"bad_proof": true}"#).unwrap();
        None
    });
    let reply = hands.cua("list_apps", json!({}));
    assert_eq!(code(&reply), "bad_output", "{reply}");
    assert!(
        hands.calls().is_empty(),
        "no tool reached a worker that failed its proof"
    );
}

#[test]
fn a_swapped_worker_is_never_started() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("swap", |_, _| Some("0".repeat(64)));
    let reply = hands.cua("list_apps", json!({}));
    assert_eq!(code(&reply), "helper_failed", "{reply}");
    assert_eq!(
        hands.spawns(),
        0,
        "a binary that does not match the record never runs"
    );
    assert_eq!(hands.ask("status", json!({}))["cua_driver_pinned"], false);
}

#[test]
fn only_reads_and_background_actions_reach_the_worker() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = plain("tools");
    for tool in [
        "clipboard_read",
        "browser_navigate",
        "get_desktop_state",
        "set_config",
        "check_for_update",
        "kill_app",
        "launch_app",
        "invoke_menu",
        "drag",
    ] {
        assert_eq!(
            code(&hands.cua(tool, json!({"pid": 100}))),
            "op_not_allowed",
            "{tool}"
        );
    }
    assert_eq!(
        code(&hands.cua(
            "type_text",
            json!({"pid": 100, "text": "x", "scope": "desktop"})
        )),
        "arg_not_allowed"
    );
    assert_eq!(
        code(&hands.cua(
            "get_window_state",
            json!({"pid": 100, "window_id": 1, "screenshot_out_file": "/tmp/x.png"})
        )),
        "arg_not_allowed"
    );
    assert_eq!(
        code(&hands.cua(
            "click",
            json!({"pid": 100, "x": 5, "y": 5, "delivery_mode": "foreground"})
        )),
        "borrow_not_allowed"
    );
    assert!(
        hands.calls().is_empty(),
        "nothing refused reached the worker: {:?}",
        hands.calls()
    );
}

#[test]
fn the_never_list_and_the_tiers_hold() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = plain("tier");
    let apps = hands.cua("list_apps", json!({}));
    let names: Vec<&str> = apps["result"]["structuredContent"]["apps"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a["name"].as_str().unwrap())
        .collect();
    assert!(!names.contains(&"Keychain Access"), "{names:?}");
    assert!(names.contains(&"Notes"));
    assert!(
        apps["result"].get("content").is_none(),
        "the text part names every app"
    );
    assert_eq!(
        code(&hands.cua("get_window_state", json!({"pid": 300, "window_id": 1}))),
        "app_denied"
    );
    assert_eq!(
        code(&hands.cua("click", json!({"pid": 400, "x": 5, "y": 5}))),
        "app_look_only"
    );
    assert_eq!(
        hands.cua("get_window_state", json!({"pid": 400, "window_id": 1}))["ok"],
        true,
        "browsers may be read"
    );
    assert_eq!(
        code(&hands.cua("press_key", json!({"pid": 500, "key": "return"}))),
        "app_click_only"
    );
    assert_eq!(
        code(&hands.cua("get_window_state", json!({"pid": 999, "window_id": 1}))),
        "app_not_running"
    );
    // The user's own additions to the never-list count too.
    let mine = hands.ask("cua", json!({"tool": "get_window_state", "args": {"pid": 200, "window_id": 1}, "never": ["Notes"]}));
    assert_eq!(code(&mine), "app_denied");
    assert_eq!(hands.called("click") + hands.called("press_key"), 0);
}

#[test]
fn an_element_token_must_come_from_a_window_state_hands_relayed() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = plain("tok");
    let early = hands.cua("click", json!({"pid": 100, "element_token": "s00000001:0"}));
    assert_eq!(code(&early), "ref_unknown");
    let state = hands.cua("get_window_state", json!({"pid": 100, "window_id": 1}));
    assert_eq!(state["ok"], true);
    // The system's Apple menu (recent documents, the user's name) never leaves Hands.
    assert!(!state.to_string().contains("Log Out Someone"), "{state}");
    let click = hands.cua("click", json!({"pid": 100, "element_token": "s00000001:0"}));
    assert_eq!(click["ok"], true, "{click}");
    assert_eq!(click["completion"], "completed");
    // The fake answers effect "confirmed": the shared vocabulary says done.
    assert_eq!(click["outcome"], "done");
    assert_eq!(click["mode_used"], "background");
    // A token of one app spent in another is refused, whatever the pid says.
    let elsewhere = hands.cua("click", json!({"pid": 200, "element_token": "s00000001:0"}));
    assert_eq!(code(&elsewhere), "ref_wrong_app");
    assert_eq!(hands.called("click"), 1);
    // Hands chose the session label, not the caller.
    let sent = hands
        .calls()
        .into_iter()
        .find(|r| r["name"] == "click")
        .unwrap();
    assert_eq!(sent["arguments"]["session"], "arslan");
}

#[test]
fn password_fields_are_never_typed_into() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = plain("pw");
    hands.cua("get_window_state", json!({"pid": 100, "window_id": 1}));
    for token in ["s00000001:2", "s00000001:3"] {
        let reply = hands.cua(
            "type_text",
            json!({"pid": 100, "element_token": token, "text": "hunter2"}),
        );
        assert_eq!(code(&reply), "password_field", "{token}: {reply}");
        let set = hands.cua(
            "set_value",
            json!({"pid": 100, "element_token": token, "value": "hunter2"}),
        );
        assert_eq!(code(&set), "password_field", "{token}");
    }
    assert_eq!(hands.called("type_text") + hands.called("set_value"), 0);
    let ok = hands.cua(
        "type_text",
        json!({"pid": 100, "element_token": "s00000001:1", "text": "Groceries"}),
    );
    assert_eq!(ok["ok"], true, "{ok}");
    // On Linux there is no live accessibility to ask: the reply says the check rested on
    // the role and label alone.
    #[cfg(not(target_os = "macos"))]
    assert_eq!(ok["secure_check"], "label_only");
}

#[test]
fn a_worker_that_dies_mid_request_is_unknown_then_replaced() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = plain("crash");
    hands.cua("get_window_state", json!({"pid": 100, "window_id": 1}));
    let died = hands.cua(
        "type_text",
        json!({"pid": 100, "element_token": "s00000001:1", "text": "crash"}),
    );
    assert_eq!(code(&died), "engine_died", "{died}");
    assert_eq!(
        died["completion"], "unknown",
        "it may have typed: never resent"
    );
    assert_eq!(hands.called("type_text"), 1);
    let again = hands.cua("list_apps", json!({}));
    assert_eq!(again["ok"], true, "{again}");
    assert_eq!(hands.spawns(), 2, "the next request starts a new worker");
}

#[test]
fn stop_ends_a_request_in_the_worker_within_a_second() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = plain("stop");
    hands.cua("get_window_state", json!({"pid": 100, "window_id": 1}));
    let socket = hands.folder().join("s.sock");
    let token = hands.token.clone();
    let slow = std::thread::spawn(move || {
        let mut stream = UnixStream::connect(socket).unwrap();
        let req = json!({"token": token, "op": "cua", "args": {"tool": "type_text",
            "args": {"pid": 100, "element_token": "s00000001:1", "text": "hang"}}});
        writeln!(stream, "{req}").unwrap();
        let mut reply = String::new();
        BufReader::new(stream).read_line(&mut reply).unwrap();
        serde_json::from_str::<Value>(&reply).unwrap()
    });
    let started = Instant::now();
    while hands.called("type_text") == 0 {
        assert!(started.elapsed() < Duration::from_secs(5));
        std::thread::sleep(Duration::from_millis(10));
    }
    let stop_at = Instant::now();
    let stopped = hands.ask("stop", json!({}));
    assert_eq!(stopped["killed"], true, "{stopped}");
    let reply = slow.join().unwrap();
    assert!(
        stop_at.elapsed() < Duration::from_secs(1),
        "stopped in {:?}",
        stop_at.elapsed()
    );
    assert_eq!(code(&reply), "stopped_by_user", "{reply}");
    assert_eq!(reply["completion"], "unknown");
    // Stop ends what was running, not Hands: the next request gets a new worker.
    assert_eq!(hands.cua("list_apps", json!({}))["ok"], true);
}

#[test]
fn a_request_id_is_answered_once_for_cua_too() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = plain("once");
    hands.cua("get_window_state", json!({"pid": 100, "window_id": 1}));
    let line = json!({"token": hands.token, "id": "cua-click-1", "op": "cua",
                      "args": {"tool": "click", "args": {"pid": 100, "element_token": "s00000001:0"}}})
    .to_string();
    let first = hands.raw(&line);
    let again = hands.raw(&line);
    assert_eq!(first["ok"], true);
    assert_eq!(again["result"], first["result"]);
    assert_eq!(hands.called("click"), 1, "the same id did not click twice");
}

#[test]
fn an_ended_session_is_renewed_once_and_a_refusal_is_said() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = plain("sess");
    // The label's session has ended: Hands starts a fresh label and the call succeeds.
    let apps = hands.ask(
        "cua",
        json!({"tool": "list_apps", "args": {}, "session": "expired"}),
    );
    assert_eq!(apps["ok"], true, "{apps}");
    assert!(!apps["result"]["structuredContent"]["apps"]
        .as_array()
        .unwrap()
        .is_empty());
    let sessions: Vec<String> = hands
        .calls()
        .iter()
        .filter(|r| r["name"] == "list_apps")
        .map(|r| r["arguments"]["session"].as_str().unwrap().to_string())
        .collect();
    assert_eq!(sessions, ["expired", "expired-1"]);
    // Cua's own "no" is a refusal, never an ok with an empty result.
    hands.cua("get_window_state", json!({"pid": 100, "window_id": 1}));
    let refused = hands.cua(
        "type_text",
        json!({"pid": 100, "element_token": "s00000001:1", "text": "refuse-me"}),
    );
    assert_eq!(refused["ok"], false, "{refused}");
    assert_eq!(code(&refused), "engine_refused");
    assert!(refused["refused"]["message"]
        .as_str()
        .unwrap()
        .contains("element_disabled"));
    assert_eq!(refused["outcome"], "refused");
}
