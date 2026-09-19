//! Process-local exclusivity, not a replacement for backend profile locks.
use std::sync::{
    atomic::{AtomicU8, Ordering},
    Arc,
};

const IDLE: u8 = 0;
const PAUSED: u8 = 4;

#[derive(Clone, Copy)]
pub(crate) enum Operation {
    Startup = 1,
    Update = 2,
    Recovery = 3,
}

#[derive(Default)]
pub(crate) struct Gate(Arc<AtomicU8>);

pub(crate) struct Permit {
    state: Option<Arc<AtomicU8>>,
    fail_closed: bool,
}

impl Gate {
    pub(crate) fn begin(&self, operation: Operation) -> Option<Permit> {
        self.0
            .compare_exchange(IDLE, operation as u8, Ordering::SeqCst, Ordering::SeqCst)
            .ok()?;
        Some(Permit {
            state: Some(self.0.clone()),
            fail_closed: !matches!(operation, Operation::Update),
        })
    }
    pub(crate) fn is_idle(&self) -> bool {
        self.0.load(Ordering::SeqCst) == IDLE
    }
}

impl Permit {
    /// Only a known safe completion/cancellation releases startup/recovery.
    pub(crate) fn complete(mut self) {
        if let Some(state) = self.state.take() {
            state.store(IDLE, Ordering::SeqCst);
        }
    }
}

impl Drop for Permit {
    fn drop(&mut self) {
        if let Some(state) = self.state.take() {
            state.store(
                if self.fail_closed { PAUSED } else { IDLE },
                Ordering::SeqCst,
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn all_maintenance_is_exclusive_and_releases_only_at_safe_boundaries() {
        for operation in [Operation::Startup, Operation::Update, Operation::Recovery] {
            let gate = Gate::default();
            let permit = gate.begin(operation).unwrap();
            assert!(!gate.is_idle());
            for other in [Operation::Startup, Operation::Update, Operation::Recovery] {
                assert!(gate.begin(other).is_none());
            }
            permit.complete();
            assert!(gate.is_idle());
        }
    }
    #[test]
    fn abandoned_startup_or_recovery_cannot_unlock_updates() {
        for operation in [Operation::Startup, Operation::Recovery] {
            let gate = Gate::default();
            drop(gate.begin(operation).unwrap());
            assert!(!gate.is_idle());
            assert!(gate.begin(Operation::Update).is_none());
            assert!(gate.begin(Operation::Recovery).is_none());
        }
        let gate = Gate::default();
        drop(gate.begin(Operation::Update).unwrap());
        assert!(gate.is_idle());
    }
    #[test]
    fn a_live_permit_can_cross_worker_boundaries_without_unlocking() {
        let gate = Gate::default();
        let permit = gate.begin(Operation::Recovery).unwrap();
        std::thread::spawn(move || permit.complete())
            .join()
            .unwrap();
        assert!(gate.is_idle());
    }
}
