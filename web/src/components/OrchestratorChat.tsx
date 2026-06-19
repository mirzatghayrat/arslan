import React, { useState, useRef, useEffect } from 'react';
import {
  ArrowRight, Terminal, Wrench,
  AlertTriangle, CheckCircle2, XOctagon, Clock,
  Layers, CornerDownRight,
  Cpu, X, Send, ChevronDown,
  Plus, RefreshCcw
} from 'lucide-react';
import { getIcon } from './iconMap';
import { Message, Spawn, Tool, Skill } from '../types';
import { TOOLS, SKILLS } from '../data';
import SFSymbol from './SFSymbol';

interface OrchestratorChatProps {
  chatHistory: Message[];
  setChatHistory: React.Dispatch<React.SetStateAction<Message[]>>;
  /** When provided, user prompts are sent via this callback (live WS) instead of the mock simulation. */
  onSendMessage?: (text: string) => void;
  spawns: Spawn[];
  currentStyle: 'quartz' | 'brutalist' | 'linear';
  setCurrentStyle: (style: 'quartz' | 'brutalist' | 'linear') => void;
  activeThread: any;
}

export default function OrchestratorChat({
  chatHistory,
  setChatHistory,
  onSendMessage,
  spawns,
  currentStyle,
  setCurrentStyle,
  activeThread
}: OrchestratorChatProps) {
  const [inputValue, setInputValue] = useState('');
  const [collapsedToolActivities, setCollapsedToolActivities] = useState<Record<string, boolean>>({});
  
  // Custom states for Spawns Pipeline Dock & Split-Screen Co-pilot Sandbox
  const [spawnStatuses, setSpawnStatuses] = useState<Record<string, 'idle' | 'working' | 'review_pending'>>({});
  const [selectedAssignSpawnId, setSelectedAssignSpawnId] = useState<string | null>(null);
  const [assignTaskText, setAssignTaskText] = useState('');

  const [splitSpawnId, setSplitSpawnId] = useState<string | null>(null);
  // subInputValue, subChats, subDrafts, subTyping removed — sandbox not yet wired to backend

  // Global Integration Discovery & Repository Engine — no MCP backend yet; tool-hub disabled
  const [showSandboxSearch, setShowSandboxSearch] = useState(true);
  const [integrationQuery, setIntegrationQuery] = useState('');
  const isEvaluating = false; // evaluation backend not yet available
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [mcpRegistry] = useState<{name: string, url: string, description: string, tags: string[]}[]>([]); // no real MCP servers yet
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [skillRegistry] = useState<{name: string, repo: string, capabilities: string[]}[]>([]);
  const evaluationResult = null;

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  // Tool-Hub evaluation is disabled — no MCP/discovery backend exists yet.
  // Tool-Hub evaluation handlers are disabled — no MCP/discovery backend exists yet.
  const handleEvaluateRepository = (_urlOrQuery: string) => { /* coming soon */ };
  const handleAddToMCP = () => { /* coming soon */ };
  const handleAddToSkill = () => { /* coming soon */ };
  const handleSynthesizeSpawn = () => { /* coming soon */ };

  // Sandbox per-spawn orchestration is not yet wired to a real backend frame.
  // Opening the sandbox panel just shows the coming-soon placeholder.
  const handleLaunchSpawnTask = (_spawnId: string, _customTask?: string) => {
    setSelectedAssignSpawnId(null);
    setAssignTaskText('');
    // Do not fabricate messages or tool runs — sandbox dispatch coming soon.
  };

  // Sandbox sub-chat and draft refinement are not yet wired to a real backend frame.
  // These handlers are stubs — no fake messages are injected.
  const handleSendSubMessage = (e: React.FormEvent) => {
    e.preventDefault();
    // coming soon — no fabricated spawn replies
  };

  const handleConfirmMergeDraft = (_spawnId: string) => {
    // coming soon — no fabricated merge output
    setSplitSpawnId(null);
  };

  const handleDiscardSubSession = (spawnId: string) => {
    setSpawnStatuses(prev => ({ ...prev, [spawnId]: 'idle' }));
    setSplitSpawnId(null);
  };

  const toggleToolCollapse = (id: string) => {
    setCollapsedToolActivities(prev => ({
      ...prev,
      [id]: !prev[id]
    }));
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim()) return;

    const text = inputValue.trim();
    setInputValue('');

    if (onSendMessage) {
      // Live WS path: delegate to parent's onSendMessage (store + WS send)
      onSendMessage(text);
      return;
    }

    // Non-wired thread: append the user message only; no fabricated assistant reply.
    const userMsg: Message = {
      id: `msg-user-${Date.now()}`,
      sender: 'user',
      senderName: 'Mirzat',
      senderAvatar: '🦁',
      text,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    setChatHistory(prev => [...prev, userMsg]);
  };

  // triggerPresetScenario and execSteps removed — preset buttons now pre-fill
  // the input box instead of auto-playing fabricated orchestration sequences.

  return (
    <div className="flex-1 flex flex-col h-full bg-[#0d0f15] relative overflow-hidden">
      {/* Absolute Ambient Background Lights for Quartz Theme */}
      {currentStyle === 'quartz' && (
        <>
          <div className="absolute top-1/4 left-1/3 w-[30rem] h-[30rem] bg-[#FF8E24]/5 blur-[120px] rounded-full pointer-events-none -translate-x-1/2 -translate-y-1/2"></div>
          <div className="absolute bottom-1/4 right-0 w-[40rem] h-[40rem] bg-amber-600/[0.03] blur-[150px] rounded-full pointer-events-none translate-x-1/3 translate-y-1/3"></div>
        </>
      )}



      {/* Simulator Interactive Control Strip & Spawns Docket Integrated */}
      <div className="bg-[#121622]/60 border-b border-[#1e2330]/80 px-6 py-2.5 flex flex-row items-center justify-between gap-4 select-none text-[11px] z-10">
        <div className="flex items-center gap-2 shrink-0">
          <Terminal className="w-4 h-4 text-amber-500" />
          <span className="text-gray-300 font-mono font-bold uppercase tracking-wider">Interactive Spawner Sandbox:</span>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {(() => {
            const currentThreadMembers = activeThread?.memberSpawnIds || [];
            const memberSpawns = spawns.filter(s => currentThreadMembers.includes(s.id));
            
            // Show only thread members; no fallback to mock names
            const activeDisplayList = memberSpawns;

            return activeDisplayList.map(spawn => {
              const status = spawnStatuses[spawn.id] || 'idle';
              const isWorking = status === 'working';
              const isReviewPending = status === 'review_pending';
              const isSplitActive = splitSpawnId === spawn.id;

              // Determine status indicator animation to place in front of spawn name
              let statusIndicator = null;
              if (isWorking) {
                // Active running indicator
                statusIndicator = (
                  <span className="relative flex h-2 w-2 mr-1">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
                  </span>
                );
              } else if (isReviewPending) {
                // High-energy blinking alert indicator requesting action
                statusIndicator = (
                  <span className="relative flex h-2 w-2 mr-1">
                    <span className="animate-pulse absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-80 scale-125"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-rose-500 animate-ping"></span>
                  </span>
                );
              } else {
                // Normal quiet breathing green indicator for ready/idle
                statusIndicator = (
                  <span className="relative flex h-1.5 w-1.5 mr-1">
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500/80"></span>
                  </span>
                );
              }

              return (
                <button
                  key={spawn.id}
                  onClick={() => {
                    if (splitSpawnId === spawn.id) {
                      setSplitSpawnId(null);
                    } else {
                      setSplitSpawnId(spawn.id);
                      if (status === 'idle') {
                        handleLaunchSpawnTask(spawn.id);
                      }
                    }
                  }}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-all text-xs font-semibold select-none cursor-pointer ${
                    isReviewPending 
                      ? 'border-rose-500/60 bg-rose-950/15 text-rose-300 hover:border-rose-400 shadow-md shadow-rose-500/5 animate-pulse' 
                      : isWorking
                      ? 'border-amber-500/30 bg-amber-500/5 text-amber-500/80 hover:border-amber-500/60'
                      : isSplitActive
                      ? 'border-[#FF8E24] bg-[#FF8E24]/10 text-[#FF8E24]'
                      : 'border-[#1e2330] bg-[#121622]/40 hover:border-[#3a4460] text-gray-300 hover:text-white'
                  }`}
                  title={
                    isReviewPending 
                      ? 'Action Required - Click to confirm or adjust work' 
                      : isWorking 
                      ? `${spawn.name} is working... Click to view live buffer` 
                      : `Click to toggle split-dialog and trigger ${spawn.name}`
                  }
                >
                  {statusIndicator}
                  <span>{spawn.name}</span>
                </button>
              );
            });
          })()}
        </div>
      </div>

      {/* Global Integration Discovery & Repository Engine (Tool-Hub) has been successfully relocated to the Spawns Ledger screen directly above the Spawns list card grid. */}

      {/* Main Container: Split-screen dual workframes if splitSpawnId is assigned */}
      <div className="flex-1 flex overflow-hidden relative">
        <div className={`flex-1 flex flex-col h-full overflow-hidden transition-all duration-300 relative ${
          splitSpawnId ? 'w-[55%] border-r border-[#1e2330]' : 'w-full'
        }`}>
          {/* Scrollable Chat Area */}
          <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {chatHistory.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-2xl mx-auto py-10 px-4 space-y-8 select-none">
            {/* Greeting Header inspired by Claude's elegant style */}
            <div className="space-y-3 animate-fade-in">
              <div className="flex items-center justify-center gap-3">
                {/* Custom sunburst flower symbol / asterisk resembling Claude's */}
                <svg className="w-10 h-10 text-orange-400/90 animate-pulse" viewBox="0 0 100 100" fill="currentColor">
                  {[0, 45, 90, 135, 180, 225, 270, 315].map((angle) => (
                    <rect
                      key={angle}
                      x="46"
                      y="14"
                      width="8"
                      height="72"
                      rx="4"
                      transform={`rotate(${angle} 50 50)`}
                      className="origin-center text-[#FF8E24]"
                    />
                  ))}
                  <circle cx="50" cy="50" r="14" className="text-amber-500" />
                </svg>

                {/* Elegant serif-style greeting */}
                <h1 className="text-3xl sm:text-4.5xl font-serif text-[#ffd3a6] tracking-tight font-medium leading-none">
                  {(() => {
                    const hr = new Date().getHours();
                    if (hr < 12) return 'Morning';
                    if (hr < 18) return 'Afternoon';
                    return 'Evening';
                  })()}, Mirzat
                </h1>
              </div>
            </div>

            {/* Luxurious prompt input box resembling Claude's container design */}
            <div className="w-full max-w-xl bg-[#121520] border border-[#23293e] rounded-2xl p-4 flex flex-col space-y-3 focus-within:border-[#FF8E24]/60 focus-within:ring-1 focus-within:ring-[#FF8E24]/30 shadow-2xl transition-all">
              <textarea
                id="landing-message-input"
                rows={3}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    if (inputValue.trim()) {
                      handleSendMessage(e);
                    }
                  }
                }}
                placeholder="Paste a document, an email, or a task description to orchestrate..."
                className="w-full bg-transparent text-sm text-white placeholder-gray-500 focus:outline-none resize-none px-2 pt-1 font-sans leading-relaxed min-h-[55px]"
              />

              {/* Action options row */}
              <div className="flex items-center justify-between pt-2 border-t border-[#1e2330]/50 select-none">
                <button 
                  type="button" 
                  onClick={() => alert("Local datasets & specialized credentials mounted securely inside workspace.")} 
                  className="p-1.5 text-gray-500 hover:text-gray-300 hover:bg-white/[0.03] rounded-lg transition-all"
                  title="Attach workspace documents or source context"
                >
                  <Plus className="w-4.5 h-4.5 text-gray-500" />
                </button>

                <div className="flex items-center gap-2">
                  {/* Model Choice indicator */}
                  <div className="flex items-center gap-1 bg-black/40 hover:bg-black/60 px-2.5 py-1 rounded-full border border-gray-800 text-[10px] font-mono text-gray-400 hover:text-gray-200 cursor-pointer transition-colors max-w-[130px] sm:max-w-none truncate">
                    <Cpu className="w-3 h-3 text-[#FF8E24]" />
                    <span className="ml-0.5">Arslan v4.8 High</span>
                    <ChevronDown className="w-3 h-3 text-gray-500" />
                  </div>

                  {/* Micro icon */}
                  <button type="button" className="p-1 text-gray-500 hover:text-gray-300" title="Audio transcription input">
                    <svg className="w-4 h-4 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                      <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 19v4M8 23h8" />
                    </svg>
                  </button>

                  {/* Wave icon */}
                  <button type="button" className="p-1 text-gray-500 hover:text-gray-300" title="Simulated audio feedback channel">
                    <svg className="w-4 h-4 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M3 10v4M6 6v12M9 11v2M12 4v16M15 8v8M18 11v2M21 10v4" />
                    </svg>
                  </button>

                  <button
                    type="button"
                    disabled={!inputValue.trim()}
                    onClick={(e) => {
                      if (inputValue.trim()) {
                        handleSendMessage(e);
                      }
                    }}
                    className="p-1.5 bg-[#FF8E24] hover:bg-[#ff9c3a] disabled:bg-gray-800/80 disabled:text-gray-600 text-black rounded-lg transition-all flex items-center justify-center ml-1"
                  >
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>

            {/* Quick action pill suggestions inspired by Claude suggestions */}
            <div className="w-full max-w-xl text-center space-y-2">
              <span className="text-[10px] font-mono text-gray-600 uppercase tracking-widest block">Start Orchestrating presets</span>
              <div className="flex flex-wrap gap-1.5 justify-center">
                {[
                  { label: "✏️ Code Audit", prompt: "Conduct automatic code analysis on sandbox files to discover vulnerability patterns." },
                  { label: "🎓 Financial Brief", prompt: "Summarize Q1 market ratings and consensus predictions for Blackwell chipsets output." },
                  { label: "💻 Slogan Synthesis", prompt: "Draft optimized copywriting hooks for key promotional tech campaigns with emojis." },
                  { label: "🔍 Drive Fetcher", prompt: "Use Brave registry crawler tool to catalog recent AI deployment metrics." }
                ].map((item, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      setInputValue(item.prompt);
                      document.getElementById('landing-message-input')?.focus();
                    }}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-[#121622]/60 hover:bg-[#1f253b] border border-[#1e2330]/80 rounded-full text-[11px] text-gray-400 hover:text-white transition-all cursor-pointer select-none font-sans"
                  >
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          chatHistory.map((msg, index) => {
            const isUser = msg.sender === 'user';
            const isArslan = msg.sender === 'arslan';
            const isSpawn = msg.sender === 'spawn';

            // Quartz Theme Rendering
            if (currentStyle === 'quartz') {
              return (
                <div 
                  key={msg.id} 
                  className={`flex gap-4 ${isUser ? 'justify-end' : ''}`}
                >
                  {/* Avatar left (for system) */}
                  {!isUser && (
                    <div className="flex flex-col items-center select-none">
                      <div className={`w-9 h-9 rounded-xl flex items-center justify-center text-sm font-sans relative ${
                        isArslan
                          ? 'bg-gradient-to-tr from-[#FF8E24] to-yellow-500 text-white shadow-lg shadow-[#FF8E24]/15'
                          : 'bg-[#1a1e2a] border border-[#ff8e24]/30 text-white'
                      }`}>
                        <SFSymbol nameOrEmoji={msg.senderAvatar} className="w-4 h-4 text-white" />
                        <span className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-black ${
                          isArslan ? 'bg-emerald-500' : 'bg-[#FF8E24]'
                        }`} />
                      </div>
                      <span className="text-[9px] text-gray-500 font-mono mt-1 font-semibold">{msg.timestamp}</span>
                    </div>
                  )}

                  {/* Message Bubble */}
                  <div className={`max-w-2xl space-y-3 ${isUser ? 'order-1' : ''}`}>
                    {/* Sender label name */}
                    {!isUser && (
                      <div className="flex items-center gap-1.5 select-none">
                        <span className="text-[11px] font-semibold text-gray-300">{msg.senderName}</span>
                        {isArslan ? (
                          <span className="text-[9px] bg-[#FF8E24]/10 text-[#FF8E24] border border-[#FF8E24]/30 px-1.5 py-0.2 rounded font-semibold font-mono uppercase tracking-wider scale-95">
                            Orchestrator
                          </span>
                        ) : (
                          <div className="flex items-center gap-1 scale-95">
                            <span className="text-[9px] bg-amber-500/10 text-amber-500 border border-amber-500/20 px-1.5 py-0.2 rounded font-mono uppercase tracking-wider font-semibold">
                              Spawn Core
                            </span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Styled Bubble Body */}
                    <div className={`px-4 py-3 rounded-2xl border text-[12.5px] leading-relaxed relative ${
                      isUser
                        ? 'bg-gradient-to-br from-[#FF8E24] to-amber-600 border-[#ffaa45]/50 text-white shadow-md shadow-[#FF8E24]/10 rounded-tr-none'
                        : isArslan
                        ? 'bg-[#151924]/80 backdrop-blur border-[#23293b] text-gray-100 rounded-tl-none shadow-sm shadow-black/40'
                        : 'bg-[#11141d]/90 backdrop-blur border-[#ff8e24]/15 text-gray-200 rounded-tl-none'
                    }`}>
                      {/* Message Content */}
                      <p className="whitespace-pre-line font-sans leading-relaxed">{msg.text}</p>

                      {/* Routed Indicator - specifically asked in prompt */}
                      {msg.routedTo && (
                        <div className="mt-3.5 pt-3 border-t border-[#1e2330]/50 flex items-center gap-2.5 text-[11px] font-mono bg-[#141824]/50 p-2 rounded-lg border border-[#232a3e]">
                          <div className="w-2 h-2 rounded-full bg-[#FF8E24] animate-ping" />
                          <div className="flex items-center gap-1 text-gray-400">
                            <span>Workflow context routed to</span>
                            <span className="text-[#FF8E24] font-semibold flex items-center gap-0.5">
                              <CornerDownRight className="w-3 h-3 inline-block" />
                              {msg.routedTo.spawnName}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* 1. Spawn Intro Card Sub-Component (specifically asked in prompt) */}
                    {msg.spawnIntro && (
                      <div className="bg-gradient-to-b from-[#131722]/90 to-[#0e111a]/95 border border-[#FF8E24]/30 rounded-2xl p-4 shadow-xl shadow-[#FF8E24]/5 space-y-3.5 relative overflow-hidden group">
                        {/* Decorative background glow for card */}
                        <div className="absolute top-0 right-0 w-24 h-24 bg-[#FF8E24]/5 blur-xl group-hover:bg-[#FF8E24]/10 transition-all rounded-full pointer-events-none"></div>
                        
                        <div className="flex items-start gap-3.5">
                          <div className="w-11 h-11 rounded-xl bg-orange-950/25 border border-[#FF8E24]/30 flex items-center justify-center text-xl shadow-inner shadow-[#FF8E24]/10">
                            <SFSymbol nameOrEmoji={msg.spawnIntro.avatarEmoji} className="w-6 h-6" />
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <h4 className="text-xs font-bold text-white font-sans">{msg.spawnIntro.name}</h4>
                              <span className="text-[9px] bg-[#FF8E24]/15 text-[#FF8E24] font-mono px-1.5 py-0.5 rounded font-bold uppercase tracking-widest border border-[#FF8E24]/10">Introduced</span>
                            </div>
                            <p className="text-[10px] text-gray-400 font-mono mt-0.5">{msg.spawnIntro.domain}</p>
                          </div>
                        </div>

                        {/* Equipped Capabilities Rendering */}
                        <div className="space-y-2">
                          <div className="text-[10px] text-gray-500 font-mono font-medium tracking-wide uppercase">Equipped Capabilities:</div>
                          <div className="flex flex-wrap gap-1.5">
                            {/* Render Tool tags with lucide icon */}
                            {msg.spawnIntro.tools.map(toolId => {
                              const toolMeta = TOOLS.find(t => t.id === toolId);
                              return (
                                <span
                                  key={toolId}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-mono bg-[#161a29] text-gray-300 px-2 py-0.8 rounded-lg border border-[#232a3e] hover:border-[#FF8E24]/30 transition-all hover:text-white"
                                >
                                  {getIcon(toolId, 'w-3 h-3')}
                                  <span className="font-semibold">{toolMeta?.name || toolId}</span>
                                </span>
                              );
                            })}
                            {/* Render Skill tags with lucide icon */}
                            {msg.spawnIntro.skills.map(skillId => {
                              const skillMeta = SKILLS.find(s => s.id === skillId);
                              return (
                                <span
                                  key={skillId}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-mono bg-amber-950/10 text-amber-500 px-2 py-0.8 rounded-lg border border-amber-950/40 hover:border-amber-500/30 transition-all"
                                >
                                  {getIcon(skillId, 'w-3 h-3')}
                                  <span className="font-semibold">{skillMeta?.name || skillId}</span>
                                </span>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* 2. Tool-Activity Frame Sub-Component (specifically asked in prompt) */}
                    {msg.toolActivity && (
                      <div className="bg-[#121622] border border-[#232a3f] rounded-2xl shadow-lg shadow-black/30 overflow-hidden text-[11px] font-sans">
                        {/* Header bar */}
                        <div className="bg-[#0b0d14] px-4 py-2.5 flex items-center justify-between border-b border-[#1e2436] select-none">
                          <div className="flex items-center gap-2">
                            <RefreshCcw className="animate-spin w-3.5 h-3.5 text-[#FF8E24]" />
                            <span className="font-mono text-gray-400">Tool Socket actively engaged:</span>
                            <span className="flex items-center gap-1 bg-[#FF8E24]/15 text-[#FF8E24] px-2 py-0.5 rounded-md font-mono text-[10px] uppercase font-bold tracking-wider border border-[#FF8E24]/10">
                              {getIcon(msg.toolActivity.toolName.toLowerCase().replace(/\s+/g, '-') || msg.toolActivity.emoji, 'w-3 h-3')}
                              {msg.toolActivity.toolName}
                            </span>
                          </div>
                          <button 
                            onClick={() => toggleToolCollapse(msg.toolActivity!.id)}
                            className="text-[10px] font-mono text-gray-500 hover:text-[#FF8E24] transition-all bg-[#1b1e2c] border border-[#2d3246] px-2 py-0.5 rounded-md"
                          >
                            {collapsedToolActivities[msg.toolActivity.id] ? "Expand results (Full Log)" : "Collapse"}
                          </button>
                        </div>

                        {/* Collateral body content */}
                        {!collapsedToolActivities[msg.toolActivity.id] ? (
                          <div className="p-4 space-y-3 font-mono">
                            <div className="flex items-start gap-2 bg-black/45 p-2 rounded-lg border border-[#1e2332]/50 text-emerald-400">
                              <span className="text-gray-500 select-none">sh$</span>
                              <span className="text-[10.5px]">{msg.toolActivity.action}</span>
                            </div>
                            <div className="space-y-1 mt-1">
                              <div className="text-gray-500 text-[10px] uppercase">Stdout returns:</div>
                              <p className="text-gray-300 text-[10.5px] bg-[#1a1e2b] p-3 rounded-lg border border-[#2c3349]/50 leading-relaxed whitespace-pre-line border-l-2 border-l-[#FF8E24]">
                                {msg.toolActivity.outputSummary}
                              </p>
                            </div>
                            <div className="flex items-center gap-1 text-[10px] text-[#FF8E24]/70">
                              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 inline mr-0.5" />
                              <span>Instruction execution validated. Sandbox socket gracefully returned 0.</span>
                            </div>
                          </div>
                        ) : (
                          <div className="px-4 py-2 bg-black/20 text-gray-500 text-[10.5px] font-mono flex items-center gap-1.5 border-t border-[#1e2436]/50">
                            <Clock className="w-3 h-3 text-gray-600 inline" />
                            <span>Run details flattened to summary statement: {msg.toolActivity.outputSummary.slice(0, 50)}...</span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* 3. Escalation Banner Status Indicator (specifically asked in prompt) */}
                    {msg.escalation && (
                      <div className={`p-4 rounded-2xl border flex items-start gap-3.5 shadow-md ${
                        msg.escalation.status === 'need_raised'
                          ? 'bg-amber-950/15 border-amber-950/60 text-amber-500 shadow-amber-950/5'
                          : msg.escalation.status === 'arslan_resolving'
                          ? 'bg-orange-950/20 border-[#FF8E24]/30 text-[#FF8E24] shadow-[#FF8E24]/5'
                          : msg.escalation.status === 'resolved'
                          ? 'bg-emerald-950/15 border-emerald-950/60 text-emerald-500 shadow-emerald-500/5'
                          : 'bg-red-950/15 border-red-950/60 text-red-500 shadow-red-950/5'
                      }`}>
                        <div className="mt-0.5">
                          {msg.escalation.status === 'need_raised' && <AlertTriangle className="w-4.5 h-4.5 animate-bounce" />}
                          {msg.escalation.status === 'arslan_resolving' && <Cpu className="w-4.5 h-4.5 animate-spin" />}
                          {msg.escalation.status === 'resolved' && <CheckCircle2 className="w-4.5 h-4.5 text-emerald-500" />}
                          {msg.escalation.status === 'refused' && <XOctagon className="w-4.5 h-4.5 text-red-500" />}
                        </div>
                        <div className="space-y-1 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-[11.5px] font-bold font-mono tracking-wide uppercase">
                              {msg.escalation.status === 'need_raised' && "Escalation raised"}
                              {msg.escalation.status === 'arslan_resolving' && "Arslan resolving escalation"}
                              {msg.escalation.status === 'resolved' && "Escalation resolved"}
                              {msg.escalation.status === 'refused' && "Escalation Safety Trigger: REFUSED"}
                            </span>
                            <span className="text-[9px] bg-black/30 font-mono px-1.5 border border-white/5 rounded">
                              From: {msg.escalation.spawnName}
                            </span>
                          </div>
                          <p className="text-[11px] text-gray-300 font-sans leading-relaxed">{msg.escalation.issue}</p>
                          
                          {/* Inner details if context resolution message exists */}
                          {msg.escalation.resolutionMessage && (
                            <div className="mt-2.5 p-2.5 bg-black/50 rounded-lg border border-red-900/40 text-red-400 font-mono text-[10.5px] leading-relaxed">
                              {msg.escalation.resolutionMessage}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Avatar right (for user) */}
                  {isUser && (
                    <div className="flex flex-col items-center select-none">
                      <div className="w-9 h-9 rounded-xl bg-[#1e2330] border border-gray-700 flex items-center justify-center text-sm shadow-md">
                        <SFSymbol nameOrEmoji={msg.senderAvatar} className="w-4 h-4 text-white" />
                      </div>
                      <span className="text-[9px] text-gray-500 font-mono mt-1 font-semibold">{msg.timestamp}</span>
                    </div>
                  )}
                </div>
              );
            }

            // Brutalist Theme Rendering (High-contrast, terminal-like blocks, retro orange elements)
            if (currentStyle === 'brutalist') {
              return (
                <div 
                  key={msg.id} 
                  className={`border-2 border-orange-500/60 p-4 font-mono text-[12px] bg-[#090b10] shadow-[4px_4px_0px_#FF8E24] relative`}
                >
                  {/* Sender Headers */}
                  <div className="flex items-center justify-between pb-2 border-b border-dashed border-gray-800 select-none mb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-amber-500 font-bold flex items-center gap-1.5">
                        [<SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5 inline-block" />] {msg.senderName.toUpperCase()}
                      </span>
                      <span className="text-[10px] px-1 py-0.2 bg-orange-950/20 text-orange-500 border border-orange-500/25">
                        {msg.sender.toUpperCase()}
                      </span>
                    </div>
                    <span className="text-gray-500 text-[10px]">{msg.timestamp}</span>
                  </div>

                  <p className="whitespace-pre-line text-gray-300 font-mono leading-relaxed">{msg.text}</p>

                  {/* Routed branch block */}
                  {msg.routedTo && (
                    <div className="mt-3 p-2 bg-[#FF8E24]/5 border-2 border-[#FF8E24] text-[11px] text-[#FF8E24] uppercase font-bold flex items-center gap-1.5 shadow-[2px_2px_0px_#000]">
                      <span>≫ DELEGATING THREAD DIRECTLY TO {msg.routedTo.spawnName.toUpperCase()}</span>
                    </div>
                  )}

                  {/* Spawn Intro Brutalist version */}
                  {msg.spawnIntro && (
                    <div className="mt-4 border-2 border-orange-500 bg-black p-3 space-y-2 text-[11px]">
                      <div className="flex items-center gap-2 font-bold text-orange-500">
                        <span>SPAWN CREATION INDEX: {msg.spawnIntro.name.toUpperCase()}</span>
                      </div>
                      <p className="text-gray-400 text-[10px]">DOMAIN: {msg.spawnIntro.domain.toUpperCase()}</p>
                      
                      <div className="pt-2 border-t border-gray-900 space-y-1">
                        <span className="text-gray-500 font-bold">EQUIPPED CAPABILITIES:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {msg.spawnIntro.tools.map(toolId => (
                            <span key={toolId} className="px-1.5 py-0.5 bg-black text-gray-300 border border-gray-700">
                              [TOOL] {toolId.toUpperCase()}
                            </span>
                          ))}
                          {msg.spawnIntro.skills.map(skillId => (
                            <span key={skillId} className="px-1.5 py-0.5 bg-black text-orange-500 border border-orange-500">
                              [SKILL] {skillId.toUpperCase()}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Tool Activity Brutalist version */}
                  {msg.toolActivity && (
                    <div className="mt-4 border-2 border-amber-500 bg-[#07090e] p-3 text-[11px] font-mono">
                      <div className="text-amber-500 font-bold uppercase pb-1 border-b border-amber-500/20 flex justify-between items-center">
                        <span className="flex items-center gap-1.5">
                          <Wrench className="w-3 h-3" />
                          EXECUTING SOCKET ACTIVITY: {msg.toolActivity.toolName.toUpperCase()}
                        </span>
                        <span className="text-[9px] bg-amber-500 text-black px-1">RUNNING</span>
                      </div>
                      
                      <div className="mt-2 text-gray-300 p-1 bg-black border border-gray-800">
                        <span className="text-gray-500">$</span> {msg.toolActivity.action}
                      </div>

                      <div className="mt-2 text-[#FF8E24]">
                        RETURN VALUE SUMMARY: {msg.toolActivity.outputSummary}
                      </div>
                    </div>
                  )}

                  {/* Brutalist Escalation Panel */}
                  {msg.escalation && (
                    <div className="mt-4 border-2 border-red-500 bg-black p-3 text-[11px]">
                      <div className="text-red-500 font-bold uppercase select-none pb-2 flex justify-between">
                        <span>⚠️ EXTREME PRIORITY ESCALATION INDEX ⚠️</span>
                        <span>{msg.escalation.status.toUpperCase()}</span>
                      </div>
                      <p className="text-gray-300 font-semibold">{msg.escalation.issue.toUpperCase()}</p>
                      {msg.escalation.resolutionMessage && (
                        <div className="mt-2 bg-red-950/20 text-red-500 p-2 border border-red-800">
                          LOG REJECTION DETAILED STATEMENT: {msg.escalation.resolutionMessage.toUpperCase()}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            }

            // Linear Minimal Theme Rendering (Sleek layout, precise margins, subtle borders, thin colors)
            if (currentStyle === 'linear') {
              return (
                <div key={msg.id} className="border-b border-[#1e2330]/40 pb-5 text-[12px] space-y-2">
                  {/* Sender Metadata Row */}
                  <div className="flex items-center gap-2 select-none text-[11px]">
                    <span className="text-gray-500 flex items-center justify-center"><SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5" /></span>
                    <span className="font-bold text-gray-200">{msg.senderName}</span>
                    <span className="text-gray-500 font-mono">•</span>
                    <span className="text-gray-500 font-mono">{msg.timestamp}</span>
                    {isArslan && (
                      <span className="text-[9px] bg-[#1a1c22] text-[#FF8E24] px-1.5 py-0.2 rounded font-mono border border-[#FF8E24]/20 uppercase">
                        Orchestrator
                      </span>
                    )}
                    {!isArslan && !isUser && (
                      <span className="text-[9px] bg-gray-950 text-amber-500 px-1.5 py-0.2 rounded font-mono border border-amber-900/40 uppercase">
                        Spawn • Core
                      </span>
                    )}
                  </div>

                  {/* Body Content */}
                  <p className="whitespace-pre-line text-gray-300 font-sans leading-relaxed text-[12.5px] pl-5">
                    {msg.text}
                  </p>

                  {/* Linear clean route badge */}
                  {msg.routedTo && (
                    <div className="text-[10px] text-gray-500 font-mono flex items-center gap-1.5 pl-5">
                      <span className="text-[#999]">→ Routed process to:</span>
                      <span className="text-[#FF8E24] hover:underline font-bold select-none cursor-pointer">
                        {msg.routedTo.spawnName}
                      </span>
                    </div>
                  )}

                  {/* Linear Minimal Spawn intro */}
                  {msg.spawnIntro && (
                    <div className="pl-5 pt-2">
                      <div className="border border-gray-800 bg-[#0a0d13] rounded-lg p-3 space-y-2.5 max-w-xl">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-white text-[11px]">{msg.spawnIntro.name} Spawn Registry</span>
                          </div>
                          <span className="text-[9px] bg-gray-900 text-gray-400 px-1 py-0.2 rounded font-mono">active</span>
                        </div>
                        <div className="text-[10px] text-gray-500">Capabilities Matrix:</div>
                        <div className="flex flex-wrap gap-1">
                          {msg.spawnIntro.tools.map(toolId => (
                            <span key={toolId} className="text-[10px] bg-[#13151b] border border-gray-800 text-gray-300 px-1.5 py-0.2 rounded">
                              {toolId}
                            </span>
                          ))}
                          {msg.spawnIntro.skills.map(skillId => (
                            <span key={skillId} className="text-[10px] bg-amber-950/15 border border-amber-900/30 text-amber-500 px-1.5 py-0.2 rounded">
                              {skillId}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Linear Minimal Tool activity */}
                  {msg.toolActivity && (
                    <div className="pl-5 pt-2">
                      <div className="border border-gray-800 bg-[#0d0f15]/50 rounded-lg p-2 max-w-xl font-mono text-[10.5px]">
                        <div className="flex items-center gap-1.5 text-gray-400">
                          <Wrench className="w-3.5 h-3.5 text-[#FF8E24]" />
                          <span>Standard Executor tool {msg.toolActivity.toolName}:</span>
                          <span className="text-gray-600 bg-[#121622] px-1 rounded uppercase tracking-wider text-[8px] border border-gray-800">OK</span>
                        </div>
                        <div className="mt-1 text-gray-500 pl-5">
                          {msg.toolActivity.action}
                        </div>
                        <div className="mt-1 pl-5 text-[#FF8E24]">
                          Summary Outcome: {msg.toolActivity.outputSummary}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Linear Minimal Escalation status */}
                  {msg.escalation && (
                    <div className="pl-5 pt-2">
                      <div className="border border-red-950/40 bg-red-950/5 border-l-2 border-l-red-500 rounded-r-lg p-3 max-w-xl">
                        <div className="flex items-center gap-1 text-[10.5px] text-red-500 font-mono font-bold uppercase select-none">
                          <AlertTriangle className="w-3.5 h-3.5" />
                          <span>Escalation Exception - Spawn Access Lockout ({msg.escalation.status})</span>
                        </div>
                        <p className="text-[11px] text-gray-300 mt-1 leading-relaxed">{msg.escalation.issue}</p>
                        {msg.escalation.resolutionMessage && (
                          <p className="mt-2 text-red-400 text-[10px] font-mono whitespace-pre-wrap pl-2 bg-black/40 py-1.5 rounded">{msg.escalation.resolutionMessage}</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            }

            return null;
          })
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input Message Form Panel */}
      {chatHistory.length > 0 && (
        <footer className="p-4 border-t border-[#1e2330] bg-[#0a0c10]/80 backdrop-blur shrink-0 z-10 select-none">
          <form onSubmit={handleSendMessage} className="max-w-4xl mx-auto flex items-center gap-2 relative">
            <input
              id="chat-message-input"
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Ask Arslan to orchestrate a task for your spawns..."
              className="w-full bg-[#121520] border border-[#23293e] hover:border-[#353e5e] focus:border-[#FF8E24]/60 focus:ring-1 focus:ring-[#FF8E24]/30 rounded-xl px-4 py-3 text-xs text-white placeholder-gray-500 focus:outline-none pr-12 transition-all font-sans"
            />
            <button
              id="chat-send-submit"
              type="submit"
              disabled={!inputValue.trim()}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-[#FF8E24] hover:bg-[#ff9c3a] disabled:bg-gray-800 disabled:text-gray-500 disabled:opacity-50 text-black font-bold uppercase rounded-lg transition-all"
            >
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>
          <div className="flex items-center justify-center gap-6 mt-2 text-[10px] text-gray-600 font-mono">
            <span>Enter to execute prompt</span>
            <span>•</span>
            <span className="flex items-center gap-1.5 font-sans">
              <Layers className="w-3.5 h-3.5 text-gray-500" />
              Core Host is sandboxed local client loop
            </span>
          </div>
        </footer>
      )}
    </div>

    {/* Right Pane: Isolated Co-Pilot Private Sandbox (副对话框) */}
    {splitSpawnId && (() => {
      const spawn = spawns.find(s => s.id === splitSpawnId);
      if (!spawn) return null;


      return (
        <div className="w-[45%] border-l border-[#1e2330] bg-[#090b0f] flex flex-col h-full animate-slide-in-right relative overflow-hidden shrink-0 z-20">
          {/* Sandbox Top Header */}
          <div className="h-[52px] border-b border-[#1e2330] px-4.5 bg-[#0a0c10]/80 backdrop-blur flex items-center justify-between select-none shrink-0">
            <div className="flex items-center gap-2.5">
              <SFSymbol nameOrEmoji={spawn.avatarEmoji} className="w-5 h-5 text-[#FF8E24]" />
              <div>
                <div className="flex items-center gap-1.5 leading-none">
                  <span className="text-xs font-bold text-white font-sans">{spawn.name}</span>
                  <span className="text-[9px] bg-amber-500/10 text-amber-500 border border-amber-500/20 px-1.5 py-0.2 rounded font-mono font-bold uppercase">
                    Sandbox
                  </span>
                </div>
                <span className="text-[9px] text-[#FF8E24] font-mono mt-1 block uppercase tracking-wider">{spawn.domain}</span>
              </div>
            </div>

            <button 
              onClick={() => setSplitSpawnId(null)}
              className="p-1 text-gray-400 hover:text-white bg-[#10131b] border border-gray-800/80 rounded hover:bg-black/30"
              title="Minimize Sandbox"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Sandbox Content: Coming Soon — dispatch + draft backend not yet wired */}
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-4 select-none">
            <div className="w-12 h-12 rounded-xl bg-amber-950/20 border border-amber-500/20 flex items-center justify-center">
              <SFSymbol nameOrEmoji={spawn.avatarEmoji} className="w-6 h-6 text-amber-500" />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-center gap-2">
                <span className="text-xs font-bold text-white font-sans">{spawn.name} Sandbox</span>
                <span className="text-[9px] font-mono bg-amber-950/20 text-amber-500 border border-amber-500/20 px-1.5 py-0.5 rounded uppercase tracking-wider">即将推出</span>
              </div>
              <p className="text-[11px] text-gray-500 font-sans leading-relaxed max-w-xs">
                Per-spawn sandbox dispatch and draft review are not yet wired to a backend frame. This panel will show real spawn output once the dispatch protocol is implemented.
              </p>
            </div>
            <button
              onClick={() => setSplitSpawnId(null)}
              className="mt-2 px-4 py-1.5 bg-transparent hover:bg-white/[0.04] text-gray-400 hover:text-white text-[10px] rounded-xl border border-gray-800/80 font-mono uppercase tracking-wider transition-all"
            >
              Close Panel
            </button>
          </div>
        </div>
      );
    })()}
  </div>
</div>
);
}
