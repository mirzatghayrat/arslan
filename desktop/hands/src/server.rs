//! The socket Arslan's backend talks to (spec §2.2) and what each request does.
//!
//! One JSON line in, one JSON line out, per connection. Every request carries the
//! per-launch token; in a signed build the peer must be Arslan's backend.
//! agent-desktop runs one command at a time; Stop does not wait for that and
//! kills the command in flight.

use crate::argv::{self, refuse, Refusal};
use crate::cua::{self, Completion, Cua};
use crate::cua_policy::{self, Kind};
use crate::paths;
use crate::policy::{self, Tier, PASSWORD_WORDS};
use crate::refmap;
use crate::runner::{self, Runner};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
const MAX_REQUEST: u64 = 256 * 1024;
/// Answers kept for `answer_of` and repeated ids (spec 2026-10-08-0157 §1, D1).
const ANSWERS_KEPT: usize = 256;
const ANSWER_TTL: Duration = Duration::from_secs(600);

pub struct Config {
    /// Hands' folder (0700): socket, token, lock, agent-desktop state.
    pub folder: PathBuf,
    pub agent_desktop: PathBuf,
    /// Its recorded sha256 (Resources/agent-desktop.sha256); checked before every run.
    pub agent_desktop_sha256: Option<String>,
    pub home: PathBuf,
    pub idle: Duration,
    /// Hands' own Team ID; Some = only `arslan-server` signed by it may connect.
    pub team: Option<String>,
    /// Cua Driver beside the bundle (Hands v2), with its recorded sha256 and Hands'
    /// bundle id. None: this Hands has no Cua Driver.
    pub cua_driver: Option<PathBuf>,
    pub cua_driver_sha256: Option<String>,
    pub host_bundle_id: String,
}

/// One request: the state, and the Stop generation it started in.
struct Ctx<'a> {
    state: &'a State,
    generation: u64,
}

struct State {
    runner: Runner,
    folder: PathBuf,
    token: String,
    team: Option<String>,
    one_at_a_time: Mutex<()>,
    last_seen: AtomicU64,
    busy: AtomicU64,
    sessions: Mutex<HashSet<String>>,
    answers: Answers,
    cua: Option<Cua>,
    /// Element tokens of the window states relayed from Cua Driver (cua_policy.rs).
    tokens: Mutex<cua_policy::Tokens>,
    /// Cua sessions end (1 h at most, set at initialize): a label whose session ended is
    /// replaced by `label-N`, counted here.
    cua_sessions: Mutex<HashMap<String, u32>>,
    /// Cua Driver's running apps, briefly, to resolve a pid to an app.
    cua_apps: Mutex<Option<(Instant, Vec<App>)>>,
    /// Each app's structure at its latest look, per (session, pid): the structural-change
    /// check (structure.rs) compares it before every action.
    structures: Mutex<HashMap<(String, i64), crate::structure::Structure>>,
}

/// At most once (P0 D1): every answer to a request with a string id is kept for ten
/// minutes. The same id again is answered from here without running anything, and
/// `answer_of` lets the backend fetch an answer whose reply it lost (a timeout, a
/// dropped connection) instead of sending the action a second time.
#[derive(Default)]
struct Answers {
    slots: Mutex<HashMap<String, Slot>>,
    changed: Condvar,
}

enum Slot {
    Running,
    Done(Value, Instant),
}

enum Claim {
    Mine,
    Answered(Value),
    StillRunning,
}

impl Answers {
    /// Claim `id` to run it, or wait (up to `wait`) for the answer of the request that has it.
    fn claim(&self, id: &str, wait: Duration) -> Claim {
        let mut slots = self.slots.lock().unwrap_or_else(|p| p.into_inner());
        let until = Instant::now() + wait;
        loop {
            match slots.get(id) {
                None => {
                    slots.insert(id.to_string(), Slot::Running);
                    return Claim::Mine;
                }
                Some(Slot::Done(answer, _)) => return Claim::Answered(answer.clone()),
                Some(Slot::Running) => {
                    let now = Instant::now();
                    if now >= until {
                        return Claim::StillRunning;
                    }
                    slots = self
                        .changed
                        .wait_timeout(slots, until - now)
                        .unwrap_or_else(|p| p.into_inner())
                        .0;
                }
            }
        }
    }

    fn finish(&self, id: &str, answer: &Value) {
        let mut slots = self.slots.lock().unwrap_or_else(|p| p.into_inner());
        slots.insert(id.to_string(), Slot::Done(answer.clone(), Instant::now()));
        slots.retain(|_, slot| match slot {
            Slot::Done(_, at) => at.elapsed() < ANSWER_TTL,
            Slot::Running => true,
        });
        while slots.len() > ANSWERS_KEPT {
            let oldest = slots
                .iter()
                .filter_map(|(k, slot)| match slot {
                    Slot::Done(_, at) => Some((k.clone(), *at)),
                    Slot::Running => None,
                })
                .min_by_key(|(_, at)| *at)
                .map(|(k, _)| k);
            match oldest {
                Some(k) => {
                    slots.remove(&k);
                }
                None => break,
            }
        }
        self.changed.notify_all();
    }

    /// The answer to `id`: done, still running after `wait`, or never received here.
    fn lookup(&self, id: &str, wait: Duration) -> Value {
        let mut slots = self.slots.lock().unwrap_or_else(|p| p.into_inner());
        let until = Instant::now() + wait;
        loop {
            match slots.get(id) {
                None => return json!({"ok": true, "state": "unknown_id"}),
                Some(Slot::Done(answer, _)) => {
                    return json!({"ok": true, "state": "done", "answer": answer})
                }
                Some(Slot::Running) => {
                    let now = Instant::now();
                    if now >= until {
                        return json!({"ok": true, "state": "running"});
                    }
                    slots = self
                        .changed
                        .wait_timeout(slots, until - now)
                        .unwrap_or_else(|p| p.into_inner())
                        .0;
                }
            }
        }
    }
}

