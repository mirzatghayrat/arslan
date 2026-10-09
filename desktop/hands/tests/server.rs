//! Hands' socket end to end, with a fake agent-desktop that answers from the
//! contract fixtures: the token, the never-list, refs bound to their app,
//! password fields, Stop. Runs on Linux CI too (no Accessibility involved).

use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant};

// The runner's Stop generation is process-wide: these tests take turns.
static SERIAL: Mutex<()> = Mutex::new(());

const FAKE: &str = r#"#!/usr/bin/env python3
import json, sys, time
from pathlib import Path
here = Path(sys.argv[0]).resolve().parent
argv = sys.argv[1:]
(here / "calls.log").open("a").write(json.dumps(argv) + "\n")
def out(env, code=0):
    print(json.dumps(env)); sys.exit(code)
if argv[:1] == ["list-apps"]:
    out(json.loads((here / "apps.json").read_text()))
if argv[:1] == ["get"] and "--property=states" in argv:
    out({"version": "2.4", "ok": True, "command": "get", "data": {"property": "states",
         "value": ["secure"] if argv[-1].endswith(":e2") else []}})
if argv[:1] == ["wait"] and "--text=slow" in argv:
    time.sleep(30)
if argv[:1] == ["press"] and (here / "nofocus").exists():
    out({"version": "2.4", "ok": False, "command": "press", "error": {"code": "ACTION_FAILED",
         "message": "Application has no verified focused element for keyboard delivery",
         "details": {"physical_delivery_started": False}}}, 1)
if argv[:2] == ["session", "start"]:
    out({"version": "2.4", "ok": True, "command": "session", "data": {"session_id": "run-1-2-0"}})
if argv[:1] in (["session"], ["cursor-overlay"]):
    out({"version": "2.4", "ok": True, "command": argv[0], "data": {}})
for case in sorted((here / "cases").glob("*.json")):
    c = json.loads(case.read_text())
    if c["argv"] == [a.replace("sfixture0", "sfixture0") for a in argv]:
        out(c["envelope"], c["exit"] or 0)
out({"version": "2.4", "ok": False, "command": argv[0] if argv else "", "error": {"code": "INTERNAL", "message": "fake: " + " ".join(argv)}}, 1)
"#;

struct Hands {
    dir: PathBuf,
    token: String,
}

fn apps() -> Value {
    json!({"version": "2.4", "ok": true, "command": "list-apps", "data": {"apps": [
        {"name": "Hands Fixture", "bundle_id": "com.arslan.hands-fixture", "pid": 100},
        {"name": "Notes", "bundle_id": "com.apple.Notes", "pid": 200},
        {"name": "Keychain Access", "bundle_id": "com.apple.keychainaccess", "pid": 300},
        {"name": "Safari", "bundle_id": "com.apple.Safari", "pid": 400},
        {"name": "Terminal", "bundle_id": "com.apple.Terminal", "pid": 500},
        // Above macOS's largest pid: a screenshot test must never find a real window.
        {"name": "Capture Target", "bundle_id": "com.arslan.capture-target", "pid": 1_000_600}]}})
}

fn refmap(home: &Path, session: Option<&str>) {
    let base = match session {
        Some(s) => home.join("sessions").join(s),
        None => home.to_path_buf(),
    };
    let dir = base.join("snapshots").join("sfixture0");
    std::fs::create_dir_all(&dir).unwrap();
    let entry = |pid: i64, role: &str, name: &str| json!({"pid": pid, "role": role, "name": name, "available_actions": ["Click", "SetValue"]});
    let map = json!({"inner": {
        "@e1": entry(100, "textfield", "Title"), "@e2": entry(100, "textfield", "Password"),
        "@e3": entry(100, "button", "Save"), "@e5": entry(100, "combobox", "Color"),
        "@e6": entry(100, "scrollarea", "Rows"), "@e9": entry(200, "button", "New Note"),
        "@e10": entry(300, "button", "Show"), "@e11": entry(500, "textfield", "Shell")}, "counter": 11});
    std::fs::write(dir.join("refmap.json"), map.to_string()).unwrap();
}

fn start(name: &str) -> Hands {
    start_pinned(name, |_| None)
}

