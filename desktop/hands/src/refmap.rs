//! Which app a ref was read from, from agent-desktop's own refmap.
//!
//! A grant is per app ("act in Notes"); a ref is just text the model passes.
//! Before any action Hands reads the ref's entry from the snapshot it came from
//! and checks its process against the app the request names, so a grant for one
//! app cannot be spent on a ref from another (`ref_wrong_app`).
//!
//! Layout (agent-desktop 0.9.4, `RefStore`): `<home>/[sessions/<id>/]snapshots/
//! <snapshot id>/refmap.json` = `{"inner": {"@e7": {"pid": …, "role": …,
//! "name": …, "available_actions": […], …}}, "counter": N}`.

use crate::argv::{parse_ref, session_ok};
use serde_json::Value;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Target {
    pub pid: i64,
    pub role: String,
    pub name: Option<String>,
    pub actions: Vec<String>,
}

pub fn refmap_path(home: &Path, session: Option<&str>, snapshot_id: &str) -> PathBuf {
    let base = match session {
        Some(s) => home.join("sessions").join(s),
        None => home.to_path_buf(),
    };
    base.join("snapshots").join(snapshot_id).join("refmap.json")
}

/// The entry for a ref, or None if the ref, its snapshot or its entry is unknown.
/// Ref and session are validated before they become path components.
pub fn lookup(home: &Path, session: Option<&str>, reference: &str) -> Option<Target> {
    let (snapshot_id, element) = parse_ref(reference)?;
    if session.is_some_and(|s| !session_ok(s)) {
        return None;
    }
    let raw = std::fs::read(refmap_path(home, session, snapshot_id)).ok()?;
    let map: Value = serde_json::from_slice(&raw).ok()?;
    let entry = map.get("inner")?.get(format!("@{element}"))?;
    Some(Target {
        pid: entry.get("pid")?.as_i64()?,
        role: entry
            .get("role")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        name: entry
            .get("name")
            .and_then(Value::as_str)
            .map(str::to_string),
        actions: entry
            .get("available_actions")
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .filter_map(Value::as_str)
                    .map(str::to_string)
                    .collect()
            })
            .unwrap_or_default(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn home() -> PathBuf {
        let h = std::env::temp_dir().join(format!("hands-refmap-{}", std::process::id()));
        let _ = fs::remove_dir_all(&h);
        let dir = h
            .join("sessions")
            .join("job1")
            .join("snapshots")
            .join("sabc123");
        fs::create_dir_all(&dir).unwrap();
        fs::write(
            dir.join("refmap.json"),
            r#"{"inner":{"@e3":{"pid":4242,"role":"button","name":"Save","available_actions":["Click"]}},"counter":3}"#,
        )
        .unwrap();
        h
    }

    #[test]
    fn a_ref_resolves_to_its_process_only_in_its_session() {
        let h = home();
        let t = lookup(&h, Some("job1"), "@sabc123:e3").unwrap();
        assert_eq!(
            (t.pid, t.role.as_str(), t.name.as_deref()),
            (4242, "button", Some("Save"))
        );
        assert_eq!(t.actions, vec!["Click".to_string()]);
        assert!(
            lookup(&h, None, "@sabc123:e3").is_none(),
            "another namespace"
        );
        assert!(
            lookup(&h, Some("job1"), "@sabc123:e4").is_none(),
            "unknown element"
        );
        assert!(
            lookup(&h, Some("../job1"), "@sabc123:e3").is_none(),
            "no traversal"
        );
        fs::remove_dir_all(&h).unwrap();
    }
}