#[derive(Deserialize)]
struct Request {
    token: String,
    #[serde(default)]
    id: Value,
    op: String,
    #[serde(default)]
    args: Value,
}

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn same(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

fn new_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    if unsafe { libc::getentropy(bytes.as_mut_ptr().cast(), bytes.len()) } != 0 {
        return Err("no entropy".into());
    }
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn refused(r: Refusal) -> Value {
    json!({"ok": false, "refused": {"code": r.code, "message": r.message}})
}

/// Write `contents` to `path` with mode 0600, atomically (temp file + rename).
fn write_private(path: &PathBuf, contents: &str) -> Result<(), String> {
    let tmp = path.with_extension("tmp");
    let _ = fs::remove_file(&tmp);
    {
        let mut f = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&tmp)
            .map_err(|e| format!("cannot write {}: {e}", tmp.display()))?;
        f.write_all(contents.as_bytes())
            .map_err(|e| e.to_string())?;
    }
    fs::rename(&tmp, path).map_err(|e| e.to_string())
}

/// Start serving. Returns only on a startup error (or never, for the real app:
/// Quit and the idle timer exit the process).
pub fn run(config: Config) -> Result<(), String> {
    let listener = bind(&config)?;
    serve(config, listener)
}

/// Folder, single-instance lock, socket — everything before the token exists.
pub fn bind(config: &Config) -> Result<(UnixListener, fs::File, String), String> {
    paths::ensure_private_dir(&config.folder)?;
    paths::ensure_private_dir(&config.folder.join(paths::AGENT_DESKTOP_HOME))?;
    let lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .mode(0o600)
        .open(config.folder.join(paths::LOCK))
        .map_err(|e| format!("cannot open the lock: {e}"))?;
    if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        return Err("another Arslan Hands is already running".into());
    }
    let socket = config.folder.join(paths::SOCKET);
    if !paths::socket_path_fits(&socket) {
        return Err(format!(
            "socket path too long for macOS: {}",
            socket.display()
        ));
    }
    let _ = fs::remove_file(&socket);
    let old = unsafe { libc::umask(0o077) };
    let listener = UnixListener::bind(&socket);
    unsafe { libc::umask(old) };
    let listener = listener.map_err(|e| format!("cannot listen on {}: {e}", socket.display()))?;
    fs::set_permissions(&socket, fs::Permissions::from_mode(0o600)).map_err(|e| e.to_string())?;
    let token = new_token()?;
    Ok((listener, lock, token))
}

/// Serve on what `bind` prepared (the macOS app runs this off the main thread).
pub fn serve(
    config: Config,
    (listener, lock, token): (UnixListener, fs::File, String),
) -> Result<(), String> {
    let state = Arc::new(State {
        runner: Runner {
            pinned: config.agent_desktop_sha256.as_deref().map(|sha| {
                Arc::new(crate::integrity::Pinned::new(
                    config.agent_desktop.clone(),
                    sha,
                ))
            }),
            binary: config.agent_desktop.clone(),
            state_root: config.folder.join(paths::AGENT_DESKTOP_HOME),
            home: config.home.clone(),
        },
        folder: config.folder.clone(),
        token,
        team: config.team.clone(),
        one_at_a_time: Mutex::new(()),
        last_seen: AtomicU64::new(now()),
        busy: AtomicU64::new(0),
        sessions: Mutex::new(HashSet::new()),
        answers: Answers::default(),
        cua: config.cua_driver.as_ref().map(|binary| {
            Cua::new(cua::Config {
                binary: binary.clone(),
                pinned: config
                    .cua_driver_sha256
                    .as_deref()
                    .map(|sha| Arc::new(crate::integrity::Pinned::new(binary.clone(), sha))),
                home: config.folder.join(paths::CUA_HOME),
                log: config.folder.join(paths::CUA_LOG),
                host_bundle_id: config.host_bundle_id.clone(),
            })
        }),
        tokens: Mutex::new(cua_policy::Tokens::default()),
        cua_sessions: Mutex::new(HashMap::new()),
        cua_apps: Mutex::new(None),
        structures: Mutex::new(HashMap::new()),
    });
    // The token is published only now that the socket listens, mode 0600.
    let ready = json!({
        "pid": std::process::id(),
        "version": VERSION,
        "token": state.token,
        "socket": config.folder.join(paths::SOCKET),
        "peer_check": if state.team.is_some() { "signed" } else { "off" },
    });
    write_private(&config.folder.join(paths::READY), &ready.to_string())?;
    let _lock = lock; // held for the life of the process

    let idle_state = Arc::clone(&state);
    let idle = config.idle;
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(5).min(idle));
        let quiet = now().saturating_sub(idle_state.last_seen.load(Ordering::SeqCst));
        if idle_state.busy.load(Ordering::SeqCst) == 0 && quiet >= idle.as_secs() {
            shutdown(&idle_state);
        }
    });

    for stream in listener.incoming() {
        let Ok(stream) = stream else { continue };
        let state = Arc::clone(&state);
        thread::spawn(move || handle(&state, stream));
    }
    Ok(())
}