/// `pin` gets the fake agent-desktop's path and returns the sha256 to require.
fn start_pinned(name: &str, pin: impl FnOnce(&Path) -> Option<String>) -> Hands {
    // Short: macOS socket paths are capped at 103 bytes.
    let dir = PathBuf::from("/tmp").join(format!("hh-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let bin = dir.join("bin");
    std::fs::create_dir_all(bin.join("cases")).unwrap();
    let fake = bin.join("agent-desktop");
    std::fs::write(&fake, FAKE).unwrap();
    std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o755)).unwrap();
    std::fs::write(bin.join("apps.json"), apps().to_string()).unwrap();
    let fixtures =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/hands_contract");
    for e in std::fs::read_dir(fixtures).unwrap().flatten() {
        std::fs::copy(e.path(), bin.join("cases").join(e.file_name())).unwrap();
    }
    let folder = dir.join("f");
    let pinned = pin(&fake);
    let config = arslan_hands::server::Config {
        folder: folder.clone(),
        agent_desktop: fake,
        agent_desktop_sha256: pinned,
        home: dir.clone(),
        idle: Duration::from_secs(3600),
        team: None,
        cua_driver: None,
        cua_driver_sha256: None,
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
    refmap(&folder.join("ad"), None);
    refmap(&folder.join("ad"), Some("run-1-2-0"));
    Hands {
        dir,
        token: doc["token"].as_str().unwrap().to_string(),
    }
}

impl Hands {
    fn folder(&self) -> PathBuf {
        self.dir.join("f")
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

    fn calls(&self) -> Vec<Vec<String>> {
        std::fs::read_to_string(self.dir.join("bin/calls.log"))
            .unwrap_or_default()
            .lines()
            .map(|l| serde_json::from_str(l).unwrap())
            .collect()
    }

    fn acted(&self) -> Vec<String> {
        self.calls()
            .into_iter()
            .filter(|c| {
                ["click", "type", "set-value", "select", "scroll", "press"].contains(&c[0].as_str())
            })
            .map(|c| c[0].clone())
            .collect()
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

#[test]
fn the_folder_socket_and_token_are_private() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("priv");
    let mode = |p: PathBuf| std::fs::metadata(p).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode(hands.folder()), 0o700);
    assert_eq!(mode(hands.folder().join("s.sock")), 0o600);
    assert_eq!(mode(hands.folder().join("ready.json")), 0o600);
    assert_eq!(hands.token.len(), 64);
    // A second Hands on the same folder refuses to start.
    let second = arslan_hands::server::bind(&arslan_hands::server::Config {
        folder: hands.folder(),
        agent_desktop: PathBuf::from("/nonexistent"),
        agent_desktop_sha256: None,
        home: hands.dir.clone(),
        idle: Duration::from_secs(1),
        team: None,
        cua_driver: None,
        cua_driver_sha256: None,
        host_bundle_id: "com.arslan.desktop.hands.test".into(),
    });
    assert!(second.unwrap_err().contains("already running"));
}

#[test]
fn without_the_token_nothing_runs() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("tok");
    let reply = hands.raw(&json!({"token": "0".repeat(64), "op": "click", "args": {"app": "Hands Fixture", "ref": "@sfixture0:e3"}}).to_string());
    assert_eq!(code(&reply), "bad_token");
    assert_eq!(code(&hands.raw("not json")), "bad_request");
    assert!(hands.calls().is_empty(), "agent-desktop never started");
}

#[test]
fn only_the_contract_ops_exist() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("ops");
    for op in [
        "launch",
        "screenshot",
        "clipboard_get",
        "list_notifications",
        "batch",
        "mouse_click",
    ] {
        assert_eq!(
            code(&hands.ask(op, json!({"app": "Hands Fixture"}))),
            "op_not_allowed",
            "{op}"
        );
    }
    let ok = hands.ask(
        "click",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e3"}),
    );
    assert_eq!(ok["ok"], true, "{ok}");
    assert_eq!(ok["envelope"]["command"], "click");
    assert_eq!(ok["app"]["bundle_id"], "com.arslan.hands-fixture");
    assert_eq!(ok["target"]["name"], "Save");
}

