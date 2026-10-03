//! The contract fixtures (tests/fixtures/hands_contract/) say which command line
//! Hands must build for each request. This checks the builder against every case;
//! pytest checks the backend's reading of the same envelopes, and
//! scripts/hands_contract_check.py runs the same command lines against a real
//! binary.

use arslan_hands::argv;
use serde_json::Value;
use std::path::PathBuf;

fn cases() -> Vec<Value> {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/hands_contract");
    let mut out: Vec<Value> = std::fs::read_dir(&dir)
        .expect("contract fixtures")
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().is_some_and(|x| x == "json"))
        .map(|e| serde_json::from_slice(&std::fs::read(e.path()).unwrap()).unwrap())
        .collect();
    out.sort_by_key(|c| c["order"].as_u64());
    out
}

#[test]
fn every_case_builds_exactly_its_command_line() {
    let cases = cases();
    assert!(cases.len() >= 20, "the fixtures are present");
    let mut ops = std::collections::BTreeSet::new();
    for case in &cases {
        let expected: Vec<String> = case["argv"]
            .as_array()
            .unwrap()
            .iter()
            .map(|a| a.as_str().unwrap().to_string())
            .collect();
        match case["op"].as_str() {
            Some(op) => {
                let built = argv::build(op, &case["args"], None)
                    .unwrap_or_else(|r| panic!("{}: refused {r:?}", case["case"]));
                assert_eq!(built, expected, "{}", case["case"]);
                ops.insert(op.to_string());
            }
            // A command line Hands must never produce (an unqualified ref).
            None => {
                let refused = argv::build(
                    "click",
                    &serde_json::json!({"ref": expected.last().unwrap()}),
                    None,
                );
                assert_eq!(refused.unwrap_err().code, "bad_ref", "{}", case["case"]);
            }
        }
    }
    let all: std::collections::BTreeSet<String> = argv::OPS.iter().map(|s| s.to_string()).collect();
    assert_eq!(ops, all, "one case per contract command at least");
}

#[test]
fn every_case_has_a_real_envelope_of_the_expected_outcome() {
    for case in cases() {
        let envelope = &case["envelope"];
        assert_eq!(envelope["version"], "2.4", "{}", case["case"]);
        let expect_ok = case["expect"]["ok"].as_bool().unwrap();
        let also_ok = case["expect"]["also"]
            .as_array()
            .is_some_and(|a| a.iter().any(|v| v == "ok"));
        let got_ok = envelope["ok"].as_bool().unwrap();
        assert!(
            got_ok == expect_ok || (got_ok && also_ok),
            "{}",
            case["case"]
        );
        if !got_ok {
            let code = &envelope["error"]["code"];
            let also = case["expect"]["also"]
                .as_array()
                .cloned()
                .unwrap_or_default();
            assert!(
                *code == case["expect"]["code"] || also.contains(code),
                "{}",
                case["case"]
            );
            assert_eq!(case["exit"], 1, "{}", case["case"]);
        }
    }
}