fn shutdown(state: &State) -> ! {
    end_sessions(state);
    if let Some(cua) = &state.cua {
        cua.shutdown();
    }
    let _ = fs::remove_file(state.folder.join(paths::READY));
    let _ = fs::remove_file(state.folder.join(paths::SOCKET));
    std::process::exit(0)
}

fn peer_ok(state: &State, stream: &UnixStream) -> bool {
    match &state.team {
        None => true,
        #[cfg(target_os = "macos")]
        Some(team) => crate::macos::peer_allowed(stream.as_raw_fd(), team),
        #[cfg(not(target_os = "macos"))]
        Some(_) => {
            let _ = stream;
            false
        }
    }
}

fn handle(state: &State, mut stream: UnixStream) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(10)));
    let reply = if !peer_ok(state, &stream) {
        refused(refuse(
            "peer_not_allowed",
            "only Arslan may use Arslan Hands",
        ))
    } else {
        let mut line = String::new();
        let mut reader = BufReader::new((&stream).take(MAX_REQUEST));
        match reader.read_line(&mut line) {
            Err(_) | Ok(0) => return,
            Ok(_) => match serde_json::from_str::<Request>(&line) {
                Err(_) => refused(refuse("bad_request", "one JSON object per line")),
                Ok(req) if !same(req.token.as_bytes(), state.token.as_bytes()) => {
                    refused(refuse("bad_token", "wrong token"))
                }
                Ok(req) => {
                    state.last_seen.store(now(), Ordering::SeqCst);
                    let mut out = answered(state, &req);
                    if let Some(map) = out.as_object_mut() {
                        map.insert("id".into(), req.id.clone());
                        map.insert("op".into(), Value::String(req.op.clone()));
                        map.insert("pid".into(), json!(std::process::id()));
                    }
                    if req.op == "quit" {
                        let _ = stream.write_all(format!("{out}\n").as_bytes()); // one write: one line
                        shutdown(state);
                    }
                    out
                }
            },
        }
    };
    let _ = stream.write_all(format!("{reply}\n").as_bytes());
}

fn deadline(op: &str, args: &Value) -> Duration {
    match op {
        "wait" => Duration::from_millis(
            args.get("timeout_ms")
                .and_then(Value::as_u64)
                .unwrap_or(5_000)
                + 5_000,
        ),
        "list_apps" | "list_windows" => Duration::from_secs(15),
        _ => Duration::from_secs(30),
    }
}

/// Run agent-desktop and parse its envelope. Stop and deadlines become refusals.
fn run_envelope(
    ctx: &Ctx,
    argv: &[String],
    limit: Duration,
) -> Result<(Option<i32>, Value), Refusal> {
    let out = ctx
        .state
        .runner
        .run(argv, limit, ctx.generation)
        .map_err(|e| refuse("helper_failed", e))?;
    if out.timed_out {
        return Err(refuse("TIMEOUT", "agent-desktop did not finish in time"));
    }
    if out.killed {
        return Err(refuse("stopped_by_user", "stopped"));
    }
    let envelope: Value = serde_json::from_str(out.stdout.trim()).map_err(|_| {
        refuse(
            "bad_output",
            "agent-desktop printed something that is not its JSON envelope",
        )
    })?;
    if envelope.get("ok").and_then(Value::as_bool).is_none() {
        return Err(refuse("bad_output", "agent-desktop's envelope has no `ok`"));
    }
    Ok((out.exit, envelope))
}

#[derive(Debug, Clone)]
struct App {
    name: String,
    bundle_id: String,
    pid: i64,
}

