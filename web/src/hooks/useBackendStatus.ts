import { useState, useEffect, useRef } from 'react';
import { api } from '../api/client';

export type BackendStatus = 'checking' | 'online' | 'offline';

const POLL_INTERVAL_MS = 10_000;

/**
 * Polls GET /api/v1/health every 10 s (and on mount) to determine whether the
 * backend is reachable.  Returns 'checking' until the first response arrives.
 */
export function useBackendStatus(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>('checking');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const check = () => {
    api
      .health()
      .then(() => setStatus('online'))
      .catch(() => setStatus('offline'));
  };

  useEffect(() => {
    check(); // immediate check on mount
    timerRef.current = setInterval(check, POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current !== null) clearInterval(timerRef.current);
    };
  }, []);

  return status;
}
