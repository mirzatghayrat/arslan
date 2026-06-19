import React, { useState, useEffect, useCallback } from 'react';
import { DEFAULT_SETTINGS } from './data';
import { Spawn, Message, AppSettings } from './types';
import { useSpawnStore } from './stores/spawnStore';
import { useArslanStore } from './stores/arslanStore';
import { api } from './api/client';
import { toUiSpawn, toUiSettings, toUiMessages } from './api/adapters';
import type { ArslanServerMessage, ProviderOption } from './api/client.types';
import { useWebSocket } from './hooks/useWebSocket';
import { useBackendStatus } from './hooks/useBackendStatus';
import Sidebar from './components/Sidebar';
import OrchestratorChat from './components/OrchestratorChat';
import SpawnDirectChat from './components/SpawnDirectChat';
import SpawnsDashboard from './components/SpawnsDashboard';
import SpawnEditor from './components/SpawnEditor';
import SettingsScreen from './components/SettingsScreen';
import { X, Sparkles, Cpu, Sliders, Layers, Terminal, ShieldAlert, Network, Wifi, Settings2, ChevronRight, ChevronLeft, Plus, Play, CheckCircle2, RefreshCcw, LayoutGrid, Paintbrush, Satellite, Wrench, Brain } from 'lucide-react';
import { getIcon } from './components/iconMap';
import SFSymbol from './components/SFSymbol';

interface ArslanThread {
  id: string;
  title: string;
  history: Message[];
  memberSpawnIds?: string[];
}

const toolDetails: Record<string, { name: string; emoji: string }> = {
  'web-search': { name: 'Web Search', emoji: '🔍' },
  'stock-data': { name: 'Stock Sandbox', emoji: '📈' },
  'py-exec': { name: 'PyExec Sandbox', emoji: '🐍' },
  'canvas-render': { name: 'SVGRenderer', emoji: '🎨' },
  'gmail-broker': { name: 'Gmail Broker', emoji: '📧' },
  'spanner-db': { name: 'Cloud Spanner', emoji: '🧱' },
};

const skillDetails: Record<string, { name: string; emoji: string }> = {
  'seo-opt': { name: 'SEO Copywriting', emoji: '✍️' },
  'financial-res': { name: 'Financial Research', emoji: '📊' },
  'infographic-design': { name: 'Infographic Layout', emoji: '📘' },
  'stat-analysis': { name: 'Statistical Forecasting', emoji: '📉' },
  'vuln-test': { name: 'Security Auditing', emoji: '🛡️' },
};

