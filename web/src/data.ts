import { Tool, Skill, Spawn, Message, AppSettings } from './types';

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

export const DEFAULT_SPAWNS: Spawn[] = [
  {
    id: 'spawn-aletheia',
    name: 'Aletheia',
    domain: 'Financial Market Intelligence',
    description: 'Specializes in quantitative valuation, stock modeling, and macroeconomic synthesis.',
    status: 'idle',
    avatarEmoji: '🦊',
    tools: ['web-search', 'stock-data', 'py-exec'],
    skills: ['financial-res', 'stat-analysis'],
    totalTasks: 42
  },
  {
    id: 'spawn-huan',
    name: 'Huan',
    domain: 'RED / XiaoHongShu Copywriting',
    description: 'SEO copywriter equipped to draft viral hooks, engaging bullet lists, and generate creative visual cards.',
    status: 'working',
    avatarEmoji: '🐱',
    tools: ['web-search', 'canvas-render'],
    skills: ['seo-opt', 'infographic-design'],
    totalTasks: 19
  }
];

export const DEFAULT_SETTINGS: AppSettings = {
  llmProvider: 'gemini',
  llmModel: 'gemini-3.5-flash',
  searchProvider: 'tavily',
  apiKeyLLM: '••••••••••••••••••••••••••••••••',
  apiKeySearch: '••••••••••••••••••••••••',
  language: 'English (US)',
  theme: 'dark',
  telemetry: false,
  spawnMode: 'interactive',
  llmStrategy: 'single'
};

export const INITIAL_CHAT_HISTORY: Message[] = [
  {
    id: 'msg-1',
    sender: 'user',
    senderName: 'Mirzat',
    senderAvatar: '🦁',
    text: 'Show me the recent market reaction to Nvidia’s earnings and draft a viral summary slide for my tech-focused channel.',
    timestamp: '15:34'
  },
  {
    id: 'msg-2',
    sender: 'arslan',
    senderName: 'Arslan',
    senderAvatar: '🦁',
    text: 'Acknowledged. This request demands multi-agent coordination. I will route Nvidia’s valuation analysis to **Aletheia** (Financial specialist) and delegate visual card layout drafting to **Huan** (Marketing & Layout copywriter). Initiating spawns...',
    timestamp: '15:34',
    routedTo: {
      spawnId: 'spawn-aletheia',
      spawnName: 'Aletheia'
    }
  },
  {
    id: 'msg-3',
    sender: 'spawn',
    senderName: 'Aletheia',
    senderAvatar: '🦊',
    text: 'Hi Mirzat, financial specialist Aletheia starting up. Ready to execute real-time market data retrieval and model Nvidia’s Q1 figures. Let’s look up current trading logs.',
    timestamp: '15:35',
    spawnIntro: {
      name: 'Aletheia',
      domain: 'Financial Market Intelligence',
      avatarEmoji: '🦊',
      tools: ['web-search', 'stock-data', 'py-exec'],
      skills: ['financial-res', 'stat-analysis']
    }
  },
  {
    id: 'msg-4',
    sender: 'spawn',
    senderName: 'Aletheia',
    senderAvatar: '🦊',
    text: 'Invoking my tools to pull Nvidias latest stock ticks and earnings statements.',
    timestamp: '15:35',
    toolActivity: {
      id: 'tool-act-1',
      toolName: 'Stock Sandbox',
      emoji: '📈',
      status: 'completed',
      action: 'Querying Bloomberg & Yahoo Finance direct ticker sockets for $NVDA',
      outputSummary: 'Loaded stock price $127.40 (+4.2%), revenue beat guidance by 9%, total growth projections elevated by 15%.',
      collapsed: false
    }
  },
  {
    id: 'msg-5',
    sender: 'spawn',
    senderName: 'Aletheia',
    senderAvatar: '🦊',
    text: 'Analysis Completed: $NVDA is trading at $127.40, a robust +4.2% bounce post-release. The primary catalyst is the 9% top-line revenue beat driven by strong Blackwell data-center demand. I am passing this synthesis back to Arslan and routing to Huan to format the viral creative slide.',
    timestamp: '15:36'
  },
  {
    id: 'msg-6',
    sender: 'arslan',
    senderName: 'Arslan',
    senderAvatar: '🦁',
    text: 'Financial research successfully completed by Aletheia. I will now route this structured analysis to **Huan** to design the viral infographic slide deck.',
    timestamp: '15:36',
    routedTo: {
      spawnId: 'spawn-huan',
      spawnName: 'Huan'
    }
  },
  {
    id: 'msg-7',
    sender: 'spawn',
    senderName: 'Huan',
    senderAvatar: '🐱',
    text: 'Spawn Huan online! Ready to elevate our copywriting! Let’s formulate a highly engaging RED-style hook along with key bullets, and render an infographic deck using the SVGRenderer tool.',
    timestamp: '15:36',
    spawnIntro: {
      name: 'Huan',
      domain: 'RED / XiaoHongShu Copywriting',
      avatarEmoji: '🐱',
      tools: ['web-search', 'canvas-render'],
      skills: ['seo-opt', 'infographic-design']
    }
  },
  {
    id: 'msg-8',
    sender: 'spawn',
    senderName: 'Huan',
    senderAvatar: '🐱',
    text: 'Executing layout rendering...',
    timestamp: '15:37',
    toolActivity: {
      id: 'tool-act-2',
      toolName: 'SVGRenderer',
      emoji: '🎨',
      status: 'completed',
      action: 'Generating SVG layout: 1080x1350px canvas, background #0B0E14, accent #FF8E24.',
      outputSummary: 'Compiled canvas with grid, typography headers, stock ticker chart vector, and visual container elements.',
      collapsed: false
    }
  },
  {
    id: 'msg-9',
    sender: 'spawn',
    senderName: 'Huan',
    senderAvatar: '🐱',
    text: 'Here is the draft slide and viral copy:\n\n🔥 **NVIDIA Earnings Blowout! Blackwell Accelerates to Cosmic Speeds** 🚀\n\n- **Stock Ticker:** $127.40 (+4.2% After-hours Bounce)\n- **Catalyst:** Blackwell chip demand surpasses all forecasts\n- **Alpha:** Data Center revenues rose 150% YoY!',
    timestamp: '15:37'
  }
];
