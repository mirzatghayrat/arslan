import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import {ErrorBoundary} from './components/ErrorBoundary';
import {bootstrapInjectedToken} from './lib/injectedToken';
import {dismissBootVeil} from './lib/bootVeil';
import './index.css';
import './i18n';

// Hydrate a packaged/desktop build's injected bearer token (window.__ARSLAN_TOKEN__)
// into the auth store before first render. No-op in dev (global absent).
bootstrapInjectedToken();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);

// Two frames, not one. `render` only schedules work, and a single rAF can fire
// before React has committed and painted — which would fade the veil away from
// an empty page and show the flash it exists to hide. The second rAF is
// dispatched after the first frame has gone to the compositor.
requestAnimationFrame(() => requestAnimationFrame(() => dismissBootVeil()));