export default function App() {
  // Backend reachability — polled every 10s, drives honest offline states
  const backendStatus = useBackendStatus();

// Navigation Section: 'arslan' | 'spawn' | 'ledger' | 'settings'
  const [activeSection, setActiveSection] = useState<'arslan' | 'spawn' | 'ledger' | 'settings'>('arslan');
  const [panelView, setPanelView] = useState<'default' | 'editor'>('default');
  
  // Custom states for style variations (specifically asked in prompt)
  const [currentChatStyle, setCurrentChatStyle] = useState<'quartz' | 'brutalist' | 'linear'>('linear');
  const [currentCardStyle, setCurrentCardStyle] = useState<'isometric' | 'blueprint' | 'compact'>('compact');

  // Control Center Right Drawer Toggle state for redesigned grand layout frame
  const [showControlPanel, setShowControlPanel] = useState<boolean>(true);

  // ── Orchestrator threads — declared early so activeThreadId is available for
  // the WS hook below (hooks must be called in a consistent order).
  const [threads, setThreads] = useState<ArslanThread[]>([
    {
      id: "thread-default",
      title: "New Session",
      memberSpawnIds: [],
      history: []
    }
  ]);
  const [activeThreadId, setActiveThreadId] = useState<string>("thread-default");

  // ── Stage B: Orchestrator chat live WS ─────────────────────────────────────
  // The store holds all thread items; we derive UI messages from it.
  const arslanItems = useArslanStore((s) => s.items);
  const arslanStreaming = useArslanStore((s) => s.streaming);
  const arslanStreamingText = useArslanStore((s) => s.streamingText);

  // Handler for incoming WS frames — routes to the proven store logic
  const handleArslanFrame = useCallback((raw: unknown) => {
    useArslanStore.getState().handleFrame(raw as ArslanServerMessage);
  }, []);

  // Connect to the live orchestrator WebSocket using the active thread's id as
  // the conversation_id. useWebSocket reconnects automatically when the URL
  // changes (path is in its effect dep array), so switching threads reconnects.
  const { send: wsSend } = useWebSocket(`/ws/arslan/${activeThreadId}`, handleArslanFrame);

  // Derived UI messages from the live store
  const liveOrchestratorHistory: Message[] = toUiMessages(arslanItems);

  // Append an optimistic streaming bubble while a reply is streaming
  const orchestratorChatHistory: Message[] = arslanStreaming && arslanStreamingText
    ? [
        ...liveOrchestratorHistory,
        {
          id: '__streaming__',
          sender: 'arslan' as const,
          senderName: 'Arslan',
          senderAvatar: '🦁',
          text: arslanStreamingText,
          timestamp: '',
        },
      ]
    : liveOrchestratorHistory;

  // Send a user message to the live backend
  const sendOrchestratorMessage = useCallback((text: string) => {
    useArslanStore.getState().addUserMessage(text);
    wsSend({ type: 'user_message', content: text });
  }, [wsSend]);

  // Active direct private chats with individual Spawns — keyed by real backend spawn ID
  // Initialized empty; populated when user opens a direct channel or creates a spawn.
  const [spawnChats, setSpawnChats] = useState<Record<string, Message[]>>({});
  const [activeSpawnChatId, setActiveSpawnChatId] = useState<string>('');

  // Shared application state databases
  // Spawns Ledger: initialized empty; populated on mount from live spawn store (Stage B)
  const [spawns, setSpawns] = useState<Spawn[]>([]);
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);

  // Stage B: provider/search-provider catalogs for Settings dropdowns (live from backend)
  const [llmProviders, setLlmProviders] = useState<ProviderOption[]>([]);
  const [searchProviders, setSearchProviders] = useState<string[]>([]);

  // Stage B: wire Spawns Ledger and Settings to live backend on mount
  useEffect(() => {
    // Load spawns
    const store = useSpawnStore.getState();
    store.load().then(() => {
      const liveSpawns = useSpawnStore.getState().spawns.map(toUiSpawn);
      setSpawns(liveSpawns);
    });

    // Load settings from backend; merge into UI state, preserving UI-only fields
    api.getSettings().then((backendSettings) => {
      const mapped = toUiSettings(backendSettings);
      setSettings((prev) => ({ ...prev, ...mapped }));
    }).catch(() => {
      // backend unavailable — keep DEFAULT_SETTINGS
    });

    // Load LLM provider catalog
    api.listProviders().then(setLlmProviders).catch(() => {});

    // Load search provider catalog
    api.listSearchProviders().then(setSearchProviders).catch(() => {});
  }, []);
  const [selectedSpawnId, setSelectedSpawnId] = useState<string | null>(null);

  // New Spawn Creation modal/overlay state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showLedgerModal, setShowLedgerModal] = useState(false);
  const [ledgerSearch, setLedgerSearch] = useState('');
  const [newSpawnName, setNewSpawnName] = useState('');
  const [newSpawnEmoji, setNewSpawnEmoji] = useState('🦊');
  const [newSpawnDomain, setNewSpawnDomain] = useState('');
  const [newSpawnDescription, setNewSpawnDescription] = useState('');

  // Handle addition of a brand new Orchestrator thread context
  const handleAddArslanThread = () => {
    const threadId = `thread-${Date.now()}`;
    const nextThreadNumber = threads.filter(t => t.id !== 'thread-default' && !t.title.includes('New Session')).length + 1;
    const newThread: ArslanThread = {
      id: threadId,
      title: `Orchestration thread #${nextThreadNumber}`,
      memberSpawnIds: [],
      history: []
    };

    // Clear the store so the new conversation starts with empty history (the
    // backend will send an empty `history` frame for the new conversation_id).
    useArslanStore.getState().resetForNewConversation();
    setThreads(prev => [...prev, newThread]);
    setActiveThreadId(threadId);
    setActiveSection('arslan');
    setPanelView('default');
  };

  // Live updater that routes SetStateAction into the currently selected Arslan thread
  const setChatHistoryForActiveThread = (valueOrFn: React.SetStateAction<Message[]>) => {
    setThreads(prevThreads => {
      return prevThreads.map(t => {
        if (t.id === activeThreadId) {
          let newHistory: Message[];
          if (typeof valueOrFn === 'function') {
            newHistory = (valueOrFn as (prev: Message[]) => Message[])(t.history);
          } else {
            newHistory = valueOrFn;
          }

          // Rename thread if empty/default title when receiving first message from user
          let updatedTitle = t.title;
          if (t.title === 'New Session' || t.title.startsWith('Orchestration thread')) {
            const userMsg = newHistory.find(m => m.sender === 'user');
            if (userMsg) {
              const cleaned = userMsg.text.replace(/[#*`_]/g, '').trim();
              updatedTitle = cleaned.length > 22 ? cleaned.substring(0, 22) + '...' : cleaned;
            }
          }

          return { ...t, history: newHistory, title: updatedTitle };
        }
        return t;
      });
    });
  };

  // Live updater that routes SetStateAction into the direct Spawn chat histories
  const setSpawnChatHistoryForActiveSpawn = (valueOrFn: React.SetStateAction<Message[]>) => {
    setSpawnChats(prevChats => {
      const prevHistory = prevChats[activeSpawnChatId] || [];
      let newHistory: Message[];
      if (typeof valueOrFn === 'function') {
        newHistory = (valueOrFn as (prev: Message[]) => Message[])(prevHistory);
      } else {
        newHistory = valueOrFn;
      }
      return {
        ...prevChats,
        [activeSpawnChatId]: newHistory
      };
    });
  };

  // Handle opening Editor for a specific spawn
  const handleEditSpawnEquipment = (spawnId: string) => {
    setSelectedSpawnId(spawnId);
    setPanelView('editor');
    setActiveSection('ledger');
  };

  // Handle raw creation sequence
  const handleCreateSpawnSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSpawnName.trim() || !newSpawnDomain.trim()) return;

    const newSpawn: Spawn = {
      id: `spawn-new-${Date.now()}`,
      name: newSpawnName,
      domain: newSpawnDomain,
      description: newSpawnDescription || `Specialist AI micro-agent dedicated to high-integrity outcomes in ${newSpawnDomain}.`,
      status: 'idle',
      avatarEmoji: newSpawnEmoji,
      tools: ['web-search'], // Default equipped standard tools
      skills: ['infographic-design'], // Default standard skill
      totalTasks: 0
    };

    setSpawns(prev => [...prev, newSpawn]);
    
    // Add custom system message inside the active Arslan threads
    const systemNotif: Message = {
      id: `system-notif-${Date.now()}`,
      sender: 'arslan',
      senderName: 'Arslan',
      senderAvatar: '🦁',
      text: `⚡ **New Agent Synthesized Successfully:** Active slot allocated to **${newSpawn.name}** [${newSpawn.domain}]. Default standard equipment tools mapped to spawn scope. Custom configurations are editable inside the Spawns Ledger.`,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    
    setThreads(prevThreads => prevThreads.map(t => {
      if (t.id === activeThreadId) {
        return {
          ...t,
          history: [...t.history, systemNotif]
        };
      }
      return t;
    }));

    // Initialize private direct line conversations for this spawn
    setSpawnChats(prev => ({
      ...prev,
      [newSpawn.id]: [
        {
          id: `sc-init-${Date.now()}`,
          sender: 'spawn',
          senderName: newSpawn.name,
          senderAvatar: newSpawn.avatarEmoji,
          text: `🤖 **Direct specialist socket established.**\nI am **${newSpawn.name}**, newly delegated to handle high-integrity outcomes in **${newSpawn.domain}**. Give me a direct prompt!`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }
      ]
    }));

    // Cleanup and reset modal form
    setNewSpawnName('');
    setNewSpawnDomain('');
    setNewSpawnDescription('');
    setShowCreateModal(false);
    
    // Shift views to highlight the newly synthesized direct channel
    setActiveSpawnChatId(newSpawn.id);
    setActiveSection('spawn');
    setPanelView('default');
  };

  const handleToggleSpawnMembership = (spawnId: string) => {
    const spawn = spawns.find(s => s.id === spawnId);
    if (!spawn || !activeThread) return;

    const isMember = activeThread.memberSpawnIds?.includes(spawnId);

    if (isMember) {
      setThreads(prev => prev.map(t => {
        if (t.id === activeThreadId) {
          const nextMembers = (t.memberSpawnIds || []).filter(id => id !== spawnId);
          
          const leaveMsg: Message = {
            id: `msg-leave-${Date.now()}`,
            sender: 'arslan',
            senderName: 'Arslan Core',
            senderAvatar: '🦁',
            text: `🔌 **Pipeline Terminated:** **${spawn.name}** was disconnected and returned to the Spawns registry context pool.`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          };

          return {
            ...t,
            memberSpawnIds: nextMembers,
            history: [...t.history, leaveMsg]
          };
        }
        return t;
      }));
    } else {
      setThreads(prev => prev.map(t => {
        if (t.id === activeThreadId) {
          const nextMembers = [...(t.memberSpawnIds || []), spawnId];

          const joinMsg: Message = {
            id: `msg-join-${Date.now()}`,
            sender: 'spawn',
            senderName: spawn.name,
            senderAvatar: spawn.avatarEmoji,
            text: `👋 **Pipeline Integrated:** Active specialty socket initialized for **${spawn.name}**. I've synchronized into thread: *"${t.title}"*.\n\nReady to accept direct prompts or general multi-agent task distribution from the Arslan Core.`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            spawnIntro: {
              name: spawn.name,
              domain: spawn.domain,
              avatarEmoji: spawn.avatarEmoji,
              tools: spawn.tools,
              skills: spawn.tools
            }
          };

          return {
            ...t,
            memberSpawnIds: nextMembers,
            history: [...t.history, joinMsg]
          };
        }
        return t;
      }));
    }
  };

  // Calculate current active histories
  const activeThread = threads.find(t => t.id === activeThreadId) || threads[0];
  const activeSpawn = spawns.find(s => s.id === activeSpawnChatId) || spawns[0];
  const activeSpawnChatHistory = spawnChats[activeSpawnChatId] || [];

  // Compute capability registries for current dialog / context
  const getContextCapabilities = () => {
    let title = "Global Capability Sandbox";
    let activeMembers: Spawn[] = [];
    
    if (activeSection === 'arslan') {
      const currentThreadMembers = activeThread?.memberSpawnIds || [];
      activeMembers = spawns.filter((s) => currentThreadMembers.includes(s.id));
      title = `${activeThread?.title || "Active Thread"} Context`;
    } else if (activeSection === 'spawn') {
      const currentActiveSpawn = spawns.find((s) => s.id === activeSpawnChatId);
      if (currentActiveSpawn) {
        activeMembers = [currentActiveSpawn];
        title = `${currentActiveSpawn.name} Private Channel`;
      }
    } else {
      activeMembers = spawns;
      title = "All Loaded Spawns";
    }

    const toolsList = Array.from(new Set(activeMembers.flatMap((s) => s.tools)));
    const skillsList = Array.from(new Set(activeMembers.flatMap((s) => s.skills)));

    return {
      title,
      tools: toolsList,
      skills: skillsList,
      members: activeMembers
    };
  };

  const currentCaps = getContextCapabilities();
  // All orchestrator threads now use the live WS; history comes from the store.
  const isThreadEmpty = activeSection === 'arslan' && orchestratorChatHistory.length === 0;

  return (
    <div className={`flex w-screen h-screen bg-[#07090d] text-gray-100 overflow-hidden font-sans antialiased select-none ${settings.theme === 'light' ? 'light-theme' : ''}`}>
      
      {/* Sidebar with macOS window decorations & CPU load monitors */}
      <Sidebar
        threads={threads}
        activeThreadId={activeThreadId}
        onSelectThread={(id) => {
          // Reset store first so stale items from the previous conversation are
          // cleared before the new conversation_id's WS connects and sends its
          // `history` frame.
          useArslanStore.getState().resetForNewConversation();
          setActiveThreadId(id);
          setActiveSection('arslan');
          setPanelView('default');
        }}
        onAddThread={handleAddArslanThread}
        spawns={spawns}
        activeSpawnChatId={activeSpawnChatId}
        onSelectSpawnChat={(id) => {
          setActiveSpawnChatId(id);
          setActiveSection('spawn');
          setPanelView('default');
        }}
        activeSection={activeSection}
        onChangeSection={(section) => {
          setActiveSection(section);
          setPanelView('default');
        }}
        backendStatus={backendStatus}
      />

      {/* Main Workspace Frame container with glass window feel */}
      <main className="flex-1 flex flex-col h-full bg-[#0a0c10] relative">
      {/* Redesigned Grand Multi-column Frame layout */}
      <div className="flex-1 flex h-full relative">
        
        {/* Main Workspace Frame container */}
        <main className="flex-1 flex flex-col h-full bg-[#0a0c10] relative overflow-hidden">
          {/* Top Bar for overall macro layout */}
          <div className="h-14 border-b border-[#1e2330] px-6 flex items-center justify-between bg-[#0a0c10]/40 backdrop-blur-md z-30">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
              <span className="text-[10.5px] font-mono text-gray-400 capitalize uppercase tracking-wider">
                Active Session Workspace: <span className="text-white font-bold">
                  {activeSection === 'arslan' ? `Orchestrator Thread: ${activeThread.title}` : 
                   activeSection === 'spawn' ? `Specialist Stream: ${activeSpawn?.name || 'Direct Chat'}` : 
                   activeSection === 'ledger' ? 'Spawns Ledger Dashboard' : 'System Diagnostics Config'}
                </span>
              </span>
            </div>
            
            <div className="flex items-center gap-3">


              {/* Toggle Diagnostic Rail button */}
              {!isThreadEmpty && (
                <button
                  id="toggle-control-panel"
                  onClick={() => setShowControlPanel(!showControlPanel)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 border rounded-lg text-[10.5px] font-mono transition-all uppercase ${
                    showControlPanel 
                      ? 'border-[#FF8E24]/30 bg-[#FF8E24]/5 text-[#FF8E24] hover:bg-[#FF8E24]/10' 
                      : 'border-[#1e2330] text-gray-400 hover:text-white hover:bg-white/[0.02]'
                  }`}
                >
                  <Cpu className="w-3.5 h-3.5" />
                  <span>{showControlPanel ? "Hide Rail" : "Show Rail"}</span>
                </button>
              )}
            </div>
          </div>

          <div className="flex-1 flex flex-col overflow-hidden relative">
            {activeSection === 'arslan' && (
              <OrchestratorChat
                chatHistory={orchestratorChatHistory}
                setChatHistory={setChatHistoryForActiveThread}
                onSendMessage={sendOrchestratorMessage}
                spawns={spawns}
                currentStyle={currentChatStyle}
                setCurrentStyle={setCurrentChatStyle}
                activeThread={activeThread}
              />
            )}

            {activeSection === 'spawn' && activeSpawn && (
              <SpawnDirectChat
                spawn={activeSpawn}
                chatHistory={activeSpawnChatHistory}
                setChatHistory={setSpawnChatHistoryForActiveSpawn}
                currentStyle={currentChatStyle}
              />
            )}

            {activeSection === 'ledger' && panelView === 'default' && (
              <SpawnsDashboard
                spawns={spawns}
                selectedSpawnId={selectedSpawnId}
                setSelectedSpawnId={setSelectedSpawnId}
                cardStyle={currentCardStyle}
                setCardStyle={setCurrentCardStyle}
                onEditEquipment={handleEditSpawnEquipment}
                onCreateSpawnClick={() => setShowCreateModal(true)}
                onOpenDirectChat={(spawnId) => {
                  setActiveSpawnChatId(spawnId);
                  setActiveSection('spawn');
                  setPanelView('default');
                }}
                setSpawns={setSpawns}
                setThreads={setThreads}
                activeThreadId={activeThreadId}
                setSpawnChats={setSpawnChats}
                backendStatus={backendStatus}
              />
            )}

            {/* Dynamic Spawn Equipment Editor view */}
            {activeSection === 'ledger' && panelView === 'editor' && selectedSpawnId && (
              <SpawnEditor
                spawnId={selectedSpawnId}
                spawns={spawns}
                setSpawns={setSpawns}
                onBack={() => {
                  setPanelView('default');
                  setActiveSection('ledger');
                }}
              />
            )}

            {activeSection === 'settings' && (
              <SettingsScreen
                settings={settings}
                setSettings={setSettings}
                llmProviders={llmProviders}
                searchProviders={searchProviders}
                backendStatus={backendStatus}
              />
            )}
          </div>
        </main>

        {/* Collapsible Panel Section in Overall Layout Redesign */}
        {showControlPanel && !isThreadEmpty && (
          <aside className="w-80 border-l border-[#1e2330] bg-[#090b0f] flex flex-col justify-between h-full select-none relative z-20 animate-slide-in-right overflow-y-auto">
            {/* Top diagnostic state */}
            <div className="p-5 border-b border-[#1e2330]/50 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 bg-orange-500 rounded-full animate-ping"></span>
                  <span className="text-[10px] font-mono tracking-widest text-[#FF8E24] font-bold uppercase">Diagnostics Engine</span>
                </div>
                <button 
                  onClick={() => setShowControlPanel(false)}
                  className="text-gray-500 hover:text-white transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Ambient stats box */}
              <div className="bg-[#11141e]/50 border border-[#1e2330]/80 rounded-xl p-3.5 space-y-2 text-[11px] font-mono">
                <div className="flex justify-between">
                  <span className="text-gray-500">Routing Agent</span>
                  <span className="text-[#FF8E24]">Arslan Primary</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Model Deployment</span>
                  <span className="text-white lowercase bg-white/5 px-1 rounded">{settings.llmModel}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Active Slots</span>
                  <span className="text-white">{spawns.length} slots loaded</span>
                </div>
              </div>
            </div>

            {/* Active Workspace Capability Registries / MCP, Tools, Skills */}
            {currentCaps.members.length > 0 && (
              <div className="p-5 border-b border-[#1e2330]/50 space-y-4">
                <div className="flex items-center justify-between border-b border-[#1e2330]/30 pb-2">
                  <div className="flex items-center gap-1.5">
                    <Terminal className="w-3.5 h-3.5 text-[#FF8E24] animate-pulse" />
                    <span className="text-[10px] font-mono text-white uppercase tracking-wider font-bold">Dialogue Sandboxed Capabilities</span>
                  </div>
                  <span className="text-[8px] font-mono text-gray-400 uppercase tracking-widest bg-orange-500/10 text-[#FF8E24] border border-[#FF8E24]/20 px-1.5 py-0.5 rounded">
                    {activeSection === 'arslan' ? 'Thread-bound' : activeSection === 'spawn' ? 'Spawn-bound' : 'Global Pool'}
                  </span>
                </div>

                {/* Dynamic Focus Scope Header */}
                <div className="text-[9.5px] font-mono bg-[#11141e]/70 p-2 rounded-lg border border-[#1e2330]/50 space-y-1">
                  <span className="text-gray-500 text-[8px] uppercase tracking-wider block">Active Dialogue Scope</span>
                  <span className="font-bold text-[#FF8E24] block truncate">≫ {currentCaps.title}</span>
                </div>

                {/* 1. MCP (Model Context Protocol) Registry — no MCP backend yet */}
                <div className="space-y-1.5 opacity-50">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[9px] font-mono text-gray-500 uppercase tracking-wider font-bold flex items-center gap-1"><Satellite className="w-3 h-3" /> Registered Sandbox MCP Servers</span>
                    <span className="text-[8px] font-mono bg-gray-800/80 text-gray-500 border border-gray-700/50 px-1.5 py-0.2 rounded uppercase tracking-wider">即将推出</span>
                  </div>
                  <div className="bg-[#0b0d14]/60 border border-dashed border-[#1e2330]/60 rounded-lg px-3 py-2.5 text-[10px] font-mono text-gray-600 italic">
                    MCP server integration is not yet available. This section will list connected MCP servers once the backend supports them.
                  </div>
                </div>

                {/* 2. Equipped Agent Tools — only web-search is wired in backend; others coming soon */}
                <div className="space-y-1.5">
                  <span className="text-[9px] font-mono text-gray-500 uppercase tracking-wider font-bold block flex items-center gap-1"><Wrench className="w-3 h-3" /> Dialogue Tools</span>
                  {currentCaps.tools.length === 0 ? (
                    <p className="text-[9px] font-mono text-gray-600 italic">No tools linked inside dialogue scope.</p>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {currentCaps.tools.map((tId) => {
                        const details = toolDetails[tId] || { name: tId, emoji: '🔧' };
                        const isWired = tId === 'web-search';
                        return (
                          <div
                            key={tId}
                            className={`px-2 py-1 rounded text-[10px] font-mono flex items-center gap-1 select-none ${
                              isWired
                                ? 'bg-[#11141e] text-[#91b4ff] border border-[#232d4b]'
                                : 'bg-[#0e1018]/60 text-gray-600 border border-[#1e2330]/40 opacity-50'
                            }`}
                            title={isWired ? `Tool: ${tId}` : `${tId} — 即将推出 / Coming soon`}
                          >
                            {getIcon(tId, 'w-3 h-3')}
                            <span className="text-[10px] font-medium">{details.name}</span>
                            {!isWired && <span className="text-[7px] text-gray-600 font-mono ml-0.5">soon</span>}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* 3. Activated Skills — per-conversation skill tracking not yet available */}
                <div className="space-y-1.5">
                  <span className="text-[9px] font-mono text-gray-500 uppercase tracking-wider font-bold block flex items-center gap-1"><Brain className="w-3 h-3" /> Dialogue Skills</span>
                  {currentCaps.skills.length === 0 ? (
                    <p className="text-[9px] font-mono text-gray-600 italic">No skills linked inside dialogue scope.</p>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {currentCaps.skills.map((sId) => {
                        const details = skillDetails[sId] || { name: sId, emoji: '🎓' };
                        return (
                          <div
                            key={sId}
                            className="bg-[#0e1018]/60 text-gray-600 border border-[#1e2330]/40 opacity-50 px-2 py-1 rounded text-[10px] font-mono flex items-center gap-1 select-none"
                            title={`${sId} — 即将推出 / Coming soon (per-conversation skill tracking not yet available)`}
                          >
                            {getIcon(sId, 'w-3 h-3')}
                            <span className="text-[10px] font-medium">{details.name}</span>
                            <span className="text-[7px] text-gray-600 font-mono ml-0.5">soon</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Spawns Active Pool list */}
            <div className="p-5 flex-1 space-y-4 overflow-y-auto">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Network className="w-3.5 h-3.5 text-gray-500" />
                  <span className="text-[10px] font-mono text-white uppercase tracking-wider font-bold">Spawns Pipeline</span>
                </div>
                <button 
                  onClick={() => setShowLedgerModal(true)}
                  className="text-gray-500 hover:text-[#FF8E24] transition-colors p-1 bg-[#1e2330]/40 rounded hover:bg-black/40"
                  title="Invite Spawns to Thread"
                >
                  <Plus className="w-3.5 h-3.5" />
                </button>
              </div>

              <div className="space-y-2.5">
                {(() => {
                  const currentThreadMembers = activeThread?.memberSpawnIds || [];
                  const activeMembers = spawns.filter((s) => currentThreadMembers.includes(s.id));

                  if (activeMembers.length === 0) {
                    return (
                      <div className="text-center py-6 px-4 bg-[#0e111a]/40 border border-[#1e2330]/30 rounded-xl space-y-2.5 select-none">
                        <p className="text-[10px] font-mono text-gray-500 uppercase leading-normal">
                          No specialists invited to this thread group
                        </p>
                        <button
                          onClick={() => setShowLedgerModal(true)}
                          className="px-2.5 py-1 text-[9.5px] font-mono font-bold bg-[#FF8E24]/10 hover:bg-[#FF8E24]/20 border border-[#FF8E24]/30 text-[#FF8E24] rounded-lg transition-all uppercase"
                        >
                          + Invite Spawns
                        </button>
                      </div>
                    );
                  }

                  return activeMembers.map((spawn) => {
                    const spawnLevel = Math.max(1, Math.floor(spawn.totalTasks / 10) + 1);
                    const progressPercent = (spawn.totalTasks % 10) * 10;
                    return (
                      <div
                        key={spawn.id}
                        onClick={() => {
                          setSelectedSpawnId(spawn.id);
                          setPanelView('editor');
                          setActiveSection('ledger');
                        }}
                        className="p-2.5 bg-[#0e111a]/80 border border-[#1e2330]/50 hover:border-orange-500/30 rounded-xl transition-all cursor-pointer flex flex-col gap-2 group animate-fade-in"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <div>
                              <div className="text-[11px] font-medium text-white group-hover:text-[#FF8E24] transition-colors flex items-center gap-1.5">
                                <SFSymbol nameOrEmoji={spawn.avatarEmoji} className="w-3.5 h-3.5 text-[#FF8E24]" />
                                <span>{spawn.name}</span>
                                <span className="text-[8px] font-mono bg-[#FF8E24]/10 text-[#FF8E24] border border-[#FF8E24]/20 rounded px-1 font-bold">L.{spawnLevel}</span>
                              </div>
                              <div className="text-[9px] text-gray-500 font-mono mt-0.5 max-w-[140px] truncate">{spawn.domain}</div>
                            </div>
                          </div>

                          <div className="flex items-center gap-2">
                            <span className={`w-1.5 h-1.5 rounded-full ${
                              spawn.status === 'working' ? 'bg-amber-400 animate-pulse' : 'bg-emerald-400'
                            }`} />
                            <span className="text-[9px] font-mono text-gray-500 text-right uppercase">{spawn.status}</span>
                          </div>
                        </div>

                        {/* Level progress bar info segment */}
                        <div className="space-y-1">
                          <div className="flex justify-between items-center text-[7.5px] font-mono text-gray-500 uppercase tracking-wider">
                            <span>Level 進度</span>
                            <span className="text-[#FF8E24] font-bold">{progressPercent}%</span>
                          </div>
                          <div className="w-full bg-black/40 border border-[#1e2330]/30 h-[3px] rounded-full overflow-hidden">
                            <div 
                              className="bg-gradient-to-r from-amber-500 to-orange-500 h-full rounded-full transition-all duration-300"
                              style={{ width: `${Math.max(8, progressPercent)}%` }}
                            />
                          </div>
                        </div>
                      </div>
                    );
                  });
                })()}
              </div>
            </div>

            {/* Quick Actions diagnostic utilities footer */}
            <div className="p-4 bg-black/40 border-t border-[#1e2330]/60 space-y-2">
              <button 
                onClick={() => {
                  const diagnosticMsg: Message = {
                    id: `manual-audit-${Date.now()}`,
                    sender: 'arslan',
                    senderName: 'Arslan Core',
                    senderAvatar: '🦁',
                    text: `⚙️ **Manual Diagnostics Check completed:** All spawned memory registers are in high state capacity. Pipeline throughput clocks: **18 ms latency**. Style templates match: **${currentChatStyle}** (Chat) | **${currentCardStyle}** (Cards).`,
                    timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                  };
                  
                  // Append to active Arslan thread history
                  setThreads(prevThreads => prevThreads.map(t => {
                    if (t.id === activeThreadId) {
                      return {
                        ...t,
                        history: [...t.history, diagnosticMsg]
                      };
                    }
                    return t;
                  }));
                }}
                className="w-full py-2 bg-transparent hover:bg-white/[0.03] border border-[#1e2330] rounded-lg text-[10px] font-mono text-gray-400 hover:text-white transition-all flex items-center justify-center gap-1.5 uppercase font-bold"
              >
                <RefreshCcw className="w-3 h-3 text-orange-500/70" />
                <span>Verify Pipe Diagnostics</span>
              </button>
            </div>
          </aside>
        )}
      </div>
      </main>

      {/* Dynamic Spawn Creator Dialog Box overlay */}
      {showCreateModal && (
        <div id="create-spawn-modal" className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in">
          <div className="w-full max-w-lg bg-[#121622]/95 border border-[#23293a] rounded-2xl shadow-2xl overflow-hidden shadow-orange-950/20 select-none">
            
            {/* Header */}
            <div className="px-6 py-4 border-b border-[#1e2330]/80 flex items-center justify-between bg-[#0b0d14]">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4.5 h-4.5 text-[#FF8E24]" />
                <h3 className="text-xs font-bold font-mono text-white uppercase tracking-widest leading-none">Synthesize New Spawn specialist</h3>
              </div>
              <button 
                onClick={() => setShowCreateModal(false)}
                className="text-gray-400 hover:text-white transition-colors"
              >
                <X className="w-4.5 h-4.5" />
              </button>
            </div>

            {/* Form */}
            <form onSubmit={handleCreateSpawnSubmit} className="p-6 space-y-5">
              
              {/* Row: Name and Emoji Choice */}
              <div className="grid grid-cols-3 gap-4">
                <div className="col-span-2 space-y-1.5">
                  <label className="block text-[10px] font-mono text-gray-400 uppercase tracking-wider">Spawn Identifier</label>
                  <input
                    type="text"
                    required
                    value={newSpawnName}
                    placeholder="e.g., CrimsonWriter"
                    onChange={(e) => setNewSpawnName(e.target.value)}
                    className="w-full bg-[#0a0c10] border border-[#23293a] focus:border-[#FF8E24]/60 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-3.5 py-2.5 text-xs text-white placeholder-gray-600 focus:outline-none transition-all font-sans"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-mono text-gray-400 uppercase tracking-wider">Avatar Emoji</label>
                  <select
                    value={newSpawnEmoji}
                    onChange={(e) => setNewSpawnEmoji(e.target.value)}
                    className="w-full bg-[#0a0c10] border border-[#23293a] focus:border-[#FF8E24]/60 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-3.5 py-2.5 text-xs text-white focus:outline-none transition-all font-sans"
                  >
                    <option value="🦊">🦊 Fox</option>
                    <option value="🐱">🐱 Cat</option>
                    <option value="🐒">🐒 Monkey</option>
                    <option value="🦉">🦉 Owl</option>
                    <option value="🦁">🦁 Lion</option>
                    <option value="🤖">🤖 Bot</option>
                    <option value="🦄">🦄 Pegasus</option>
                  </select>
                </div>
              </div>

              {/* Input: Domain */}
              <div className="space-y-1.5">
                <label className="block text-[10px] font-mono text-gray-400 uppercase tracking-wider">Assigned Domain Field</label>
                <input
                  type="text"
                  required
                  value={newSpawnDomain}
                  placeholder="e.g., SEO Copywriting, Financial Valuations"
                  onChange={(e) => setNewSpawnDomain(e.target.value)}
                  className="w-full bg-[#0a0c10] border border-[#23293a] focus:border-[#FF8E24]/60 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-3.5 py-2.5 text-xs text-white placeholder-gray-600 focus:outline-none transition-all font-sans"
                />
              </div>

              {/* Input: Description */}
              <div className="space-y-1.5">
                <label className="block text-[10px] font-mono text-gray-400 uppercase tracking-wider">Domain Scope / Mission Description</label>
                <textarea
                  value={newSpawnDescription}
                  placeholder="Provide brief directives here defining the spawn core purpose..."
                  rows={3}
                  onChange={(e) => setNewSpawnDescription(e.target.value)}
                  className="w-full bg-[#0a0c10] border border-[#23293a] focus:border-[#FF8E24]/60 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-3.5 py-2.5 text-xs text-white placeholder-gray-600 focus:outline-none transition-all resize-none font-sans"
                />
              </div>

              {/* Footnote instruction info */}
              <div className="text-[10px] text-gray-500 font-mono leading-relaxed bg-[#0b0d14] p-3 border border-pink-950/20 rounded-xl">
                <span>Default standard capabilities 🔧 Web Search and 📘 Infographic Design are automatically mapped on initialization. Custom settings are editable in the spawn details page.</span>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#1e2330]/50 select-none">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-3.5 py-2 bg-transparent hover:bg-white/[0.03] rounded-lg text-xs font-sans font-medium text-gray-400 hover:text-white transition-all border border-transparent"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-[#FF8E24] hover:bg-[#ff9c3a] text-black text-xs font-bold font-sans uppercase rounded-lg transition-all flex items-center gap-1 shadow-lg shadow-[#FF8E24]/10"
                >
                  Confirm Synthesis
                </button>
              </div>

            </form>
          </div>
        </div>
      )}

      {/* Spawns Ledger Invitation Modal */}
      {showLedgerModal && (
        <div id="spawns-ledger-modal" className="fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in">
          <div className="w-full max-w-4xl h-[80vh] bg-[#121622]/95 border border-[#23293a] rounded-2xl shadow-2xl overflow-hidden shadow-orange-950/25 flex flex-col">
            
            {/* Header */}
            <div className="px-6 py-4.5 border-b border-[#1e2330]/80 flex items-center justify-between bg-[#0b0d14] shrink-0">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-orange-500/10 border border-orange-500/30 flex items-center justify-center">
                  <Network className="w-4 h-4 text-[#FF8E24]" />
                </div>
                <div>
                  <h3 className="text-xs font-bold font-mono text-white uppercase tracking-wider">Spawns Pipeline Ledger</h3>
                  <p className="text-[10px] text-gray-500 font-sans mt-0.5">Recruit and plug specialists into the active group chat.</p>
                </div>
              </div>
              <button 
                onClick={() => {
                  setShowLedgerModal(false);
                  setLedgerSearch('');
                }}
                className="text-gray-400 hover:text-white transition-colors p-1 bg-white/[0.02] border border-[#1e2330] rounded-lg"
              >
                <X className="w-4.5 h-4.5" />
              </button>
            </div>

            {/* Sub-header context banner */}
            <div className="px-6 py-3 bg-[#11141e]/50 border-b border-[#1e2330]/40 flex items-center justify-between text-[11px] font-mono select-none">
              <span className="text-gray-500">Active Chat:</span>
              <span className="text-orange-400 font-bold max-w-xs truncate">≫ {activeThread.title}</span>
            </div>

            {/* Local ledger search input section */}
            <div className="p-4 bg-[#0a0c10]/40 border-b border-[#1e2330]/40 shrink-0">
              <input
                type="text"
                value={ledgerSearch}
                onChange={(e) => setLedgerSearch(e.target.value)}
                placeholder="🔍 Search Spawns registry by domain specialty, identifier name, or capability description..."
                className="w-full bg-[#0a0c10] border border-[#23293a] focus:border-[#FF8E24]/60 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl px-4 py-3 text-xs text-white placeholder-gray-600 focus:outline-none transition-all font-sans"
              />
            </div>

            {/* Invite/kick backend is not yet implemented — actions disabled with coming-soon badge */}
            <div className="px-6 py-2 bg-amber-950/10 border-b border-amber-900/20 flex items-center gap-2 text-[10px] font-mono text-amber-600/80 shrink-0">
              <span>⚠</span>
              <span>Invite / kick not yet wired to backend — 即将推出 / Coming soon. Spawn list is real.</span>
            </div>

            {/* Scrollable list content */}
            <div className="flex-1 overflow-y-auto p-6 space-y-3.5">
              {(() => {
                const query = ledgerSearch.toLowerCase();
                const filtered = spawns.filter(s =>
                  s.name.toLowerCase().includes(query) ||
                  s.domain.toLowerCase().includes(query) ||
                  s.description.toLowerCase().includes(query)
                );

                if (filtered.length === 0) {
                  return (
                    <div className="text-center py-12 text-gray-400 font-mono text-xs select-none space-y-2">
                      <span className="block text-lg">⚠️</span>
                      <span className="text-gray-500">No matching specialist prototypes registered.</span>
                    </div>
                  );
                }

                return filtered.map((spawn) => {
                  const isMember = activeThread?.memberSpawnIds?.includes(spawn.id);
                  const spawnLevel = Math.max(1, Math.floor(spawn.totalTasks / 10) + 1);

                  return (
                    <div
                      key={spawn.id}
                      className="p-4 border rounded-xl border-[#1e2330]/60 bg-[#0e111a]/90 flex items-center justify-between gap-4 select-none"
                    >
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div className="space-y-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-white text-xs select-text">{spawn.avatarEmoji} {spawn.name}</span>
                            <span className="text-[8px] font-mono bg-black/40 text-gray-400 border border-gray-800 rounded-md px-1.5 py-0.2 select-none font-bold uppercase tracking-wider">L.{spawnLevel}</span>
                            <span className="text-[8px] font-mono bg-[#FF8E24]/10 text-[#FF8E24] border border-[#FF8E24]/15 rounded px-1.5 py-0.2 select-none font-bold uppercase tracking-wider">{spawn.domain}</span>
                          </div>
                          <p className="text-[11px] text-gray-400 leading-normal line-clamp-2 max-w-lg font-sans">
                            {spawn.description}
                          </p>
                          {/* Display Tools */}
                          <div className="flex items-center gap-1.5 pt-1">
                            {spawn.tools.map(toolId => (
                              <span key={toolId} className="text-[8px] font-mono text-gray-500 bg-[#0a0c10] border border-[#1e2330] px-1 py-0.2 rounded-md">
                                #{toolId}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* Invite/kick disabled — backend not yet available */}
                      <div
                        className="px-3 py-1.5 rounded-lg text-[10px] font-mono font-bold uppercase tracking-wider border border-[#1e2330]/60 bg-[#0b0d14]/60 text-gray-600 cursor-not-allowed opacity-50 shrink-0 flex items-center gap-1"
                        title="即将推出 / Coming soon — invite/kick backend not yet available"
                      >
                        {isMember ? (
                          <>
                            <span>✓ Listed</span>
                          </>
                        ) : (
                          <span>+ Pull Into Chat</span>
                        )}
                      </div>
                    </div>
                  );
                });
              })()}
            </div>

            {/* Footer containing synthetic action CTA */}
            <div className="p-4.5 bg-[#0b0d14] border-t border-[#1e2330]/85 flex items-center justify-between shrink-0">
              <button
                onClick={() => {
                  setShowLedgerModal(false);
                  setShowCreateModal(true);
                }}
                className="text-[10px] font-mono text-gray-400 hover:text-white flex items-center gap-1.5 uppercase tracking-wider px-3 py-1.5 bg-white/[0.01] border border-gray-800/80 rounded-lg hover:bg-white/[0.03] transition-all"
              >
                <Sparkles className="w-3.5 h-3.5 text-[#FF8E24] shrink-0" />
                <span>Synthesize new custom specialist</span>
              </button>
              <button
                onClick={() => {
                  setShowLedgerModal(false);
                  setLedgerSearch('');
                }}
                className="px-4 py-1.5 bg-[#1a1e2c] hover:bg-[#222739] text-gray-300 text-[10px] font-bold font-mono uppercase rounded-lg border border-[#2c3349]/50 transition-all select-none"
              >
                Close Ledger
              </button>
            </div>

          </div>
        </div>
      )}

    </div>
  );
}