#[test]
fn denied_apps_are_not_even_looked_at_browsers_only_looked_at_terminals_not_typed_in() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("tiers");
    assert_eq!(
        code(&hands.ask("snapshot", json!({"app": "Keychain Access"}))),
        "app_denied"
    );
    assert_eq!(
        code(&hands.ask("snapshot", json!({"app": "com.apple.keychainaccess"}))),
        "app_denied"
    );
    assert_eq!(
        code(&hands.ask(
            "click",
            json!({"app": "Keychain Access", "ref": "@sfixture0:e10"})
        )),
        "app_denied"
    );
    assert_eq!(
        code(&hands.ask("press", json!({"app": "Safari", "keys": "return"}))),
        "app_look_only"
    );
    assert_eq!(
        code(&hands.ask(
            "set_value",
            json!({"app": "Terminal", "ref": "@sfixture0:e11", "value": "rm -rf ~"})
        )),
        "app_click_only"
    );
    assert_eq!(
        code(&hands.ask("press", json!({"app": "Terminal", "keys": "return"}))),
        "app_click_only"
    );
    // The user's own additions are honoured; nothing the backend sends lifts a built-in one.
    assert_eq!(
        code(&hands.ask("snapshot", json!({"app": "Notes", "never": ["Notes"]}))),
        "app_denied"
    );
    let listed = hands.ask("list_apps", json!({}));
    let names: Vec<&str> = listed["apps"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a["name"].as_str().unwrap())
        .collect();
    assert!(
        !names.contains(&"Keychain Access") && names.contains(&"Notes"),
        "{names:?}"
    );
    assert!(hands.acted().is_empty());
    assert!(
        !hands.calls().iter().any(|c| c[0] == "snapshot"),
        "a denied app is never read"
    );
}

#[test]
fn a_ref_is_spent_only_in_the_app_it_came_from() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("refs");
    // e9 belongs to Notes (pid 200); the request names Hands Fixture.
    assert_eq!(
        code(&hands.ask(
            "click",
            json!({"app": "Hands Fixture", "ref": "@sfixture0:e9"})
        )),
        "ref_wrong_app"
    );
    assert_eq!(
        code(&hands.ask(
            "click",
            json!({"app": "Hands Fixture", "ref": "@sfixture0:e99"})
        )),
        "ref_unknown"
    );
    assert_eq!(
        code(&hands.ask("click", json!({"app": "Hands Fixture", "ref": "@e3"}))),
        "bad_ref"
    );
    // A ref from a job's session does not resolve outside it, and vice versa.
    let in_session = hands.ask(
        "click",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e3", "session": "run-1-2-0"}),
    );
    assert_eq!(in_session["ok"], true, "{in_session}");
    assert!(hands
        .calls()
        .iter()
        .any(|c| c.contains(&"--session=run-1-2-0".to_string())));
    assert_eq!(hands.acted(), ["click"]);
}

#[test]
fn password_fields_are_never_typed_into() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("pw");
    assert_eq!(
        code(&hands.ask(
            "set_value",
            json!({"app": "Hands Fixture", "ref": "@sfixture0:e2", "value": "hunter2"})
        )),
        "password_field"
    );
    assert_eq!(
        code(&hands.ask(
            "type",
            json!({"app": "Hands Fixture", "ref": "@sfixture0:e2", "text": "hunter2"})
        )),
        "password_field"
    );
    assert!(hands.acted().is_empty());
    let described = hands.ask(
        "describe",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e2"}),
    );
    assert_eq!(described["target"]["password"], true);
    let title = hands.ask(
        "set_value",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e1", "value": "Weekend plan"}),
    );
    assert_eq!(title["ok"], true, "{title}");
    assert_eq!(hands.acted(), ["set-value"]);
}

#[test]
fn stop_kills_the_command_in_flight_within_a_second() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("stop");
    let socket = hands.folder().join("s.sock");
    let token = hands.token.clone();
    let slow = std::thread::spawn(move || {
        let mut stream = UnixStream::connect(socket).unwrap();
        let req = json!({"token": token, "op": "wait", "args": {"app": "Hands Fixture", "text": "slow", "timeout_ms": 20000}});
        writeln!(stream, "{req}").unwrap();
        let mut reply = String::new();
        BufReader::new(stream).read_line(&mut reply).unwrap();
        serde_json::from_str::<Value>(&reply).unwrap()
    });
    let started = Instant::now();
    while !hands.calls().iter().any(|c| c[0] == "wait") {
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
    // Later requests work again: Stop ends what was running, not Hands.
    assert_eq!(
        hands.ask(
            "click",
            json!({"app": "Hands Fixture", "ref": "@sfixture0:e3"})
        )["ok"],
        true
    );
}

