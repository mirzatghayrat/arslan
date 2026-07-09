import { Tool, Skill, AppSettings } from './types';

export const TOOLS: Tool[] = [
  {
    id: 'web-search',
    name: 'Web Search',
    description: 'Queries live web indexes using Tavily/Google API for deep research.',
    emoji: '🔍',
    category: 'standard',
    tier: 'tier-1'
  },
  {
    id: 'stock-data',
    name: 'Stock Sandbox',
    description: 'Retrieves live tick-level charts and historical stock analytics.',
    emoji: '📈',
    category: 'standard',
    tier: 'tier-1'
  },
  {
    id: 'py-exec',
    name: 'PyExec Sandbox',
    description: 'Isolated Python environment for secure data processing & plotting.',
    emoji: '🐍',
    category: 'standard',
    tier: 'tier-2'
  },
  {
    id: 'canvas-render',
    name: 'SVGRenderer',
    description: 'Builds interactive layouts and dynamic SVG flowcharts on demand.',
    emoji: '🎨',
    category: 'standard',
    tier: 'tier-2'
  },
  {
    id: 'gmail-broker',
    name: 'Gmail Broker Brokerage',
    description: 'Send and schedule external emails. Requires premium execution scope.',
    emoji: '🔒 📧',
    category: 'advanced_locked',
    tier: 'tier-3'
  },
  {
    id: 'spanner-db',
    name: 'Cloud Spanner Direct',
    description: 'Direct transaction writes to production storage pools. Critical priority.',
    emoji: '🔒 🧱',
    category: 'advanced_locked',
    tier: 'tier-3'
  }
];

export const SKILLS: Skill[] = [
  {
    id: 'seo-opt',
    name: 'SEO Copywriting',
    description: 'Optimizing structured text for search engine relevancy and maximum click-through.',
    emoji: '✍️',
    category: 'standard'
  },
  {
    id: 'financial-res',
    name: 'Financial Research',
    description: 'Interpreting earnings call sheets, balance summaries, and valuation models.',
    emoji: '📊',
    category: 'standard'
  },
  {
    id: 'infographic-design',
    name: 'Infographic Layout',
    description: 'Condensing multi-page text analyses into highly scannable, visually beautiful diagrams.',
    emoji: '📘',
    category: 'standard'
  },
  {
    id: 'stat-analysis',
    name: 'Statistical Forecasting',
    description: 'Autoregressive trend analysis, predictive regressions, and moving regressions.',
    emoji: '📉',
    category: 'standard'
  },
  {
    id: 'vuln-test',
    name: 'Network Penetration Auditing',
    description: 'Automated vulnerability scanning, buffer overflow analysis, and boundary mapping.',
    emoji: '🔒 🛡️',
    category: 'advanced_locked'
  }
];

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
  runDebugRetentionDays: 30
};
