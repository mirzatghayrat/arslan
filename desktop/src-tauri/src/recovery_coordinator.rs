//! Ordered trusted-native recovery policy. No file picker or model/web IPC here.
//! Errors after requesting stop are uncertain: keep paused, do not auto-retry,
//! rollback, finalize or restart. Existing journals protect later fresh startup.
use crate::maintenance::{Gate, Operation};

#[derive(Debug, PartialEq, Clone, Copy)]
pub(crate) enum Stage {
    Stop,
    Prepare,
    Rewrap,
    Switch,
    Trial,
    Confirmation,
    Finalize,
    Restart,
}

#[derive(Debug, PartialEq)]
pub(crate) enum Outcome {
    Busy,
    Cancelled,
    Refused,
    Paused(Stage),
    Complete,
}

pub(crate) trait Steps {
    /// Own selected archive/source key and actual launch-config durable proof.
    /// false = cancelled; error = refused without any profile/process mutation.
    fn select_and_validate(&mut self) -> Result<bool, ()>;
    fn confirm_adaptation(&mut self) -> bool;
    fn recheck_target(&mut self) -> Result<(), ()>;
    fn stop(&mut self) -> Result<(), ()>;
    fn prepare(&mut self) -> Result<(), ()>;
    fn rewrap(&mut self) -> Result<(), ()>;
    fn switch(&mut self) -> Result<String, ()>;
    fn trial(&mut self, operation: &str) -> Result<(), ()>;
    fn confirm_finalization(&mut self, operation: &str) -> bool;
    fn finalize(&mut self, operation: &str) -> Result<(), ()>;
    /// Must observe normal health/readiness, not merely spawn a child.
    fn restart(&mut self) -> Result<(), ()>;
}

pub(crate) fn run(gate: &Gate, steps: &mut impl Steps) -> Outcome {
    let Some(permit) = gate.begin(Operation::Recovery) else {
        return Outcome::Busy;
    };
    match steps.select_and_validate() {
        Ok(true) => {}
        Ok(false) => {
            permit.complete();
            return Outcome::Cancelled;
        }
        Err(()) => {
            permit.complete();
            return Outcome::Refused;
        }
    }
    if !steps.confirm_adaptation() {
        permit.complete();
        return Outcome::Cancelled;
    }
    if steps.recheck_target().is_err() {
        permit.complete();
        return Outcome::Refused;
    }
    // From here on, dropping the permit pauses ALL maintenance. No later phase
    // may treat a refusal or timeout as evidence that nothing was changed.
    if steps.stop().is_err() {
        return Outcome::Paused(Stage::Stop);
    }
    macro_rules! step {
        ($stage:ident, $call:expr) => {
            if steps.recheck_target().is_err() || $call.is_err() {
                return Outcome::Paused(Stage::$stage);
            }
        };
    }
    step!(Prepare, steps.prepare());
    step!(Rewrap, steps.rewrap());
    if steps.recheck_target().is_err() {
        return Outcome::Paused(Stage::Switch);
    }
    let operation = match steps.switch() {
        Ok(value) if crate::recovery_control::valid_id(&value) => value,
        _ => return Outcome::Paused(Stage::Switch),
    };
    step!(Trial, steps.trial(&operation));
    if !steps.confirm_finalization(&operation) {
        return Outcome::Paused(Stage::Confirmation);
    }
    step!(Finalize, steps.finalize(&operation));
    step!(Restart, steps.restart());
    permit.complete();
    Outcome::Complete
}