#[test]
fn values_reach_agent_desktop_as_values() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("argv");
    let reply = hands.ask(
        "set_value",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e1", "value": "--headed"}),
    );
    assert_eq!(reply["ok"], true, "{reply}");
    let call = hands
        .calls()
        .into_iter()
        .find(|c| c[0] == "set-value")
        .unwrap();
    assert_eq!(call, ["set-value", "--", "@sfixture0:e1", "--headed"]);
}

#[test]
fn a_swapped_agent_desktop_is_never_run() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    // Pinned to the real fake: it runs.
    let good = start_pinned("pin-ok", |bin| {
        Some(arslan_hands::integrity::sha256_file(bin).unwrap())
    });
    let ok = good.ask(
        "click",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e3"}),
    );
    assert_eq!(ok["ok"], true, "{ok}");
    drop(good);
    // Pinned to a different build (what a swapped file looks like): nothing runs.
    let swapped = start_pinned("pin-bad", |_| Some("0".repeat(64)));
    let refused = swapped.ask(
        "click",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e3"}),
    );
    assert_eq!(code(&refused), "helper_failed", "{refused}");
    assert!(refused["refused"]["message"]
        .as_str()
        .unwrap()
        .contains("not the build"));
    assert!(
        swapped.calls().is_empty(),
        "the swapped binary never started"
    );
}

// ── P0 (spec 2026-10-08-0157 §1): at most once, one deadline code ───────────

fn ask_id(hands: &Hands, id: &str, op: &str, args: Value) -> Value {
    hands.raw(&json!({"token": hands.token, "id": id, "op": op, "args": args}).to_string())
}

#[test]
fn the_same_request_id_runs_once() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("once");
    let click = json!({"app": "Hands Fixture", "ref": "@sfixture0:e3"});
    let first = ask_id(&hands, "click-abc", "click", click.clone());
    let again = ask_id(&hands, "click-abc", "click", click.clone());
    assert_eq!(first["ok"], true, "{first}");
    assert_eq!(hands.acted(), ["click"], "a repeated id ran again");
    assert_eq!(again["envelope"], first["envelope"]);
    // Another id is another action.
    ask_id(&hands, "click-def", "click", click);
    assert_eq!(hands.acted(), ["click", "click"]);
}

#[test]
fn a_lost_answer_can_be_fetched_by_its_id() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("answ");
    let pid = std::process::id();
    let unknown = hands.ask("answer_of", json!({"id": "never-sent", "wait_ms": 10}));
    assert_eq!(unknown["state"], "unknown_id", "{unknown}");
    assert_eq!(unknown["pid"], pid);
    let done = ask_id(
        &hands,
        "click-xyz",
        "click",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e3"}),
    );
    let fetched = hands.ask("answer_of", json!({"id": "click-xyz", "wait_ms": 10}));
    assert_eq!(fetched["state"], "done", "{fetched}");
    assert_eq!(fetched["answer"]["envelope"], done["envelope"]);
    assert_eq!(hands.acted(), ["click"], "answer_of never runs anything");
}

#[test]
fn answer_of_waits_for_a_request_still_running_and_deadlines_say_timeout() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("wait");
    let socket = hands.folder().join("s.sock");
    let token = hands.token.clone();
    // The fake agent-desktop sleeps on "slow"; Hands' deadline (100 ms + 5 s) cuts it.
    std::thread::spawn(move || {
        let mut stream = UnixStream::connect(socket).unwrap();
        let req = json!({"token": token, "id": "wait-slow", "op": "wait",
                         "args": {"app": "Hands Fixture", "text": "slow", "timeout_ms": 100}});
        writeln!(stream, "{req}").unwrap();
        // The caller gives up without reading: its answer must still be kept.
    });
    let started = Instant::now();
    while !hands.calls().iter().any(|c| c[0] == "wait") {
        assert!(started.elapsed() < Duration::from_secs(5));
        std::thread::sleep(Duration::from_millis(10));
    }
    let fetched = hands.ask("answer_of", json!({"id": "wait-slow", "wait_ms": 15000}));
    assert_eq!(fetched["state"], "done", "{fetched}");
    assert_eq!(code(&fetched["answer"]), "TIMEOUT", "{fetched}");
}

