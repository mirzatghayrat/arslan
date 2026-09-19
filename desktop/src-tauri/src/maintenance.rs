//! Process-local exclusivity, not a replacement for backend profile locks.
use std::sync::{
    atomic::{AtomicU8, Ordering},
    Arc, Mutex, MutexGuard,
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
pub(crate) struct Gate {
    state: Arc<AtomicU8>,
    admission: Mutex<()>,
}

pub(crate) struct Permit {
    state: Option<Arc<AtomicU8>>,
    fail_closed: bool,
}

impl Gate {
    pub(crate) fn begin(&self, operation: Operation) -> Option<Permit> {
        // A helper start/open already admitted must finish publishing its
        // handle before recovery can acquire ownership and stop that helper.
        let _admission = self.admission.lock().ok()?;
        self.state
            .compare_exchange(IDLE, operation as u8, Ordering::SeqCst, Ordering::SeqCst)
            .ok()?;
        Some(Permit {
            state: Some(self.state.clone()),
            fail_closed: !matches!(operation, Operation::Update),
        })
    }
    pub(crate) fn is_idle(&self) -> bool {
        self.state.load(Ordering::SeqCst) == IDLE
    }
    /// Hold through the complete native side effect, not merely an idle check.
    /// Stop/mute commands deliberately do not require this permit.
    pub(crate) fn interactive(&self) -> Option<MutexGuard<'_, ()>> {
        let guard = self.admission.lock().ok()?;
        self.is_idle().then_some(guard)
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
    fn maintenance_excludes_new_interactive_work_including_after_pause() {
        let gate = Gate::default();
        assert!(gate.interactive().is_some());
        for operation in [Operation::Startup, Operation::Update, Operation::Recovery] {
            let permit = gate.begin(operation).unwrap();
            assert!(gate.interactive().is_none());
            permit.complete();
        }
        drop(gate.begin(Operation::Recovery).unwrap());
        assert!(gate.interactive().is_none());
    }
    #[test]
    fn recovery_waits_for_admitted_helper_to_publish_before_stopping() {
        let gate = Arc::new(Gate::default());
        let admitted = gate.interactive().unwrap();
        let child = gate.clone();
        let published = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let worker_published = published.clone();
        let (started_tx, started_rx) = std::sync::mpsc::channel();
        let (owned_tx, owned_rx) = std::sync::mpsc::channel();
        let worker = std::thread::spawn(move || {
            started_tx.send(()).unwrap();
            let permit = child.begin(Operation::Recovery).unwrap();
            assert!(worker_published.load(Ordering::SeqCst));
            owned_tx.send(()).unwrap();
            permit.complete();
        });
        started_rx.recv().unwrap();
        assert!(owned_rx.try_recv().is_err());
        published.store(true, Ordering::SeqCst);
        drop(admitted);
        owned_rx.recv_timeout(std::time::Duration::from_secs(2)).unwrap();
        worker.join().unwrap();
    }
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