fn never_list(args: &Value) -> Vec<String> {
    args.get("never")
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .filter_map(Value::as_str)
                .take(500)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

fn running_apps(ctx: &Ctx) -> Result<Vec<App>, Refusal> {
    let (_, envelope) = run_envelope(
        ctx,
        &["list-apps".to_string()],
        deadline("list_apps", &Value::Null),
    )?;
    let apps = envelope
        .pointer("/data/apps")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    Ok(apps
        .iter()
        .filter_map(|a| {
            Some(App {
                name: a.get("name")?.as_str()?.to_string(),
                bundle_id: a
                    .get("bundle_id")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string(),
                pid: a.get("pid")?.as_i64()?,
            })
        })
        .collect())
}

/// The one running app a request means: exact name or bundle id, any case.
fn resolve_app(ctx: &Ctx, wanted: &str) -> Result<App, Refusal> {
    let mut found: Vec<App> = running_apps(ctx)?
        .into_iter()
        .filter(|a| a.name.eq_ignore_ascii_case(wanted) || a.bundle_id.eq_ignore_ascii_case(wanted))
        .collect();
    match found.len() {
        0 => Err(refuse(
            "app_not_running",
            format!("no running app is called “{wanted}”"),
        )),
        1 => Ok(found.remove(0)),
        _ => Err(refuse(
            "app_ambiguous",
            format!("more than one running app is called “{wanted}”"),
        )),
    }
}

fn tier_refusal(tier: Tier, op: &str, app: &App) -> Refusal {
    match tier {
        Tier::Denied => refuse("app_denied", format!("Arslan never touches {}", app.name)),
        Tier::LookOnly => refuse(
            "app_look_only",
            format!("{} is a web browser: Hands only reads it; act on web pages with Arslan's own browser", app.name),
        ),
        _ => refuse(
            "app_click_only",
            format!("{} runs commands: Hands may click and scroll there but not `{op}`", app.name),
        ),
    }
}

fn session_of(args: &Value) -> Result<Option<String>, Refusal> {
    match args.get("session").and_then(Value::as_str) {
        None => Ok(None),
        Some(s) if argv::session_ok(s) => Ok(Some(s.to_string())),
        Some(_) => Err(refuse("bad_request", "bad session id")),
    }
}

fn looks_like_password(target: &refmap::Target, states: &[String]) -> bool {
    if states.iter().any(|s| s == "secure") {
        return true;
    }
    let name = target.name.as_deref().unwrap_or("").to_lowercase();
    PASSWORD_WORDS.iter().any(|w| name.contains(w))
}

fn live_states(ctx: &Ctx, reference: &str, session: Option<&str>) -> Result<Vec<String>, Refusal> {
    let argv = argv::build(
        "get",
        &json!({"ref": reference, "property": "states"}),
        session,
    )?;
    let (_, envelope) = run_envelope(ctx, &argv, deadline("get", &Value::Null))?;
    if envelope.get("ok").and_then(Value::as_bool) != Some(true) {
        // Cannot see the field's states: do not type into it blind.
        return Err(refuse(
            "target_unreadable",
            "could not read the field before typing; look again",
        ));
    }
    Ok(envelope
        .pointer("/data/value")
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default())
}

/// `dispatch`, at most once per string id (P0 D1).
fn answered(state: &State, req: &Request) -> Value {
    if req.op == "answer_of" {
        let id = req.args.get("id").and_then(Value::as_str).unwrap_or("");
        let wait = req
            .args
            .get("wait_ms")
            .and_then(Value::as_u64)
            .unwrap_or(0)
            .min(120_000);
        return state.answers.lookup(id, Duration::from_millis(wait));
    }
    let id = match req.id.as_str() {
        Some(id) if !id.is_empty() && !matches!(req.op.as_str(), "status" | "stop" | "quit") => id,
        _ => return dispatch(state, req),
    };
    match state.answers.claim(id, Duration::from_secs(120)) {
        Claim::Answered(answer) => answer,
        Claim::StillRunning => refused(refuse("busy", "the same request is still running")),
        Claim::Mine => {
            let mut out = dispatch(state, req);
            if let Some(map) = out.as_object_mut() {
                map.insert("id".into(), req.id.clone());
                map.insert("op".into(), Value::String(req.op.clone()));
                map.insert("pid".into(), json!(std::process::id()));
            }
            state.answers.finish(id, &out);
            out
        }
    }
}

fn dispatch(state: &State, req: &Request) -> Value {
    match req.op.as_str() {
        "status" => status(state),
        "request_permission" => {
            // Hands v2: `{kind: "screen"}` asks for Screen Recording (window screenshots);
            // anything else, as before, for Accessibility.
            if req.args.get("kind").and_then(Value::as_str) == Some("screen") {
                json!({"ok": true, "screen_recording": request_screen()})
            } else {
                json!({"ok": true, "accessibility": request_permission()})
            }
        }
        "stop" => stop(state),
        "quit" => json!({"ok": true}),
        // A screenshot runs beside an agent-desktop command, not after it (spec §15 A8: a look's
        // tree and its screenshot are asked for together). Stop still applies.
        "capture_window" => {
            let generation = runner::generation();
            let ctx = Ctx { state, generation };
            let out = capture_window(&ctx, &req.args).unwrap_or_else(refused);
            if runner::generation() != generation {
                return refused(refuse("stopped_by_user", "stopped"));
            }
            out
        }
        _ => {
            let generation = runner::generation();
            let _one = state
                .one_at_a_time
                .lock()
                .unwrap_or_else(|p| p.into_inner());
            if runner::generation() != generation {
                return refused(refuse("stopped_by_user", "stopped before it started"));
            }
            state.busy.fetch_add(1, Ordering::SeqCst);
            let ctx = Ctx { state, generation };
            let out = guarded(&ctx, req).unwrap_or_else(refused);
            state.busy.fetch_sub(1, Ordering::SeqCst);
            state.last_seen.store(now(), Ordering::SeqCst);
            out
        }
    }
}

fn guarded(ctx: &Ctx, req: &Request) -> Result<Value, Refusal> {
    let op = req.op.as_str();
    let args = &req.args;
    match op {
        "session_start" => return session_start(ctx, args),
        "session_label" => return session_label(ctx, args),
        "session_end" => return session_end(ctx, args),
        "list_apps" => return list_apps(ctx, args),
        "cua" => return cua_op(ctx, args),
        _ => {}
    }
    if op != "describe" && !argv::OPS.contains(&op) {
        return Err(refuse(
            "op_not_allowed",
            format!("`{op}` is not something Hands does"),
        ));
    }
    let session = session_of(args)?;
    let app = resolve_app(ctx, argv::app_name(args)?)?;
    let tier = policy::tier(&app.bundle_id, &app.name, &never_list(args));
    if !policy::allows(tier, op) {
        return Err(tier_refusal(tier, op, &app));
    }
    let mut target = None;
    if op == "describe" || argv::targets_ref(op) {
        let reference = args.get("ref").and_then(Value::as_str).unwrap_or("");
        if argv::parse_ref(reference).is_none() {
            return Err(refuse(
                "bad_ref",
                "`ref` must be a ref from a look, like @s1a2b3c4:e7",
            ));
        }
        let found = refmap::lookup(&ctx.state.runner.state_root, session.as_deref(), reference)
            .ok_or_else(|| {
                refuse(
                    "ref_unknown",
                    "this ref is not from a look in this piece of work; look again",
                )
            })?;
        if found.pid != app.pid {
            return Err(refuse(
                "ref_wrong_app",
                format!("this ref is not from {}", app.name),
            ));
        }
        if matches!(op, "type" | "set_value" | "describe") {
            let states = live_states(ctx, reference, session.as_deref())?;
            let password = looks_like_password(&found, &states);
            if password && op != "describe" {
                return Err(refuse(
                    "password_field",
                    "Arslan never types into password fields",
                ));
            }
            if op == "describe" {
                return Ok(json!({
                    "ok": true,
                    "app": app_json(&app),
                    "tier": policy::tier_name(tier),
                    "sends_on_return": policy::sends_on_return(&app.bundle_id, &app.name),
                    "target": {"role": found.role, "name": found.name, "actions": found.actions,
                               "states": states, "password": password},
                }));
            }
        }
        target = Some(found);
    }
    let mut call = args.clone();
    if let Some(map) = call.as_object_mut() {
        map.insert("app".into(), Value::String(app.name.clone()));
    }
    let argv = argv::build(op, &call, session.as_deref())?;
    let key = (session.clone().unwrap_or_default(), app.pid);
    if matches!(op, "snapshot" | "find") {
        // Read BEFORE the tree: a sheet that opens while the tree is read then counts as a
        // change, so an action on that tree is refused rather than allowed.
        if let Some(now) = crate::structure::read(app.pid) {
            let mut kept = ctx
                .state
                .structures
                .lock()
                .unwrap_or_else(|p| p.into_inner());
            if kept.len() > 256 {
                kept.clear();
            }
            kept.insert(key.clone(), now);
        }
    } else if acts(op) {
        let before = ctx
            .state
            .structures
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .get(&key)
            .cloned();
        if let (Some(before), Some(now)) = (before, crate::structure::read(app.pid)) {
            let changed = crate::structure::changes(&before, &now);
            if !changed.is_empty() {
                return Err(refuse(
                    "changed",
                    format!(
                        "{} changed since your look: {}. Nothing was done; look again",
                        app.name,
                        changed.join("; ")
                    ),
                ));
            }
        }
    }
    let front_before = if acts(op) { frontmost_pid() } else { None };
    let (exit, envelope) = run_envelope(ctx, &argv, deadline(op, args))?;
    let focus_restored = front_back(front_before, app.pid);
    let front_after = if acts(op) { frontmost_pid() } else { None };
    Ok(json!({
        "ok": true,
        "app": app_json(&app),
        "tier": policy::tier_name(tier),
        "sends_on_return": policy::sends_on_return(&app.bundle_id, &app.name),
        "target": target.map(|t| json!({"role": t.role, "name": t.name, "actions": t.actions})),
        "exit": exit,
        "envelope": envelope,
        "focus_restored": focus_restored,
        // One vocabulary for both engines (outcome.rs); only actions have one.
        "outcome": (acts(op) && envelope.get("ok") == Some(&Value::Bool(true)))
            .then(|| crate::outcome::from_agent_desktop(&envelope)),
        "mode_used": acts(op).then_some("background"),
        // What was in front just before and just after this action (pids), so a
        // check can tell an app Hands acted on taking the focus from the user
        // switching apps between actions.
        "front": {"before": front_before, "after": front_after},
    }))
}

/// Hands v2's own window screenshot (spec §4.2, §15 A8): agent-desktop's `screenshot` writes a
/// file, so Hands captures in memory itself. Same app rules as a look: the never-list refuses,
/// browsers and terminals may be seen. The window must be one of that app's (capture.m checks
/// the window server's list, not the caller's word).
fn capture_window(ctx: &Ctx, args: &Value) -> Result<Value, Refusal> {
    let app = resolve_app(ctx, argv::app_name(args)?)?;
    let tier = policy::tier(&app.bundle_id, &app.name, &never_list(args));
    if !policy::allows(tier, "capture_window") {
        return Err(tier_refusal(tier, "capture_window", &app));
    }
    let window = crate::capture::window_id(args.get("window").unwrap_or(&Value::Null))
        .ok_or_else(|| refuse("bad_request", "`window` is a window id like w-26104"))?;
    let pid = i32::try_from(app.pid).map_err(|_| refuse("app_not_running", "bad pid"))?;
    let shot = crate::capture::window(pid, window);
    if shot.get("ok").and_then(Value::as_bool) != Some(true) {
        let code = shot
            .get("code")
            .and_then(Value::as_str)
            .unwrap_or("capture_failed");
        let message = shot.get("message").and_then(Value::as_str).unwrap_or("");
        return Err(refuse(capture_code(code), message.to_string()));
    }
    Ok(json!({
        "ok": true,
        "app": app_json(&app),
        "tier": policy::tier_name(tier),
        "capture": shot,
    }))
}

/// capture.m's codes, as the fixed strings a Refusal carries.
fn capture_code(code: &str) -> &'static str {
    match code {
        "screen_recording_off" => "screen_recording_off",
        "window_not_found" => "window_not_found",
        "window_not_capturable" => "window_not_capturable",
        "needs_macos_14" => "needs_macos_14",
        "not_supported" => "not_supported",
        _ => "capture_failed",
    }
}