#[test]
fn actions_say_what_they_achieved_in_one_vocabulary() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("outc");
    // 08_click: delivered_unverified; 10_set_value: delivered_verified.
    let click = hands.ask(
        "click",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e3"}),
    );
    assert_eq!(click["outcome"], "sent_unconfirmed", "{click}");
    assert_eq!(click["mode_used"], "background");
    let set = hands.ask(
        "set_value",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e1", "value": "Weekend plan"}),
    );
    assert_eq!(set["outcome"], "done", "{set}");
    // An action agent-desktop reported as an error has no outcome: its code says why.
    let failed = hands.ask(
        "set_value",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e1", "value": "not in the fixtures"}),
    );
    assert_eq!(failed["envelope"]["ok"], false);
    assert!(failed["outcome"].is_null(), "{failed}");
    // A read has no outcome.
    let apps = hands.ask("list_apps", json!({}));
    assert!(apps.get("outcome").is_none_or(Value::is_null), "{apps}");
}

#[test]
fn a_screenshot_follows_the_look_rules_and_never_runs_agent_desktop() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("shot");
    assert_eq!(
        code(&hands.ask("capture_window", json!({"app": "Keychain Access"}))),
        "app_denied"
    );
    assert_eq!(
        code(&hands.ask(
            "capture_window",
            json!({"app": "Notes", "never": ["Notes"]})
        )),
        "app_denied"
    );
    assert_eq!(
        code(&hands.ask("capture_window", json!({"app": "Notes", "window": "w-x"}))),
        "bad_request"
    );
    // An app that exists only in the fake list: the capture runs and finds nothing to show
    // (no grant on CI, no such process anywhere, or not macOS) - never an image.
    let shot = hands.ask(
        "capture_window",
        json!({"app": "Capture Target", "window": "w-26104"}),
    );
    assert!(
        [
            "screen_recording_off",
            "window_not_found",
            "not_supported",
            "needs_macos_14"
        ]
        .contains(&code(&shot)),
        "{shot}"
    );
    assert!(shot.get("capture").is_none());
    // Hands captures itself: agent-desktop was asked only which apps run.
    assert!(
        hands.calls().iter().all(|c| c[0] == "list-apps"),
        "{:?}",
        hands.calls()
    );
}

#[test]
fn a_screenshot_does_not_wait_behind_a_command_in_flight() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    let hands = start("beside");
    let socket = hands.folder().join("s.sock");
    let token = hands.token.clone();
    let slow = std::thread::spawn(move || {
        let mut stream = UnixStream::connect(socket).unwrap();
        let req = json!({"token": token, "op": "wait", "args": {"app": "Hands Fixture", "text": "slow", "timeout_ms": 20000}});
        writeln!(stream, "{req}").unwrap();
        let mut reply = String::new();
        BufReader::new(stream).read_line(&mut reply).unwrap();
    });
    let started = Instant::now();
    while !hands.calls().iter().any(|c| c[0] == "wait") {
        assert!(started.elapsed() < Duration::from_secs(5));
        std::thread::sleep(Duration::from_millis(10));
    }
    // The wait holds Hands' one-at-a-time lock for 30 s; the screenshot answers anyway.
    let asked = Instant::now();
    let shot = hands.ask("capture_window", json!({"app": "Keychain Access"}));
    assert_eq!(code(&shot), "app_denied");
    assert!(
        asked.elapsed() < Duration::from_secs(5),
        "{:?}",
        asked.elapsed()
    );
    hands.ask("stop", json!({}));
    slow.join().unwrap();
}

// The structural-change check, with accessibility stood in for: how many sheets the fixture's
// window has right now.
static SHEETS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

fn fixture_structure(pid: i32) -> Option<arslan_hands::structure::Structure> {
    (pid == 100).then(|| arslan_hands::structure::Structure {
        windows: vec![arslan_hands::structure::Window {
            id: 7,
            subrole: "AXStandardWindow".into(),
            title: "Hands Fixture".into(),
            sheets: SHEETS.load(std::sync::atomic::Ordering::SeqCst),
        }],
        focused: Some(7),
        menu_open: false,
    })
}

