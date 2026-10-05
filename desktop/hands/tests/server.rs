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
        {"name": "Terminal", "bundle_id": "com.apple.Terminal", "pid": 500}]}})
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