fn acts(op: &str) -> bool {
    matches!(
        op,
        "click" | "type" | "set_value" | "select" | "press" | "scroll"
    )
}

/// Some apps bring themselves forward when acted on (Notes on New Note, seen on
/// a real Mac). Hands never takes the focus: if the app in front changed TO the
/// app acted on, give the front back to the app that had it.
fn front_back(before: Option<i32>, acted_on: i64) -> bool {
    match (before, frontmost_pid()) {
        (Some(before), Some(now)) if now != before && i64::from(now) == acted_on => {
            restore_front(before)
        }
        _ => false,
    }
}

#[cfg(target_os = "macos")]
fn frontmost_pid() -> Option<i32> {
    crate::macos::frontmost_pid()
}

#[cfg(not(target_os = "macos"))]
fn frontmost_pid() -> Option<i32> {
    None
}

#[cfg(target_os = "macos")]
fn restore_front(pid: i32) -> bool {
    crate::macos::give_front_back(pid)
}

#[cfg(not(target_os = "macos"))]
fn restore_front(_pid: i32) -> bool {
    false
}

fn app_json(app: &App) -> Value {
    json!({"name": app.name, "bundle_id": app.bundle_id, "pid": app.pid})
}

fn list_apps(ctx: &Ctx, args: &Value) -> Result<Value, Refusal> {
    let never = never_list(args);
    let apps: Vec<Value> = running_apps(ctx)?
        .iter()
        .filter_map(|a| {
            let tier = policy::tier(&a.bundle_id, &a.name, &never);
            (tier != Tier::Denied)
                .then(|| json!({"name": a.name, "bundle_id": a.bundle_id, "tier": policy::tier_name(tier)}))
        })
        .collect();
    Ok(json!({"ok": true, "apps": apps}))
}