#[test]
fn an_action_on_a_look_older_than_a_new_sheet_is_refused_and_nothing_runs() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    SHEETS.store(0, std::sync::atomic::Ordering::SeqCst);
    arslan_hands::structure::set_probe_for_tests(Some(fixture_structure));
    let hands = start("struct");
    let click = || {
        hands.ask(
            "click",
            json!({"app": "Hands Fixture", "ref": "@sfixture0:e3"}),
        )
    };
    assert_eq!(
        hands.ask("snapshot", json!({"app": "Hands Fixture"}))["ok"],
        true
    );
    assert_eq!(click()["ok"], true, "an action on a current look runs");
    assert_eq!(
        click()["ok"],
        true,
        "values are not structure: a second action on one look runs"
    );
    SHEETS.store(1, std::sync::atomic::Ordering::SeqCst); // a sheet opens after the look
    let refused = click();
    assert_eq!(code(&refused), "changed", "{refused}");
    assert!(refused["refused"]["message"]
        .as_str()
        .unwrap()
        .contains("a sheet or popover opened"));
    assert_eq!(
        hands.acted().len(),
        2,
        "the refused click never reached agent-desktop"
    );
    assert_eq!(
        hands.ask("snapshot", json!({"app": "Hands Fixture"}))["ok"],
        true
    );
    assert_eq!(click()["ok"], true, "a new look makes it current again");
    arslan_hands::structure::set_probe_for_tests(None);
}

// Menus, with accessibility stood in for: the fixture's menu bar, and what got pressed.
static PRESSED: Mutex<Vec<Vec<String>>> = Mutex::new(Vec::new());

fn fixture_menus(pid: i32) -> Option<Vec<arslan_hands::menus::MenuItem>> {
    let item = |path: &[&str], enabled: bool, shortcut: Option<(&str, i64)>| {
        arslan_hands::menus::MenuItem {
            path: path.iter().map(|s| s.to_string()).collect(),
            enabled,
            shortcut: shortcut.map(|(c, m)| (c.to_string(), m)),
        }
    };
    (pid == 100).then(|| {
        vec![
            item(&["Format", "Font", "Bold"], true, Some(("b", 0))),
            item(&["File", "Export"], false, None),
        ]
    })
}

fn press_fixture_menu(pid: i32, path: &[String]) -> Option<bool> {
    PRESSED.lock().unwrap().push(path.to_vec());
    Some(pid == 100)
}

fn with_menus() {
    PRESSED.lock().unwrap().clear();
    arslan_hands::menus::set_stand_in_for_tests(Some((fixture_menus, press_fixture_menu)));
}

#[test]
fn a_menu_item_is_pressed_by_its_path_under_the_action_rules() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    with_menus();
    let hands = start("menu");
    let bold = hands.ask(
        "menu",
        json!({"app": "Hands Fixture", "path": ["format", "Font", "Bold"]}),
    );
    assert_eq!(bold["ok"], true, "{bold}");
    assert_eq!(bold["route"], "menu_item");
    assert_eq!(bold["outcome"], "sent_unconfirmed");
    assert_eq!(
        *PRESSED.lock().unwrap(),
        vec![vec!["Format".to_string(), "Font".into(), "Bold".into()]]
    );
    let missing = hands.ask(
        "menu",
        json!({"app": "Hands Fixture", "path": ["Format", "Font", "Italic"]}),
    );
    assert_eq!(code(&missing), "menu_not_found");
    assert!(missing["refused"]["message"]
        .as_str()
        .unwrap()
        .contains("Bold"));
    assert_eq!(
        code(&hands.ask(
            "menu",
            json!({"app": "Hands Fixture", "path": ["File", "Export"]})
        )),
        "menu_disabled"
    );
    assert_eq!(
        code(&hands.ask("menu", json!({"app": "Hands Fixture", "path": ["Bold"]}))),
        "bad_request"
    );
    assert_eq!(
        code(&hands.ask(
            "menu",
            json!({"app": "Safari", "path": ["File", "New Window"]})
        )),
        "app_look_only"
    );
    assert_eq!(
        code(&hands.ask(
            "menu",
            json!({"app": "Terminal", "path": ["Shell", "New Window"]})
        )),
        "app_click_only"
    );
    assert_eq!(
        code(&hands.ask(
            "menu",
            json!({"app": "Keychain Access", "path": ["File", "New"]})
        )),
        "app_denied"
    );
    assert_eq!(
        PRESSED.lock().unwrap().len(),
        1,
        "nothing refused was pressed"
    );
    assert!(
        hands.acted().is_empty(),
        "menus never go through agent-desktop"
    );
    arslan_hands::menus::set_stand_in_for_tests(None);
}

