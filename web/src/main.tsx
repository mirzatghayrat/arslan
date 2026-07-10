import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import {ErrorBoundary} from './components/ErrorBoundary';
import {bootstrapInjectedToken} from './lib/injectedToken';
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