fn session_start(ctx: &Ctx, args: &Value) -> Result<Value, Refusal> {
    let argv = vec![
        "session".into(),
        "start".into(),
        "--cursor".into(),
        "--no-trace".into(),
        "--name=Arslan".into(),
    ];
    let (_, envelope) = run_envelope(ctx, &argv, Duration::from_secs(15))?;
    let session = envelope
        .pointer("/data/session_id")
        .and_then(Value::as_str)
        .filter(|s| argv::session_ok(s))
        .ok_or_else(|| refuse("bad_output", "agent-desktop started no session"))?
        .to_string();
    ctx.state
        .sessions
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .insert(session.clone());
    if args.get("label").and_then(Value::as_str).is_some() {
        let mut labelled = args.clone();
        labelled["session"] = Value::String(session.clone());
        session_label(ctx, &labelled)?;
    }
    Ok(json!({"ok": true, "session": session}))
}

fn session_label(ctx: &Ctx, args: &Value) -> Result<Value, Refusal> {
    let session =
        session_of(args)?.ok_or_else(|| refuse("bad_request", "`session` is required"))?;
    let label: String = args
        .get("label")
        .and_then(Value::as_str)
        .unwrap_or("Arslan")
        .chars()
        .filter(|c| !c.is_control())
        .take(80)
        .collect();
    let argv = vec![
        "cursor-overlay".into(),
        "enable".into(),
        format!("--session={session}"),
        format!("--label={label}"),
        "--max-words=8".into(),
    ];
    let (_, envelope) = run_envelope(ctx, &argv, Duration::from_secs(10))?;
    Ok(json!({"ok": true, "envelope": envelope}))
}

fn session_end(ctx: &Ctx, args: &Value) -> Result<Value, Refusal> {
    let session =
        session_of(args)?.ok_or_else(|| refuse("bad_request", "`session` is required"))?;
    ctx.state
        .sessions
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .remove(&session);
    let argv = vec!["session".into(), "end".into(), "--".into(), session];
    let (_, envelope) = run_envelope(ctx, &argv, Duration::from_secs(10))?;
    Ok(json!({"ok": true, "envelope": envelope}))
}

/// Hide every cursor Hands showed (Stop and exit). Best effort.
fn end_sessions(state: &State) {
    let sessions: Vec<String> = state
        .sessions
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .drain()
        .collect();
    for session in sessions {
        let _ = state.runner.run(
            &["session".into(), "end".into(), "--".into(), session],
            Duration::from_secs(5),
            runner::generation(),
        );
    }
}

fn stop(state: &State) -> Value {
    // kill_all moves the Stop generation even when no agent-desktop runs, so a Cua
    // request in flight learns it was stopped.
    let killed = runner::kill_all();
    let cua_killed = state.cua.as_ref().is_some_and(Cua::stop);
    end_sessions(state);
    json!({"ok": true, "killed": killed || cua_killed})
}

fn status(state: &State) -> Value {
    json!({
        "ok": true,
        "version": VERSION,
        "pid": std::process::id(),
        "accessibility": accessibility(),
        "screen_recording": screen_recording(),
        "peer_check": if state.team.is_some() { "verified" } else { "off" },
        "team": state.team,
        "agent_desktop": state.runner.binary.exists(),
        "agent_desktop_pinned": state.runner.pinned.as_ref().map(|p| p.check().is_ok()),
        "cua_driver": state.cua.as_ref().map(Cua::present),
        "cua_driver_pinned": state.cua.as_ref().and_then(Cua::pinned),
    })
}

#[cfg(target_os = "macos")]
fn accessibility() -> bool {
    crate::macos::accessibility_trusted()
}

#[cfg(not(target_os = "macos"))]
fn accessibility() -> bool {
    false
}

#[cfg(target_os = "macos")]
fn screen_recording() -> bool {
    crate::macos::screen_recording()
}

#[cfg(not(target_os = "macos"))]
fn screen_recording() -> bool {
    false
}

#[cfg(target_os = "macos")]
fn request_screen() -> bool {
    crate::macos::request_screen_recording()
}

#[cfg(not(target_os = "macos"))]
fn request_screen() -> bool {
    false
}

#[cfg(target_os = "macos")]
fn request_permission() -> bool {
    crate::macos::request_accessibility()
}

#[cfg(not(target_os = "macos"))]
fn request_permission() -> bool {
    false
}

// ── Cua Driver (Hands v2, spec docs/specs/2026-10-08-0157-hands-v2.md §3) ────

