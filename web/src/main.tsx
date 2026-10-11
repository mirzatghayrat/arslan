import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import {ErrorBoundary} from './components/ErrorBoundary';
import {bootstrapInjectedToken} from './lib/injectedToken';
import {dismissBootVeil} from './lib/bootVeil';
import './index.css';
import './i18n';
import { useIconStore } from './stores/iconStore';
void useIconStore.getState().initialize();

// Hydrate a packaged/desktop build's injected bearer token (window.__ARSLAN_TOKEN__)
// into the auth store before first render. No-op in dev (global absent).
bootstrapInjectedToken();

const root = createRoot(document.getElementById('root')!);
if (import.meta.env.DEV && location.hash.startsWith('#kit-gallery')) {
  // 0.1.55: dev-only surface-kit gallery for screenshots (never in a build).
  const params = new URLSearchParams(location.hash.slice(location.hash.indexOf('&') + 1));
  document.documentElement.classList.toggle('dark', location.hash.includes('&dark'));
  if (params.get('p')) document.documentElement.dataset.palette = params.get('p')!;
  void import('./__tests__/gallery/KitGallery').then(({ default: KitGallery }) => root.render(<KitGallery />));
} else if (import.meta.env.DEV && location.hash.startsWith('#first-run')) {
  // 0.1.60: dev-only preview of the first-run film over a stand-in for the app (never in a build).
  document.documentElement.classList.toggle('dark', location.hash.includes('&dark'));
  void import('./__tests__/gallery/FirstRunPreview').then(({ default: FirstRunPreview }) => root.render(<FirstRunPreview />));
} else {
  root.render(
    <StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </StrictMode>,
  );
}

// Two frames, not one. `render` only schedules work, and a single rAF can fire
// before React has committed and painted — which would fade the veil away from
// an empty page and show the flash it exists to hide. The second rAF is
// dispatched after the first frame has gone to the compositor.
requestAnimationFrame(() => requestAnimationFrame(() => dismissBootVeil()));