#[cfg(test)]
mod tests {
    use super::*;
    const ID: &str = "01234567-89ab-cdef-0123-456789abcdef";
    #[derive(Default)]
    struct Fixture {
        calls: Vec<String>,
        failure: Option<&'static str>,
        cancel: Option<&'static str>,
        key_failure: usize,
        key_checks: usize,
        invalid_operation: bool,
    }
    impl Fixture {
        fn action(&mut self, name: &str) -> Result<(), ()> {
            self.calls.push(name.into());
            if self.failure == Some(name) {
                Err(())
            } else {
                Ok(())
            }
        }
    }
    impl Steps for Fixture {
        fn select_and_validate(&mut self) -> Result<bool, ()> {
            self.action("select")?;
            Ok(self.cancel != Some("select"))
        }
        fn confirm_adaptation(&mut self) -> bool {
            self.calls.push("consent".into());
            self.cancel != Some("consent")
        }
        fn recheck_target(&mut self) -> Result<(), ()> {
            self.key_checks += 1;
            self.action("key")?;
            if self.key_failure == self.key_checks {
                Err(())
            } else {
                Ok(())
            }
        }
        fn stop(&mut self) -> Result<(), ()> {
            self.action("stop")
        }
        fn prepare(&mut self) -> Result<(), ()> {
            self.action("prepare")
        }
        fn rewrap(&mut self) -> Result<(), ()> {
            self.action("rewrap")
        }
        fn switch(&mut self) -> Result<String, ()> {
            self.action("switch")?;
            Ok(if self.invalid_operation {
                "invalid"
            } else {
                ID
            }
            .into())
        }
        fn trial(&mut self, operation: &str) -> Result<(), ()> {
            assert_eq!(operation, ID);
            self.action("trial")
        }
        fn confirm_finalization(&mut self, operation: &str) -> bool {
            assert_eq!(operation, ID);
            self.calls.push("confirm".into());
            self.cancel != Some("confirm")
        }
        fn finalize(&mut self, operation: &str) -> Result<(), ()> {
            assert_eq!(operation, ID);
            self.action("finalize")
        }
        fn restart(&mut self) -> Result<(), ()> {
            self.action("restart")
        }
    }
    #[test]
    fn success_is_ordered_and_confirmed_with_one_bound_operation() {
        let gate = Gate::default();
        let mut steps = Fixture::default();
        assert_eq!(run(&gate, &mut steps), Outcome::Complete);
        assert_eq!(
            steps.calls,
            [
                "select", "consent", "key", "stop", "key", "prepare", "key", "rewrap", "key",
                "switch", "key", "trial", "confirm", "key", "finalize", "key", "restart"
            ]
        );
        assert!(gate.is_idle());
    }
    #[test]
    fn early_cancel_or_refusal_never_stops_the_running_backend() {
        for cancel in ["select", "consent"] {
            let gate = Gate::default();
            let mut steps = Fixture {
                cancel: Some(cancel),
                ..Default::default()
            };
            assert_eq!(run(&gate, &mut steps), Outcome::Cancelled);
            assert!(!steps.calls.iter().any(|s| s == "stop"));
            assert!(gate.is_idle());
        }
        for failure in ["select", "key"] {
            let gate = Gate::default();
            let mut steps = Fixture {
                failure: Some(failure),
                ..Default::default()
            };
            assert_eq!(run(&gate, &mut steps), Outcome::Refused);
            assert!(!steps.calls.iter().any(|s| s == "stop"));
            assert!(gate.is_idle());
        }
    }
    #[test]
    fn each_failure_stops_the_sequence_and_prevents_update_or_retry() {
        for (failure, stage) in [
            ("stop", Stage::Stop),
            ("prepare", Stage::Prepare),
            ("rewrap", Stage::Rewrap),
            ("switch", Stage::Switch),
            ("trial", Stage::Trial),
            ("finalize", Stage::Finalize),
            ("restart", Stage::Restart),
        ] {
            let gate = Gate::default();
            let mut steps = Fixture {
                failure: Some(failure),
                ..Default::default()
            };
            assert_eq!(run(&gate, &mut steps), Outcome::Paused(stage));
            assert_eq!(steps.calls.last().unwrap(), failure);
            let before = steps.calls.clone();
            assert_eq!(run(&gate, &mut steps), Outcome::Busy);
            assert_eq!(steps.calls, before);
            assert!(gate.begin(Operation::Update).is_none());
        }
    }
    #[test]
    fn declining_finalization_keeps_pending_state_without_implicit_rollback() {
        let gate = Gate::default();
        let mut steps = Fixture {
            cancel: Some("confirm"),
            ..Default::default()
        };
        assert_eq!(run(&gate, &mut steps), Outcome::Paused(Stage::Confirmation));
        assert_eq!(steps.calls.last().unwrap(), "confirm");
        assert!(!gate.is_idle());
    }

    #[test]
    fn changed_target_at_every_later_boundary_prevents_the_next_action() {
        for (index, stage, action) in [
            (2, Stage::Prepare, "prepare"),
            (3, Stage::Rewrap, "rewrap"),
            (4, Stage::Switch, "switch"),
            (5, Stage::Trial, "trial"),
            (6, Stage::Finalize, "finalize"),
            (7, Stage::Restart, "restart"),
        ] {
            let gate = Gate::default();
            let mut steps = Fixture {
                key_failure: index,
                ..Default::default()
            };
            assert_eq!(run(&gate, &mut steps), Outcome::Paused(stage));
            assert!(!steps.calls.iter().any(|s| s == action));
            assert!(!gate.is_idle());
        }
    }

    #[test]
    fn busy_gate_never_opens_selection_and_invalid_operation_never_runs_trial() {
        let gate = Gate::default();
        let update = gate.begin(Operation::Update).unwrap();
        let mut steps = Fixture::default();
        assert_eq!(run(&gate, &mut steps), Outcome::Busy);
        assert!(steps.calls.is_empty());
        drop(update);
        steps.invalid_operation = true;
        assert_eq!(run(&gate, &mut steps), Outcome::Paused(Stage::Switch));
        assert_eq!(steps.calls.last().unwrap(), "switch");
    }
}