/// The label Hands gives Cua's session (its cursor, its snapshots): the backend's
/// choice when it is a plain label, else "arslan".
fn cua_session(args: &Value) -> String {
    args.get("session")
        .and_then(Value::as_str)
        .filter(|s| {
            !s.is_empty()
                && s.len() <= 64
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        })
        .unwrap_or("arslan")
        .to_string()
}

fn cua_deadline(kind: Kind) -> Duration {
    match kind {
        Kind::Act => Duration::from_secs(30),
        Kind::Global | Kind::Read => Duration::from_secs(20),
    }
}

/// The code of a refusal Cua put in a result (`structuredContent.refusal.code` or `error.code`).
fn cua_refusal_code(result: &Value) -> Option<String> {
    result
        .pointer("/structuredContent/refusal/code")
        .or_else(|| result.pointer("/structuredContent/error/code"))
        .and_then(Value::as_str)
        .map(str::to_string)
}

/// A refusal that also says whether what was asked may have happened.
fn refused_after(r: Refusal, completion: Completion) -> Value {
    json!({"ok": false, "refused": {"code": r.code, "message": r.message},
           "completion": completion.name()})
}

/// Running apps as Cua Driver lists them (`structuredContent.apps`).
fn cua_running_apps(result: &Value) -> Vec<App> {
    result
        .pointer("/structuredContent/apps")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|a| a.get("running").and_then(Value::as_bool) != Some(false))
        .filter_map(|a| {
            Some(App {
                name: a.get("name")?.as_str()?.to_string(),
                bundle_id: a
                    .get("bundle_id")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string(),
                pid: a.get("pid")?.as_i64()?,
            })
        })
        .collect()
}

#[cfg(target_os = "macos")]
fn app_of_pid(pid: i64) -> Option<App> {
    i32::try_from(pid)
        .ok()
        .and_then(crate::macos::app_of_pid)
        .map(|(name, bundle_id)| App {
            name,
            bundle_id,
            pid,
        })
}

#[cfg(not(target_os = "macos"))]
fn app_of_pid(_pid: i64) -> Option<App> {
    None
}

/// The app `pid` belongs to: asked of macOS directly (NSRunningApplication, fast); only when
/// macOS does not know it (the tests' fake pids), from Cua's own list, kept two seconds —
/// that list scans installed apps too and took ~0.9 s a call (measured 2026-10-09).
fn cua_app(ctx: &Ctx, cua: &Cua, pid: i64, session: &str) -> Result<App, Refusal> {
    if let Some(app) = app_of_pid(pid) {
        return Ok(app);
    }
    let cached = ctx
        .state
        .cua_apps
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .as_ref()
        .filter(|(at, _)| at.elapsed() < Duration::from_secs(2))
        .and_then(|(_, list)| list.iter().find(|a| a.pid == pid).cloned());
    if let Some(app) = cached {
        return Ok(app);
    }
    let answer = cua
        .call(
            "list_apps",
            json!({"session": session}),
            Duration::from_secs(20),
        )
        .map_err(|f| f.refusal)?;
    let list = cua_running_apps(&answer.result);
    let found = list.iter().find(|a| a.pid == pid).cloned();
    *ctx.state.cua_apps.lock().unwrap_or_else(|p| p.into_inner()) = Some((Instant::now(), list));
    found.ok_or_else(|| refuse("app_not_running", format!("no running app has pid {pid}")))
}

/// Cua Driver's app list without the never-list, and without its text part (which
/// names every app).
fn cua_filtered_apps(result: &Value, never: &[String]) -> Value {
    let apps: Vec<Value> = result
        .pointer("/structuredContent/apps")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|a| {
            let name = a.get("name").and_then(Value::as_str).unwrap_or("");
            let bundle_id = a.get("bundle_id").and_then(Value::as_str).unwrap_or("");
            let tier = policy::tier(bundle_id, name, never);
            (tier != Tier::Denied).then(|| {
                json!({"name": name, "bundle_id": bundle_id, "pid": a.get("pid"),
                       "running": a.get("running"), "active": a.get("active"),
                       "tier": policy::tier_name(tier)})
            })
        })
        .collect();
    json!({"structuredContent": {"apps": apps}})
}

#[cfg(target_os = "macos")]
fn live_secure_at(pid: i64, x: f64, y: f64) -> Option<bool> {
    crate::macos::secure_at(i32::try_from(pid).ok()?, x, y)
}

#[cfg(not(target_os = "macos"))]
fn live_secure_at(_pid: i64, _x: f64, _y: f64) -> Option<bool> {
    None
}

#[cfg(target_os = "macos")]
fn live_focused_secure(pid: i64) -> Option<bool> {
    crate::macos::focused_secure(i32::try_from(pid).ok()?)
}

#[cfg(not(target_os = "macos"))]
fn live_focused_secure(_pid: i64) -> Option<bool> {
    None
}