#[test]
fn a_key_combo_with_nothing_focused_presses_its_menu_item_instead() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    with_menus();
    let hands = start("nofocus");
    std::fs::write(hands.dir.join("bin/nofocus"), "").unwrap();
    let bold = hands.ask("press", json!({"app": "Hands Fixture", "keys": "cmd+b"}));
    assert_eq!(bold["ok"], true, "{bold}");
    assert_eq!(bold["route"], "menu_item");
    assert_eq!(bold["menu_item"], json!(["Format", "Font", "Bold"]));
    assert_eq!(bold["keys"], "cmd+b");
    // No item has this combo: the refusal stands as agent-desktop said it, nothing pressed.
    let other = hands.ask(
        "press",
        json!({"app": "Hands Fixture", "keys": "cmd+shift+z"}),
    );
    assert!(other.get("route").is_none(), "{other}");
    assert_eq!(other["envelope"]["error"]["code"], "ACTION_FAILED");
    assert_eq!(PRESSED.lock().unwrap().len(), 1);
    arslan_hands::menus::set_stand_in_for_tests(None);
}

#[test]
fn a_pop_up_and_front_true_borrow_the_front_only_with_the_users_switch() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    arslan_hands::borrow::stand_in_for_tests(true);
    let hands = start("borrow");
    // Color (@e5) is a pop-up: choosing in it opens its menu, which takes the key window.
    let pick = |borrow: Option<bool>| {
        let mut args = json!({"app": "Hands Fixture", "ref": "@sfixture0:e5", "value": "Blue"});
        if let Some(b) = borrow {
            args["borrow"] = json!(b);
        }
        hands.ask("select", args)
    };
    assert_eq!(code(&pick(None)), "borrow_off");
    assert_eq!(code(&pick(Some(false))), "borrow_off");
    assert!(hands.acted().is_empty(), "nothing ran without the switch");
    let picked = pick(Some(true));
    assert_eq!(picked["ok"], true, "{picked}");
    assert_eq!(picked["mode_used"], "borrow");
    assert_eq!(picked["borrow"]["front_restored"], true);
    assert_eq!(arslan_hands::borrow::borrows_for_tests(), 1);
    // A click stays in the background unless the model asks for the front.
    let click = hands.ask(
        "click",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e3"}),
    );
    assert_eq!(click["mode_used"], "background");
    assert_eq!(arslan_hands::borrow::borrows_for_tests(), 1);
    let front = hands.ask(
        "click",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e3", "front": true}),
    );
    assert_eq!(code(&front), "borrow_off");
    let front = hands.ask(
        "click",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e3", "front": true, "borrow": true}),
    );
    assert_eq!(front["mode_used"], "borrow", "{front}");
    assert_eq!(arslan_hands::borrow::borrows_for_tests(), 2);
    arslan_hands::borrow::stand_in_for_tests(false);
}

fn wait_until(what: impl Fn() -> bool) -> bool {
    let until = Instant::now() + Duration::from_secs(2);
    while Instant::now() < until {
        if what() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    false
}

#[test]
fn a_takeover_uses_the_front_pauses_when_the_user_touches_anything_and_ends() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    arslan_hands::takeover::stand_in_for_tests(true);
    arslan_hands::borrow::stand_in_for_tests(true);
    let hands = start("takeover");
    let click = || {
        hands.ask(
            "click",
            json!({"app": "Hands Fixture", "ref": "@sfixture0:e3"}),
        )
    };
    let status = || hands.ask("takeover_status", json!({}))["takeover"].clone();
    assert_eq!(
        code(&hands.ask("takeover_begin", json!({"minutes": 0}))),
        "bad_request"
    );
    assert_eq!(
        code(&hands.ask("takeover_begin", json!({"minutes": 31}))),
        "bad_request"
    );
    assert_eq!(
        hands.ask("takeover_begin", json!({"minutes": 5}))["takeover"]["active"],
        true
    );
    assert_eq!(click()["mode_used"], "takeover");
    // A pop-up needs no borrow (and no borrow switch) inside a takeover.
    let pick = hands.ask(
        "select",
        json!({"app": "Hands Fixture", "ref": "@sfixture0:e5", "value": "Blue"}),
    );
    assert_eq!(pick["mode_used"], "takeover", "{pick}");
    assert_eq!(arslan_hands::borrow::borrows_for_tests(), 0);
    // The user moves the mouse: paused at once, and nothing more is sent.
    arslan_hands::takeover::touch_for_tests();
    assert!(wait_until(|| status()["paused"] == true));
    let acted = hands.acted().len();
    assert_eq!(code(&click()), "takeover_paused");
    assert_eq!(
        code(&hands.ask(
            "menu",
            json!({"app": "Hands Fixture", "path": ["Format", "Bold"]})
        )),
        "takeover_paused"
    );
    assert_eq!(hands.acted().len(), acted, "nothing ran while paused");
    // Continue: actions run again.
    assert_eq!(
        hands.ask("takeover_resume", json!({}))["takeover"]["paused"],
        false
    );
    assert_eq!(click()["mode_used"], "takeover");
    assert_eq!(code(&hands.ask("takeover_resume", json!({}))), "not_paused");
    // Time up: it ends by itself, and actions are background again.
    arslan_hands::takeover::expire_for_tests();
    assert!(wait_until(|| status()["active"] == false));
    assert_eq!(click()["mode_used"], "background");
    // Stop ends a takeover too.
    hands.ask("takeover_begin", json!({"minutes": 1}));
    hands.ask("stop", json!({}));
    assert_eq!(status()["active"], false);
    arslan_hands::takeover::stand_in_for_tests(false);
    arslan_hands::borrow::stand_in_for_tests(false);
}

