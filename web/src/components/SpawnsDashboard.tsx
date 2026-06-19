import React, { useState } from 'react';
import { Spawn } from '../types';
import { TOOLS, SKILLS } from '../data';
import { 
  Sliders, Wrench, BookOpen, Clock, Activity, ArrowUpRight, Shield, Cpu, 
  ChevronDown, ChevronUp, Terminal, MessageSquare, Search, Globe, RefreshCcw, Sparkles, Plus, Database, X 
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import SFSymbol from './SFSymbol';

interface SpawnsDashboardProps {
  spawns: Spawn[];
  selectedSpawnId: string | null;
  setSelectedSpawnId: (id: string | null) => void;
  cardStyle: 'isometric' | 'blueprint' | 'compact';
  setCardStyle: (style: 'isometric' | 'blueprint' | 'compact') => void;
  onEditEquipment: (spawnId: string) => void;
  onDeleteSpawn?: (spawnId: string) => void;
  onCreateSpawnClick: () => void;
  onOpenDirectChat?: (spawnId: string) => void;
  setSpawns?: React.Dispatch<React.SetStateAction<Spawn[]>>;
  setThreads?: React.Dispatch<React.SetStateAction<any[]>>;
  activeThreadId?: string;
  setSpawnChats?: React.Dispatch<React.SetStateAction<Record<string, any[]>>>;
}

export default function SpawnsDashboard({
  spawns,
  selectedSpawnId,
  setSelectedSpawnId,
  cardStyle,
  setCardStyle,
  onEditEquipment,
  onCreateSpawnClick,
  onOpenDirectChat,
  setSpawns,
  setThreads,
  activeThreadId,
  setSpawnChats
}: SpawnsDashboardProps) {

  // Global Integration Discovery & Repository Engine States
  const [showSandboxSearch, setShowSandboxSearch] = useState(true);
  const [integrationQuery, setIntegrationQuery] = useState('');
  const [isEvaluating, setIsEvaluating] = useState(false);
  const [mcpRegistry, setMcpRegistry] = useState<{name: string, url: string, description: string, tags: string[]}[]>([
    {
      name: 'Brave Search Core',
      url: 'https://github.com/brave/brave-mcp-server',
      description: 'Secure, local proxy-bypassing web crawler and semantic text extractor API node.',
      tags: ['MCP', 'Web Crawler']
    },
    {
      name: 'Local SQLite Analyzer',
      url: 'https://github.com/mcp-community/sqlite-mcp-server',
      description: 'Executes high-performance sqlite sandbox trace queries and schemas lookup.',
      tags: ['MCP', 'Database']
    }
  ]);
  const [skillRegistry, setSkillRegistry] = useState<{name: string, repo: string, capabilities: string[]}[]>([
    {
      name: 'Penetration Auditing',
      repo: 'https://github.com/test-security/network-auditor',
      capabilities: ['Intrusion Trace Audit', 'Port Handshake Map', 'Local Network Sniffing']
    }
  ]);
  const [evaluationResult, setEvaluationResult] = useState<{
    url: string;
    name: string;
    summary: string;
    capabilities: string[];
    moat: string;
    bestUse: string;
    type: 'MCP' | 'Skill';
  } | null>(null);

  const handleEvaluateRepository = (urlOrQuery: string) => {
    if (!urlOrQuery.trim()) return;
    setIsEvaluating(true);
    setEvaluationResult(null);

    const query = urlOrQuery.toLowerCase().trim();

    setTimeout(() => {
      let resultName = 'Custom Agent Workspace Spec';
      let resultUrl = urlOrQuery;
      let summary = 'Custom third-party integration analyzed via Sandboxed Engine. Perfect configuration matching found.';
      let capabilities = [
        'Automatic entry point injection',
        'Payload compliance checking',
        'Secured prompt routing schema'
      ];
      let moat = 'Dynamic authentication virtualization prevents API token leakage post-compilation.';
      let bestUse = 'Ideal for equipping general Spawns with custom task runner protocols.';
      let evaluatedType: 'MCP' | 'Skill' = 'MCP';

      if (query.includes('gdrive') || query.includes('google drive') || query.includes('google-drive') || query.includes('workspace')) {
        resultName = 'Google Drive Workspace Core';
        resultUrl = 'https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive';
        summary = 'Allows direct OAuth workspace document reads, deep hierarchical folder searches, and live-stream ingestion in Google Workspace formats.';
        capabilities = [
          'Workspace doc metadata sync & search indexing',
          'Incremental chunk-by-chunk Sheet reader',
          'Granular OAuth security access scopes validator'
        ];
        moat = 'Granular read-only token restriction layer, blocking server-side prompt injection attacks from overriding active live documents.';
        bestUse = 'Enables Arslan Core to extract spreadsheet records and draft immediate automated briefs dynamically.';
        evaluatedType = 'MCP';
      } else if (query.includes('git') || query.includes('github')) {
        resultName = 'Git Workspace Controller';
        resultUrl = 'https://github.com/mcp-community/git-mcp';
        summary = 'Provides repository commit tree trace, atomic diff visualization, and auto-refactoring branches checkout tools directly within sandboxed workspace paths.';
        capabilities = [
          'Diff tree tracer with structural markdown preview',
          'Branch auto-protection rules lock',
          'Safe staged files cataloger with rollback memory'
        ];
        moat = 'Isolated file-system sandbox tracing, fully shielding the parent active operating system context from malicious checkout scripts.';
        bestUse = 'Enables Huan/Hatchery sub-agents to draft layout revisions and write commits post-evaluation.';
        evaluatedType = 'MCP';
      } else if (query.includes('brave') || query.includes('search') || query.includes('crawler') || query.includes('browser')) {
        resultName = 'Brave Search Intelligence Node';
        resultUrl = 'https://github.com/brave/brave-mcp-server';
        summary = 'A specialized web query engine optimized for agents, providing secure high-performance web crawls and selector-based text extraction.';
        capabilities = [
          'Auto-bypassing bot-detection web index fetcher',
          'Semantic HTML main text stripper layer',
          'Localized news variance trend aggregator'
        ];
        moat = 'Advanced rate-limit handling and residential proxy rotating built to secure uninterrupted indexing.';
        bestUse = 'Equips Aletheia with live financial news indexes across global web indices instantly.';
        evaluatedType = 'MCP';
      } else if (query.includes('milvus') || query.includes('vector') || query.includes('rag')) {
        resultName = 'Milvus Vector-Cache Connector';
        resultUrl = 'https://github.com/milvus-io/milvus-mcp-server';
        summary = 'A high-dimensional collection indexing node for storing long-term memory semantic layers securely and tracing cosine similarity vectors.';
        capabilities = [
          'Dynamic schema creator & metadata collection mapper',
          'Cosine similarity metric trace lookups',
          'RAG context payload optimizer'
        ];
        moat = 'Native cluster connection cache pools, reducing round-trip vector lookup hop latencies to less than 15ms.';
        bestUse = 'Enables Arslan Memory registers to store deep historic logs in fully searchable vector slots.';
        evaluatedType = 'MCP';
      } else if (query.includes('postgres') || query.includes('sql') || query.includes('mysql') || query.includes('database')) {
        resultName = 'Relational DB Smart Analyzer';
        resultUrl = urlOrQuery.startsWith('http') ? urlOrQuery : 'https://github.com/mcp-community/postgres-server';
        summary = 'Exposes database structure introspection, automated schema indexing, and analytical SQL tracer tools with secure execution limits.';
        capabilities = [
          'Automatic foreign-key trace mapper',
          'Bounded analytical DML analyzer & schema checker',
          'Transaction safety dry-run layer'
        ];
        moat = 'Active query limit capping and injection regex filtering, enabling safe read-only SQL generation for autonomous agents.';
        bestUse = 'Enables background spawns to perform automated statistics aggregation on dynamic database clusters.';
        evaluatedType = 'MCP';
      } else {
        let extractedName = 'Custom Repository Integration';
        const parts = query.replace('https://', '').replace('github.com/', '').split('/');
        if (parts.length > 1) {
          extractedName = parts[parts.length - 1].split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
        } else if (urlOrQuery) {
          extractedName = urlOrQuery.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
        }
        
        resultName = `${extractedName} Core`;
        summary = `A verified ${extractedName} capability module analyzed on-chain. Fully compatible with Arslan dual-plane orchestration constraints.`;
        capabilities = [
          `Introspective ${extractedName} API communication connector`,
          `Dynamic payload wrapper with schema-level validation`,
          `High-throughput error handling diagnostic protocol`
        ];
        moat = `Strict sandbox encapsulation blocks execution of arbitrary runtime buffers to shield the workspace.`;
        bestUse = `Enables Arslan Core to register ${extractedName} as an active specialty node on-demand.`;
        evaluatedType = query.includes('mcp') || query.includes('server') ? 'MCP' : 'Skill';
      }

      setEvaluationResult({
        url: resultUrl,
        name: resultName,
        summary,
        capabilities,
        moat,
        bestUse,
        type: evaluatedType
      });
      setIsEvaluating(false);
    }, 900);
  };

  const handleAddToMCP = () => {
    if (!evaluationResult) return;
    if (mcpRegistry.some(m => m.name === evaluationResult.name)) return;

    setMcpRegistry(prev => [
      ...prev,
      {
        name: evaluationResult.name,
        url: evaluationResult.url,
        description: evaluationResult.summary,
        tags: ['MCP', 'User Added']
      }
    ]);

    if (setThreads && activeThreadId) {
      const mcpMsg = {
        id: `mcp-add-${Date.now()}`,
        sender: 'arslan',
        senderName: 'Arslan Core',
        senderAvatar: '🦁',
        text: `📥 **MCP Registry Updated:** Successfully registered **[${evaluationResult.name}]** into the active sandbox tool container pool. It is now standard authorized (🔓).`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setThreads(prevThreads => prevThreads.map(t => {
        if (t.id === activeThreadId) {
          return { ...t, history: [...t.history, mcpMsg] };
        }
        return t;
      }));
    }
  };

  const handleAddToSkill = () => {
    if (!evaluationResult) return;
    if (skillRegistry.some(s => s.name === evaluationResult.name)) return;

    setSkillRegistry(prev => [
      ...prev,
      {
        name: evaluationResult.name,
        repo: evaluationResult.url,
        capabilities: evaluationResult.capabilities
      }
    ]);

    if (setThreads && activeThreadId) {
      const skillMsg = {
        id: `skill-add-${Date.now()}`,
        sender: 'arslan',
        senderName: 'Arslan Core',
        senderAvatar: '🦁',
        text: `🛡️ **Capabilities Ledger Expanded:** Added Skillset **[${evaluationResult.name}]** to specialized skill registers.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setThreads(prevThreads => prevThreads.map(t => {
        if (t.id === activeThreadId) {
          return { ...t, history: [...t.history, skillMsg] };
        }
        return t;
      }));
    }
  };

  const handleSynthesizeSpawn = () => {
    if (!evaluationResult) return;
    
    const newId = `spawn-new-${Date.now()}`;
    const nameStr = evaluationResult.name === 'Custom Repository Integration Core' 
      ? 'Arbitrage' 
      : evaluationResult.name.split(' ')[0] + ' Bot';

    const newSpawn: Spawn = {
      id: newId,
      name: nameStr,
      domain: `Integration Node: ${evaluationResult.name}`,
      description: evaluationResult.summary,
      status: 'idle',
      avatarEmoji: '⚡',
      tools: ['web-search'],
      skills: ['infographic-design'],
      totalTasks: 0
    };

    if (setSpawns) {
      setSpawns(prev => [...prev, newSpawn]);
    }

    if (setSpawnChats) {
      setSpawnChats(prev => ({
        ...prev,
        [newId]: [
          {
            id: `sc-init-${Date.now()}`,
            sender: 'spawn',
            senderName: nameStr,
            senderAvatar: '⚡',
            text: `🤖 **Direct specialist socket established via dynamically evaluated repository.**\nI am **${nameStr}**, synchronized with dynamic skill capabilities: [${evaluationResult.name}]. Send tasks to aggregate data!`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          }
        ]
      }));
    }

    if (setThreads && activeThreadId) {
      const synthMsg = {
        id: `synth-act-${Date.now()}`,
        sender: 'arslan',
        senderName: 'Arslan Core',
        senderAvatar: '🦁',
        text: `✨ **Gateway Synthesizer Handshake:** Dynamic specialist spawn successfully compiled and registered!\n\n**Specialist Name:** ${nameStr}\n**Active Skill:** ${evaluationResult.name}\n**Endpoint Hook:** *${evaluationResult.url}*.\n\nNow available in Spawns registry.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        spawnIntro: {
          name: nameStr,
          avatarEmoji: '⚡',
          domain: `Integration: ${evaluationResult.name}`,
          tools: ['web-search'],
          skills: ['infographic-design']
        }
      };

      setThreads(prevThreads => prevThreads.map(t => {
        if (t.id === activeThreadId) {
          return {
            ...t,
            history: [...t.history, synthMsg]
          };
        }
        return t;
      }));
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-[#0d0f15] p-8 select-none relative">
      {/* Decorative Top Lights */}
      {cardStyle === 'isometric' && (
        <div className="absolute top-0 right-1/4 w-[35rem] h-[35rem] bg-[#FF8E24]/[0.02] blur-[120px] rounded-full pointer-events-none"></div>
      )}

      {/* Header bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-8">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-white tracking-tight font-sans">Active Spawns Ledger</h1>
            <span className="text-[10px] bg-[#FF8E24]/10 text-[#FF8E24] border border-[#FF8E24]/20 font-mono font-semibold px-2 py-0.5 rounded-full uppercase">
              {spawns.length} Spawns
            </span>
          </div>
          <p className="text-xs text-gray-500 font-sans mt-1">
            Persistent micro-agents synthesized by the Arslan host core. Review status, run metrics, and equip tools.
          </p>
        </div>

        {/* Buttons right: Spawn Creator & Card Style Variator */}
        <div className="flex items-center gap-3 shrink-0 flex-wrap">
          {/* Card Style Switcher */}
          <div className="flex items-center border border-[#1e2330] p-0.5 rounded-lg bg-[#0e1118]">
            <span className="text-[9px] font-mono text-gray-500 uppercase px-2">Card Layout:</span>
            <button
              id="card-iso-btn"
              onClick={() => setCardStyle('isometric')}
              className={`px-2 py-1 rounded text-[10px] font-mono transition-all font-medium ${
                cardStyle === 'isometric'
                  ? 'bg-[#FF8E24]/10 text-[#FF8E24] border border-[#FF8E24]/30'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Glass Glow
            </button>
            <button
              id="card-blue-btn"
              onClick={() => setCardStyle('blueprint')}
              className={`px-2 py-1 rounded text-[10px] font-mono transition-all font-medium ${
                cardStyle === 'blueprint'
                  ? 'bg-orange-500 text-black font-bold border border-orange-500'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Blueprint
            </button>
            <button
              id="card-comp-btn"
              onClick={() => setCardStyle('compact')}
              className={`px-2 py-1 rounded text-[10px] font-mono transition-all font-medium ${
                cardStyle === 'compact'
                  ? 'bg-[#212630] text-white border border-[#3e4657]'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Pill Compact
            </button>
          </div>

          {/* Create spawn handler */}
          <button
            id="create-spawn-trigger"
            onClick={onCreateSpawnClick}
            className="px-3 py-1.5 bg-[#FF8E24] hover:bg-[#ff9c3a] text-black text-xs font-bold font-sans uppercase rounded-lg transition-all flex items-center gap-1 shadow-lg shadow-[#FF8E24]/15"
          >
            <span>+</span> Synthesize Spawn
          </button>
        </div>
      </div>

      {/* Global Integration Discovery & Repository Engine (Tool-Hub) */}
      <div className="bg-[#121622]/40 border border-[#23293a] rounded-2xl p-6 mb-8 transition-all z-10 select-text">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-[#FF8E24]/10 border border-[#FF8E24]/30 flex items-center justify-center text-sm transition-colors shadow-inner shadow-black/40">
              <Globe className="w-5 h-5 text-[#FF8E24] animate-spin" style={{ animationDuration: '8s' }} />
            </div>
            <div>
              <h3 className="font-sans font-bold text-sm text-white tracking-wide">
                Global Integration Discovery & Repository Engine <span className="text-gray-500 font-normal text-xs ml-1">(Tool-Hub / 全局工具集成发现与评估引擎)</span>
              </h3>
              <p className="text-[11.5px] text-gray-400 font-sans mt-0.5">
                Input public repository paths to dynamically analyze engineering defensive moats, check integration payload compliance, and instantiate customized spawns instantly.
              </p>
            </div>
          </div>
          
          <button
            onClick={() => setShowSandboxSearch(!showSandboxSearch)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-[#121622]/90 hover:bg-[#1e2330] text-gray-300 hover:text-white rounded-lg border border-[#23293a] transition-all cursor-pointer text-xs font-medium font-sans"
          >
            <span>{showSandboxSearch ? 'Collapse Tool Hub' : 'Expand Tool Hub'}</span>
            {showSandboxSearch ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>

        {showSandboxSearch && (
          <div className="mt-5 space-y-4 animate-fade-in border-t border-[#1e2330]/40 pt-4">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3.5 top-3 w-4 h-4 text-gray-500" />
                <input
                  type="text"
                  placeholder="Insert GitHub address or capability keyword (e.g., https://github.com/brave/brave-mcp-server)..."
                  value={integrationQuery}
                  onChange={(e) => setIntegrationQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleEvaluateRepository(integrationQuery);
                  }}
                  className="w-full bg-[#07090d] border border-[#23293a] focus:border-[#FF8E24]/60 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl pl-10 pr-4 py-2.5 text-xs text-white placeholder-gray-600 focus:outline-[#FF8E24]/50 transition-all font-sans"
                />
              </div>
              <button
                onClick={() => handleEvaluateRepository(integrationQuery)}
                disabled={isEvaluating}
                className="px-5 py-2.5 bg-[#FF8E24]/10 hover:bg-[#FF8E24] hover:text-black border border-[#FF8E24]/30 text-[#FF8E24] text-xs font-bold font-mono uppercase rounded-xl transition-all flex items-center gap-1 shrink-0 cursor-pointer disabled:opacity-50"
              >
                {isEvaluating ? (
                  <>
                    <RefreshCcw className="w-3.5 h-3.5 animate-spin" />
                    <span>Analyzing...</span>
                  </>
                ) : (
                  <>
                    <Cpu className="w-3.5 h-3.5" />
                    <span>Evaluate Spec</span>
                  </>
                )}
              </button>
            </div>

            {/* Quick Presets */}
            <div className="flex flex-wrap items-center gap-2 text-[10.5px] font-mono text-gray-500 select-none">
              <span className="text-gray-600">Quick Sandbox Presets:</span>
              <button 
                onClick={() => {
                  setIntegrationQuery('https://github.com/brave/brave-mcp-server');
                  handleEvaluateRepository('https://github.com/brave/brave-mcp-server');
                }}
                className="px-2 py-0.5 rounded bg-white/[0.02] border border-[#1e2330] hover:border-[#FF8E24]/50 hover:text-white transition-colors"
              >
                Brave-MCP
              </button>
              <button 
                onClick={() => {
                  setIntegrationQuery('https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive');
                  handleEvaluateRepository('https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive');
                }}
                className="px-2 py-0.5 rounded bg-white/[0.02] border border-[#1e2330] hover:border-[#FF8E24]/50 hover:text-white transition-colors"
              >
                GDrive-Workspace
              </button>
              <button 
                onClick={() => {
                  setIntegrationQuery('https://github.com/postgres-server');
                  handleEvaluateRepository('https://github.com/postgres-server');
                }}
                className="px-2 py-0.5 rounded bg-white/[0.02] border border-[#1e2330] hover:border-[#FF8E24]/50 hover:text-white transition-colors"
              >
                PostgreSQL-Analyzer
              </button>
              <button 
                onClick={() => {
                  setIntegrationQuery('https://github.com/milvus-io/milvus-mcp-server');
                  handleEvaluateRepository('https://github.com/milvus-io/milvus-mcp-server');
                }}
                className="px-2 py-0.5 rounded bg-white/[0.02] border border-[#1e2330] hover:border-[#FF8E24]/50 hover:text-white transition-colors"
              >
                Milvus-RAG
              </button>
            </div>

            {/* Scanning / Term State */}
            {isEvaluating && (
              <div className="bg-black/50 border border-orange-500/10 rounded-xl p-4 font-mono text-[10px] space-y-2 text-orange-500/70 animate-pulse">
                <p>≫ [SANDBOX CLONER ACTIVATED] Parsing source code layout structures...</p>
                <p>≫ Running abstract syntax trees audits for potential prompt vulnerability paths...</p>
                <p>≫ Matching core API endpoints configurations against active MCP specs...</p>
              </div>
            )}

            {/* Assessment result detail card */}
            {evaluationResult && (
              <div className="bg-[#0b0c13] border border-[#FF8E24]/15 rounded-xl p-5 space-y-4 animate-fade-in shadow-lg relative overflow-hidden">
                <div className="absolute top-0 right-0 px-2.5 py-1 bg-gradient-to-l from-[#FF8E24]/15 to-transparent border-bl border-[#FF8E24]/20 rounded-bl text-[9.5px] font-mono text-[#FF8E24] uppercase tracking-wider font-semibold">
                  Specification Assessment PASSED
                </div>

                <div className="flex items-start gap-3.5">
                  <div className="w-10 h-10 rounded-lg bg-orange-500/5 border border-[#FF8E24]/20 flex items-center justify-center text-[#FF8E24] shrink-0">
                    {evaluationResult.type === 'MCP' ? <Database className="w-5 h-5 animate-pulse" /> : <BookOpen className="w-5 h-5 animate-pulse" />}
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-bold text-white font-sans">{evaluationResult.name}</h4>
                      <span className="px-1.5 py-0.5 rounded text-[8.5px] font-mono font-bold uppercase tracking-wider bg-orange-950/40 border border-[#FF8E24]/30 text-[#FF8E24]">
                        {evaluationResult.type} Node
                      </span>
                    </div>
                    <p className="text-[10px] text-gray-500 font-mono truncate">{evaluationResult.url}</p>
                  </div>
                </div>

                {/* Grid analytics info */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-sans pb-3 border-b border-[#1e2330]/50 pt-1">
                  <div>
                    <span className="text-gray-500 block text-[10px] uppercase font-mono tracking-wider">Functional Summary</span>
                    <p className="text-gray-300 mt-1 leading-relaxed text-[11px]">{evaluationResult.summary}</p>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px] uppercase font-mono tracking-wider">🛠️ Core Capabilities</span>
                    <ul className="text-gray-300 mt-1 space-y-1 text-[11px] list-disc list-inside">
                      {evaluationResult.capabilities.map((cap, i) => (
                        <li key={i}>{cap}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px] uppercase font-mono tracking-wider">🛡️ Defensive Moats / 技术护城河</span>
                    <p className="text-gray-400 mt-1 leading-relaxed text-[11px] italic">{evaluationResult.moat}</p>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px] uppercase font-mono tracking-wider">🎯 Ideal Synergy Scenario / 协同场景</span>
                    <p className="text-gray-300 mt-1 leading-relaxed text-[11px]">{evaluationResult.bestUse}</p>
                  </div>
                </div>

                {/* Operations buttons bar */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-1 text-xs select-none">
                  <div className="flex items-center gap-2.5">
                    <button
                      onClick={handleAddToMCP}
                      className="px-3.5 py-2 bg-white/[0.02] border border-[#23293a] hover:border-emerald-500/30 hover:text-emerald-400 rounded-lg text-[11px] font-mono text-gray-300 transition-colors flex items-center gap-1.5 font-medium cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5 text-emerald-500" />
                      <span>{mcpRegistry.some(m => m.name === evaluationResult.name) ? '📥 Registered in Tool-Hub' : '📥 Add to MCP Registry / 注册到MCP库'}</span>
                    </button>
                    <button
                      onClick={handleAddToSkill}
                      className="px-3.5 py-2 bg-white/[0.02] border border-[#23293a] hover:border-blue-500/30 hover:text-blue-400 rounded-lg text-[11px] font-mono text-gray-300 transition-colors flex items-center gap-1.5 font-medium cursor-pointer"
                    >
                      <Shield className="w-3.5 h-3.5 text-blue-500" />
                      <span>{skillRegistry.some(s => s.name === evaluationResult.name) ? '🛡️ Skill Saved' : '🛡️ Add to Active Skills / 绑定到Skill库'}</span>
                    </button>
                  </div>

                  <button
                    onClick={handleSynthesizeSpawn}
                    className="px-4 py-2 bg-[#FF8E24] hover:bg-[#ff9c3a] text-black text-xs font-bold font-sans uppercase rounded-lg transition-all flex items-center gap-1.5 shadow-lg shadow-orange-500/10 cursor-pointer animate-pulse"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>One-click Spawn Synthesis / 一键复刻分身合成</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Spawns Grid Render */}
      {spawns.length === 0 ? (
        <div className="h-64 border border-dashed border-gray-800 rounded-2xl flex flex-col items-center justify-center text-center p-6 bg-black/10">
          <Cpu className="w-8 h-8 text-gray-600 mb-2 animate-bounce" />
          <h3 className="text-sm font-sans font-medium text-white">No active spawns active</h3>
          <p className="text-xs text-gray-500 max-w-sm mt-1">
            Create or instantiate micro-specialists to start delegating complex quantitative algorithms.
          </p>
        </div>
      ) : (
        <div className={`grid gap-6 ${cardStyle === 'compact' ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'}`}>
          {spawns.map(spawn => {
            
            // 1. ISOMETRIC GLASS GLOW CARD STYLE
            if (cardStyle === 'isometric') {
              const spawnLevel = Math.max(1, Math.floor(spawn.totalTasks / 10) + 1);
              return (
                <div
                  key={spawn.id}
                  onClick={() => setSelectedSpawnId(spawn.id)}
                  className={`bg-gradient-to-b from-[#121622]/90 to-[#0a0c12]/95 border border-[#23293b] hover:border-[#FF8E24]/40 rounded-2xl p-5 shadow-xl transition-all duration-300 hover:-translate-y-1 relative group cursor-pointer overflow-hidden`}
                >
                  {/* Neon pulsing glow outline */}
                  <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-[#FF8E24]/5 to-transparent blur-xl pointer-events-none group-hover:opacity-100 opacity-60 transition-opacity"></div>
                  
                  {/* Title Info Row */}
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3.5">
                      <div className="w-12 h-12 rounded-xl bg-[#1e2332]/60 border border-[#2c3349] group-hover:border-[#FF8E24]/40 flex items-center justify-center text-sm transition-colors shadow-inner shadow-black/40">
                        <SFSymbol nameOrEmoji={spawn.avatarEmoji} className="w-5 h-5 text-[#FF8E24]" />
                      </div>
                      <div>
                        <div className="flex items-center gap-1.5">
                          <h3 className="text-xs font-bold text-white font-sans tracking-wide group-hover:text-[#FF8E24] transition-colors">
                            {spawn.name}
                          </h3>
                        </div>
                        <p className="text-[10px] text-gray-400 font-mono uppercase tracking-wider mt-0.5">
                          {spawn.domain}
                        </p>
                      </div>
                    </div>

                    {/* Status Badge */}
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wider uppercase font-mono ${
                      spawn.status === 'working' 
                        ? 'bg-emerald-950/20 text-emerald-400 border border-emerald-950/40 animate-pulse'
                        : spawn.status === 'escalated'
                        ? 'bg-red-950/20 text-red-400 border border-red-950/40'
                        : 'bg-blue-950/20 text-blue-400 border border-blue-950/40'
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        spawn.status === 'working' 
                          ? 'bg-emerald-500' 
                          : spawn.status === 'escalated' 
                          ? 'bg-red-500' 
                          : 'bg-blue-500'
                      }`} />
                      {spawn.status}
                    </span>
                  </div>

                  {/* Spawn Description */}
                  <p className="text-xs text-gray-400 leading-relaxed font-sans mb-3 h-10 overflow-hidden line-clamp-2">
                    {spawn.description}
                  </p>



                  {/* Equipment Panel Indicator */}
                  <div className="space-y-3 pt-4 border-t border-[#1e2330]/50">
                    <div className="flex justify-between items-center text-[10px] font-mono text-gray-500 uppercase tracking-widest">
                      <span>Equipped systems</span>
                      <span className="text-gray-400 font-bold">
                        {spawn.tools.length + spawn.skills.length} item(s)
                      </span>
                    </div>

                    <div className="flex flex-wrap gap-1.5">
                      {spawn.tools.slice(0, 2).map(id => {
                        const meta = TOOLS.find(t => t.id === id);
                        return (
                          <span key={id} className="inline-flex items-center gap-1 text-[10px] font-mono bg-[#161a29] text-gray-300 px-2 py-0.5 rounded-md border border-[#232a3e]">
                            <span>🔧</span> {meta?.name || id}
                          </span>
                        );
                      })}
                      {spawn.skills.slice(0, 2).map(id => {
                        const meta = SKILLS.find(s => s.id === id);
                        return (
                          <span key={id} className="inline-flex items-center gap-1 text-[10px] font-mono bg-amber-950/10 text-amber-500 px-2 py-0.5 rounded-md border border-amber-950/30">
                            <span>📘</span> {meta?.name || id}
                          </span>
                        );
                      })}
                      {spawn.tools.length + spawn.skills.length > 4 && (
                        <span className="text-[10px] text-gray-500 font-mono px-1">
                          +{spawn.tools.length + spawn.skills.length - 4} more
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Card Bottom Panel / Hover actions */}
                  <div className="mt-5 flex items-center justify-between text-gray-500 group-hover:text-gray-300 transition-colors select-none">
                    <div className="flex items-center gap-3 text-[10px] font-mono">
                      <span className="flex items-center gap-1">
                        <Activity className="w-3.5 h-3.5 text-[#FF8E24]" />
                        {spawn.totalTasks} jobs compiled
                      </span>
                    </div>
                    
                    <button
                      id={`edit-equip-${spawn.id}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onEditEquipment(spawn.id);
                      }}
                      className="text-[10px] text-[#FF8E24] hover:text-white font-mono bg-[#FF8E24]/10 hover:bg-[#FF8E24] px-2.5 py-1 rounded transition-all border border-[#FF8E24]/20 uppercase font-semibold flex items-center gap-1"
                    >
                      <Sliders className="w-3 h-3" />
                      Configure
                    </button>
                  </div>
                </div>
              );
            }

            // 2. TECH BLUEPRINT GRID CARD STYLE (Monospace labels, high contrast, wireframe layout)
            if (cardStyle === 'blueprint') {
              const spawnLevel = Math.max(1, Math.floor(spawn.totalTasks / 10) + 1);
              return (
                <div
                  key={spawn.id}
                  onClick={() => setSelectedSpawnId(spawn.id)}
                  className="border-2 border-orange-500/60 p-4 font-mono text-[11px] bg-[#090b10] shadow-[3px_3px_0px_#FF8E24] hover:shadow-[5px_5px_0px_#FF8E24] transition-all relative cursor-pointer"
                >
                  <div className="absolute top-1 right-2 text-[9px] font-mono tracking-widest text-gray-600 uppercase">
                    Spawn-Ref: {spawn.id.slice(6, 11).toUpperCase()}
                  </div>

                  {/* Header info */}
                  <div className="pb-2 border-b border-dashed border-gray-800 mb-3 flex items-start gap-3">
                    <span className="inline-block p-1 bg-orange-950/25 border border-[#FF8E24]/20 rounded flex items-center justify-center">
                      <SFSymbol nameOrEmoji={spawn.avatarEmoji} className="w-4 h-4 text-[#FF8E24]" />
                    </span>
                    <div className="flex-1">
                      <div className="font-bold text-white text-[12px] hover:text-[#FF8E24] flex items-center justify-between">
                        <span>{spawn.name.toUpperCase()}</span>
                      </div>
                      <div className="text-[9px] text-orange-500 font-mono mt-0.5">
                        DOMAIN // {spawn.domain.toUpperCase()}
                      </div>
                    </div>
                  </div>

                  <p className="text-gray-400 leading-relaxed mb-3 text-[11px] h-8 overflow-hidden">
                    {spawn.description.toUpperCase()}
                  </p>



                  {/* Equipment checklist items */}
                  <div className="space-y-1.5 mb-4">
                    <div className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">
                      ≫ HARDWARE EQUIPMENT CHANCELLOR:
                    </div>
                    <div className="grid grid-cols-2 gap-1.5">
                      {spawn.tools.map(id => (
                        <div key={id} className="text-[10px] border border-gray-800 bg-black/40 p-1 text-gray-300">
                          ⚙️ {id.toUpperCase()}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-3 border-t border-gray-800 text-[10px]">
                    <span className="bg-orange-500 text-black px-1.5 font-bold">STATE: {spawn.status.toUpperCase()}</span>
                    
                    <button
                      id={`edit-equip-bp-${spawn.id}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onEditEquipment(spawn.id);
                      }}
                      className="text-white hover:text-[#FF8E24] border-l border-gray-800 pl-2 font-bold uppercase"
                    >
                      [ EDIT CHIPS ]
                    </button>
                  </div>
                </div>
              );
            }

            // 3. PILL COMPACT CARD STYLE (Ultra streamlined, expandable list view)
            if (cardStyle === 'compact') {
              const isSelected = selectedSpawnId === spawn.id;
              const spawnLevel = Math.max(1, Math.floor(spawn.totalTasks / 10) + 1);
              const progressPercent = (spawn.totalTasks % 10) * 10;
              const tasksToNextLevel = 10 - (spawn.totalTasks % 10);

              return (
                <div key={spawn.id} className="flex flex-col mb-2.5 select-none">
                  <div
                    onClick={() => setSelectedSpawnId(isSelected ? null : spawn.id)}
                    className={`bg-[#121520] hover:bg-[#161a29] border ${
                      isSelected ? 'border-[#FF8E24] bg-[#161a29]' : 'border-gray-800/60 hover:border-gray-700'
                    } rounded-xl p-3 px-4 flex flex-col sm:flex-row items-center justify-between gap-4 transition-all cursor-pointer`}
                  >
                    <div className="flex items-center gap-3 w-full sm:w-auto flex-1 min-w-0">
                      <span className="p-1.5 bg-[#1a1e2c] border border-gray-800 rounded-lg select-none shrink-0 flex items-center justify-center">
                        <SFSymbol nameOrEmoji={spawn.avatarEmoji} className="w-4 h-4 text-[#FF8E24]" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-bold text-white text-xs">{spawn.name}</span>
                          <span className="text-[9px] font-mono text-[#FF8E24] bg-[#FF8E24]/10 rounded border border-[#FF8E24]/20 px-1.5 py-0.2 select-none uppercase font-bold tracking-wider">{spawn.domain}</span>
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5 max-w-sm truncate">
                          {spawn.description}
                        </p>
                      </div>
                    </div>



                    {/* Equipment tags and action button */}
                    <div className="flex items-center gap-3.5 w-full sm:w-auto shrink-0 justify-end">
                      <div className="hidden md:flex flex-wrap items-center gap-2 text-[10px] text-gray-500 font-mono">
                        <span>🔧 {spawn.tools.length} tools</span>
                        <span>•</span>
                        <span>📘 {spawn.skills.length} skills</span>
                        <span>•</span>
                        <span className="text-emerald-400 font-bold uppercase tracking-wider select-none">● active</span>
                      </div>

                      <div className="text-gray-400 hover:text-white transition-colors">
                        {isSelected ? <ChevronUp className="w-4.5 h-4.5 text-[#FF8E24]" /> : <ChevronDown className="w-4.5 h-4.5" />}
                      </div>
                    </div>
                  </div>

                  {/* Expand-down panel content with glass animation */}
                  <AnimatePresence>
                    {isSelected && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.25, ease: 'easeInOut' }}
                        className="overflow-hidden"
                      >
                        <div className="mt-1.5 bg-gradient-to-r from-[#141824]/90 to-[#0a0c12]/95 border border-[#23293e]/90 rounded-xl p-5 shadow-2xl relative">
                          <div className="absolute inset-0 bg-[linear-gradient(to_right,#FF8E24_1px,transparent_1px)] bg-[size:16rem_16rem] opacity-[0.012] pointer-events-none rounded-xl" />
                          
                          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 relative z-10">
                            
                            {/* Summary profile */}
                            <div className="lg:col-span-4 space-y-4 border-b lg:border-b-0 lg:border-r border-[#1e2330]/60 pb-4 lg:pb-0 lg:pr-5 flex flex-col justify-between">
                              <div className="space-y-3">
                                <div>
                                  <span className="text-[9.5px] font-mono text-gray-500 uppercase tracking-widest block mb-1">Assigned Domain Profile</span>
                                  <span className="text-xs text-white font-bold block capitalize">{spawn.domain} Specialist</span>
                                </div>

                                <div>
                                  <div className="flex items-center justify-between mb-1">
                                    <span className="text-[9.5px] font-mono text-gray-500 uppercase tracking-widest block">Task Directive Scope</span>
                                  </div>
                                  <p className="text-xs text-gray-300 leading-relaxed font-sans">{spawn.description}</p>
                                </div>
                              </div>

                              {/* Telemetry Jobs stats */}
                              <div className="bg-black/30 border border-[#1e2330]/80 rounded-lg p-3 flex items-center justify-between mt-2">
                                <div className="space-y-0.5">
                                  <span className="text-[9px] font-mono text-gray-500 uppercase">Compiled Jobs Clocked</span>
                                  <div className="text-xs text-gray-400 font-mono flex items-center gap-1 mt-0.5">
                                    <Clock className="w-3" />
                                    <span>Latency: 14ms average</span>
                                  </div>
                                </div>
                                <div className="text-right">
                                  <div className="text-lg font-mono font-bold text-[#FF8E24] animate-pulse">
                                    {spawn.totalTasks} jobs
                                  </div>
                                  <span className="text-[8px] font-mono text-emerald-400 block uppercase font-bold">100% HEALTHY</span>
                                </div>
                              </div>
                            </div>

                            {/* Equipped Tools details */}
                            <div className="lg:col-span-4 space-y-3 border-b lg:border-b-0 lg:border-r border-[#1e2330]/60 pb-4 lg:pb-0 lg:pr-5">
                              <span className="text-[9.5px] font-mono text-gray-500 uppercase tracking-widest block font-bold">Equipped Standard Tools</span>
                              
                              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                                {spawn.tools.length === 0 ? (
                                  <div className="text-center py-4 bg-black/10 border border-dashed border-gray-800 rounded">
                                    <span className="text-[10px] text-gray-600 font-mono">NO ACTIVE TOOLS LOADED</span>
                                  </div>
                                ) : (
                                  spawn.tools.map(tId => {
                                    const tool = TOOLS.find(t => t.id === tId) || { name: tId, emoji: '🔧', description: 'Raw custom tool instruction.' };
                                    return (
                                      <div key={tId} className="flex items-start gap-2.5 p-2 bg-black/20 border border-white/[0.02] rounded-lg">
                                        <span className="text-xs p-1 bg-white/[0.03] border border-white/[0.04] rounded-md">{tool.emoji}</span>
                                        <div>
                                          <h4 className="text-[10.5px] font-bold text-white">{tool.name}</h4>
                                          <p className="text-[9.5px] text-gray-400 font-sans mt-0.5 leading-relaxed">{tool.description}</p>
                                        </div>
                                      </div>
                                    );
                                  })
                                )}
                              </div>
                            </div>

                            {/* Skills details */}
                            <div className="lg:col-span-4 space-y-3 flex flex-col justify-between">
                              <div className="space-y-3">
                                <span className="text-[9.5px] font-mono text-gray-500 uppercase tracking-widest block font-bold">Cognitive Soft Skills</span>
                                <div className="space-y-1.5 max-h-40 overflow-y-auto">
                                  {spawn.skills.length === 0 ? (
                                    <div className="text-center py-4 bg-black/10 border border-dashed border-gray-800 rounded">
                                      <span className="text-[10px] text-gray-600 font-mono font-medium">NO ACTIVE COGNITIVE SCHEMAS</span>
                                    </div>
                                  ) : (
                                    spawn.skills.map(sId => {
                                      const skill = SKILLS.find(s => s.id === sId) || { name: sId, emoji: '📘', description: 'Raw custom skill instruction context.' };
                                      return (
                                        <div key={sId} className="flex items-start gap-2.5 p-2 bg-black/20 border border-white/[0.02] rounded-lg">
                                          <span className="text-xs p-1 bg-amber-500/5 border border-amber-500/10 text-amber-500 rounded-md">{skill.emoji}</span>
                                          <div>
                                            <h4 className="text-[10.5px] font-bold text-amber-500">{skill.name}</h4>
                                            <p className="text-[9.5px] text-gray-400 font-sans mt-0.5 leading-relaxed">{skill.description}</p>
                                          </div>
                                        </div>
                                      );
                                    })
                                  )}
                                </div>
                              </div>

                              {/* Action buttons inside interactive tray */}
                              <div className="pt-3 border-t border-[#1e2330]/50 flex items-center justify-between gap-3">
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onOpenDirectChat?.(spawn.id);
                                  }}
                                  className="flex-1 py-1.5 px-3 bg-[#FF8E24] hover:bg-[#ff9c3a] text-black text-[10px] font-bold font-sans uppercase rounded-lg transition-all flex items-center justify-center gap-1.5 shadow-lg shadow-[#FF8E24]/10 cursor-pointer"
                                >
                                  <MessageSquare className="w-3.5 h-3.5" />
                                  <span>Open Channel</span>
                                </button>

                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onEditEquipment(spawn.id);
                                  }}
                                  className="py-1.5 px-3 bg-[#121520] hover:bg-white/[0.04] border border-[#1e2330] hover:border-gray-600 text-gray-400 hover:text-white text-[10px] font-mono uppercase rounded-lg transition-all flex items-center justify-center gap-1 cursor-pointer"
                                >
                                  <Sliders className="w-3.5 h-3.5" />
                                  <span>Calibrate</span>
                                </button>
                              </div>
                            </div>

                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              );
            }

            return null;
          })}
        </div>
      )}
    </div>
  );
}