/// `{tool, args, session?, never?}`: one Cua Driver tool call, through Hands' rules.
fn cua_op(ctx: &Ctx, args: &Value) -> Result<Value, Refusal> {
    let cua = ctx.state.cua.as_ref().ok_or_else(|| {
        refuse(
            "engine_missing",
            "Cua Driver is not installed with this Arslan Hands",
        )
    })?;
    let tool = args
        .get("tool")
        .and_then(Value::as_str)
        .ok_or_else(|| refuse("bad_request", "`tool` is required"))?;
    let kind = cua_policy::kind(tool)?;
    let session = cua_session(args);
    let call = cua_policy::sanitize(
        tool,
        kind,
        args.get("args").unwrap_or(&Value::Null),
        &session,
    )?;
    let never = never_list(args);
    let mut app = None;
    let mut secure_check = "none";
    if kind != Kind::Global {
        let pid = call.get("pid").and_then(Value::as_i64).unwrap_or_default();
        let found = cua_app(ctx, cua, pid, &session)?;
        let tier = policy::tier(&found.bundle_id, &found.name, &never);
        if tier == Tier::Denied || (kind == Kind::Act && !cua_policy::tier_allows(tier, tool)) {
            return Err(tier_refusal(tier, tool, &found));
        }
        if kind == Kind::Act {
            if let Some(token) = call.get("element_token").and_then(Value::as_str) {
                let element = ctx
                    .state
                    .tokens
                    .lock()
                    .unwrap_or_else(|p| p.into_inner())
                    .get(token, pid)?
                    .clone();
                if cua_policy::types(tool) {
                    if element.looks_secure() {
                        return Err(refuse(
                            "password_field",
                            "Arslan never types into password fields",
                        ));
                    }
                    secure_check = match element
                        .center()
                        .and_then(|(x, y)| live_secure_at(pid, x, y))
                    {
                        Some(true) => {
                            return Err(refuse(
                                "password_field",
                                "Arslan never types into password fields",
                            ))
                        }
                        Some(false) => "live",
                        None => "label_only",
                    };
                }
            }
            if matches!(tool, "press_key" | "hotkey") {
                // Keys go to whatever has the app's focus.
                match live_focused_secure(pid) {
                    Some(true) => {
                        return Err(refuse(
                            "password_field",
                            "Arslan never sends keys to a password field",
                        ))
                    }
                    Some(false) => secure_check = "live",
                    None if secure_check == "none" => secure_check = "label_only",
                    None => {}
                }
            }
        }
        app = Some(found);
    }
    if runner::generation() != ctx.generation {
        return Err(refuse("stopped_by_user", "stopped before it started"));
    }
    let pid = app.as_ref().map(|a| a.pid);
    let front_before = if kind == Kind::Act {
        frontmost_pid()
    } else {
        None
    };
    let mut call = call;
    let mut renewed = false;
    let answer = loop {
        let round = *ctx
            .state
            .cua_sessions
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .get(&session)
            .unwrap_or(&0);
        let label = if round == 0 {
            session.clone()
        } else {
            format!("{session}-{round}")
        };
        call.insert("session".into(), Value::String(label));
        let answer = match cua.call(tool, Value::Object(call.clone()), cua_deadline(kind)) {
            Ok(answer) => answer,
            Err(failed) => {
                let refusal = if runner::generation() != ctx.generation {
                    refuse("stopped_by_user", "stopped")
                } else {
                    failed.refusal
                };
                return Ok(refused_after(refusal, failed.completion));
            }
        };
        // A session that ended refuses before doing anything: start a fresh label, once.
        if !renewed && cua_refusal_code(&answer.result).as_deref() == Some("session_ended") {
            renewed = true;
            *ctx.state
                .cua_sessions
                .lock()
                .unwrap_or_else(|p| p.into_inner())
                .entry(session.clone())
                .or_insert(0) += 1;
            continue;
        }
        break answer;
    };
    let focus_restored = match (kind, pid) {
        (Kind::Act, Some(pid)) => front_back(front_before, pid),
        _ => false,
    };
    let front_after = if kind == Kind::Act {
        frontmost_pid()
    } else {
        None
    };
    if !answer.ok {
        return Ok(refused_after(
            refuse(
                "engine_error",
                format!(
                    "{}: {}",
                    answer.error_code.unwrap_or_default(),
                    answer.error.unwrap_or_default()
                ),
            ),
            Completion::Completed,
        ));
    }
    // Cua's own "no" (isError): said as a refusal, never relayed as a success — an empty app
    // list in place of "session ended" hid every app from the harness (2026-10-09).
    if answer.result.get("isError").and_then(Value::as_bool) == Some(true) {
        let code = cua_refusal_code(&answer.result).unwrap_or_else(|| "error".into());
        let text = answer
            .result
            .pointer("/content/0/text")
            .and_then(Value::as_str)
            .unwrap_or("")
            .chars()
            .take(500)
            .collect::<String>();
        let mut refused = refused_after(
            refuse("engine_refused", format!("{code}: {text}")),
            Completion::Completed,
        );
        if kind == Kind::Act {
            // Cua refused it: nothing was delivered, unless its result says otherwise.
            let said = crate::outcome::from_cua(&answer.result);
            refused["outcome"] = json!(if said == "sent_unconfirmed" {
                "refused"
            } else {
                said
            });
        }
        return Ok(refused);
    }
    let result = match tool {
        "list_apps" => cua_filtered_apps(&answer.result, &never),
        "get_window_state" => {
            let mut answer_result = answer.result;
            cua_policy::without_system_menu(&mut answer_result);
            ctx.state
                .tokens
                .lock()
                .unwrap_or_else(|p| p.into_inner())
                .record(&answer_result);
            answer_result
        }
        _ => answer.result,
    };
    Ok(json!({
        "ok": true,
        "engine": "cua",
        "tool": tool,
        "completion": Completion::Completed.name(),
        "result": result,
        "app": app.as_ref().map(app_json),
        "secure_check": secure_check,
        "outcome": (kind == Kind::Act).then(|| crate::outcome::from_cua(&result)),
        "mode_used": (kind == Kind::Act).then_some("background"),
        "focus_restored": focus_restored,
        "front": {"before": front_before, "after": front_after},
    }))
}