#[test]
fn what_runs_when_the_user_touches_is_ended_and_said_paused_not_stopped() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    arslan_hands::takeover::stand_in_for_tests(true);
    let hands = start("touched");
    hands.ask("takeover_begin", json!({"minutes": 5}));
    let socket = hands.folder().join("s.sock");
    let token = hands.token.clone();
    let slow = std::thread::spawn(move || {
        let mut stream = UnixStream::connect(socket).unwrap();
        let req = json!({"token": token, "op": "wait", "args": {"app": "Hands Fixture", "text": "slow", "timeout_ms": 20000}});
        writeln!(stream, "{req}").unwrap();
        let mut reply = String::new();
        BufReader::new(stream).read_line(&mut reply).unwrap();
        serde_json::from_str::<Value>(&reply).unwrap()
    });
    assert!(wait_until(|| hands.calls().iter().any(|c| c[0] == "wait")));
    let touched = Instant::now();
    arslan_hands::takeover::touch_for_tests();
    let reply = slow.join().unwrap();
    assert!(
        touched.elapsed() < Duration::from_secs(1),
        "{:?}",
        touched.elapsed()
    );
    assert_eq!(code(&reply), "takeover_paused", "{reply}");
    hands.ask("takeover_end", json!({}));
    arslan_hands::takeover::stand_in_for_tests(false);
}

#[test]
fn a_waiting_borrow_shows_on_the_island_and_takes_its_answer() {
    let _turn = SERIAL.lock().unwrap_or_else(|p| p.into_inner());
    arslan_hands::borrow::stand_in_for_tests(true);
    let hands = start("waiting");
    let pick = || {
        hands.ask(
            "select",
            json!({"app": "Hands Fixture", "ref": "@sfixture0:e5", "value": "Blue", "borrow": true}),
        )
    };
    let phase = || hands.ask("activity_status", json!({}))["borrow"].clone();
    assert_eq!(phase(), Value::Null);
    assert_eq!(
        hands.ask("borrow_now", json!({}))["ok"],
        false,
        "nothing is waiting"
    );
    // The user is typing: the borrow waits, and the island says so; "now" starts it.
    arslan_hands::borrow::typing_for_tests(true);
    std::thread::scope(|scope| {
        let waiting = scope.spawn(pick);
        assert!(wait_until(|| phase() == "waiting"));
        assert_eq!(hands.ask("borrow_now", json!({}))["ok"], true);
        let picked = waiting.join().unwrap();
        assert_eq!(picked["mode_used"], "borrow", "{picked}");
        assert!(picked["borrow"]["waited_ms"].as_u64().unwrap() > 0);
    });
    assert_eq!(phase(), Value::Null);
    // "Not this time": nothing is done.
    std::thread::scope(|scope| {
        let waiting = scope.spawn(pick);
        assert!(wait_until(|| phase() == "waiting"));
        assert_eq!(hands.ask("borrow_skip", json!({}))["ok"], true);
        assert_eq!(code(&waiting.join().unwrap()), "borrow_declined");
    });
    arslan_hands::borrow::typing_for_tests(false);
    arslan_hands::borrow::stand_in_for_tests(false);
}
