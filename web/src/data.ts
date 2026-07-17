import { AppSettings } from './types';

// NOTE: The former hardcoded TOOLS/SKILLS catalogs (with invented capability
// names) were removed — equipped-capability chips now resolve keys against the
// REAL backend registry (see stores/registryStore.ts). Never re-introduce
// fabricated capability data here.

export const DEFAULT_SETTINGS: AppSettings = {
  searchProvider: 'tavily',
  apiKeySearch: '••••••••••••••••••••••••',
  githubToken: '',
  language: 'en',
  theme: 'dark',
  telemetry: false,
  spawnMode: 'interactive',
  llmStrategy: 'single',
  distillOnSessionEnd: true,
  orchestratorShellEnabled: false,
  shellConfirmPolicy: 'ask_all',
  runDebugRetentionDays: 30,
  mcpServerEnabled: false
};
