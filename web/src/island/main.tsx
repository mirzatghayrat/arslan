import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import IslandApp from './IslandApp';
import './island.css';

// The island page (island.html) in the shell's second, transparent window.
// It loads none of the app bundle: no global CSS, no i18next, no API client.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <IslandApp />
  </StrictMode>,
);
