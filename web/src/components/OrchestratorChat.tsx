import React, { useState, useRef, useEffect } from 'react';
import {
  ArrowRight, Terminal, Wrench,
  AlertTriangle, CheckCircle2, XOctagon, Clock,
  Layers, CornerDownRight,
  Cpu, X, Send, ChevronDown,
  Plus, RefreshCcw
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getIcon } from './iconMap';
import { Message, Spawn, Tool, Skill } from '../types';
import { TOOLS, SKILLS } from '../data';
import SFSymbol from './SFSymbol';
import { SpawnAvatar } from './SpawnAvatar';
import Markdown from './Markdown';
import { useArslanStore } from '../stores/arslanStore';
import NoModelHint from './NoModelHint';
import RunReplay from './RunReplay';
import EvalSummary from './EvalSummary';
import AttachBar, { type Attachment } from './AttachBar';

interface OrchestratorChatProps {
  chatHistory: Message[];
  setChatHistory: React.Dispatch<React.SetStateAction<Message[]>>;
  /** When provided, user prompts are sent via this callback (live WS) instead of the mock simulation. */
  onSendMessage?: (text: string, attached?: { context: string; names: string[] }) => void;
  spawns: Spawn[];
  currentStyle: 'quartz' | 'brutalist' | 'linear';
  setCurrentStyle: (style: 'quartz' | 'brutalist' | 'linear') => void;
  activeThread: any;
  /** Called when the user confirms a proposed direction. spawnId is the numeric backend id. */
  onConfirmDirection?: (spawnId: number) => void;
  /** Called when the user submits a verdict on a spawn deliverable. */
  onDeliverableVerdict?: (action: string, spawnId: number, messageId?: number, taskBrief?: string | null) => void;
  /** True when at least one ProviderConfig exists. When false, a hint to configure a model is shown. */
  hasModel?: boolean;
  /** Navigate to the Settings screen. Used by the no-model hint. */
  onOpenSettings?: () => void;
}

export default function OrchestratorChat({
  chatHistory,
  setChatHistory,
  onSendMessage,
  spawns,
  currentStyle,
  setCurrentStyle,
  activeThread,
  onConfirmDirection,
  onDeliverableVerdict,
  hasModel = true,
  onOpenSettings,
}: OrchestratorChatProps) {
  const { t } = useTranslation();
  // Live roster from store — used to determine which spawns are in this conversation
  const roster = useArslanStore((s) => s.roster);
  const thinking = useArslanStore((s) => (s as any).thinking as boolean);
  const streaming = useArslanStore((s) => s.streaming);
  const llmError = useArslanStore((s) => s.error);
  const clearLlmError = useArslanStore((s) => s.clearError);
  const [inputValue, setInputValue] = useState('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attachKey, setAttachKey] = useState(0);
  const [collapsedToolActivities, setCollapsedToolActivities] = useState<Record<string, boolean>>({});
  const [replayRunId, setReplayRunId] = useState<number | null>(null);
  const [showEvalSummary, setShowEvalSummary] = useState(false);
  
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

    const context = attachments.map((a) => a.text).join("\n\n---\n\n");
    const names = attachments.map((a) => a.name);
    const clearAttachments = () => {
      setAttachments([]);
      setAttachKey((k) => k + 1);
    };

    if (onSendMessage) {
      // Live WS path: delegate to parent's onSendMessage (store + WS send)
      onSendMessage(text, context ? { context, names } : undefined);
      clearAttachments();
      return;
    }

    clearAttachments();

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
    <div className="flex-1 flex flex-col h-full bg-background relative overflow-hidden">
      {/* Absolute Ambient Background Lights for Quartz Theme */}
      {currentStyle === 'quartz' && (
        <>
          <div className="absolute top-1/4 left-1/3 w-[30rem] h-[30rem] bg-primary/5 blur-[120px] rounded-full pointer-events-none -translate-x-1/2 -translate-y-1/2"></div>
          <div className="absolute bottom-1/4 right-0 w-[40rem] h-[40rem] bg-primary/[0.03] blur-[150px] rounded-full pointer-events-none translate-x-1/3 translate-y-1/3"></div>
        </>
      )}



      {/* Simulator Interactive Control Strip & Spawns Docket Integrated */}
      <div className="bg-surface/60 border-b border-border/80 px-6 py-2.5 flex flex-row items-center justify-between gap-4 select-none text-[11px] z-10">
        <div className="flex items-center gap-2 shrink-0">
          <Terminal className="w-4 h-4 text-primary" />
          <span className="text-muted-foreground font-mono font-bold uppercase tracking-wider">{t('orchestrator.sandbox_label')}</span>
          <button type="button" className="eval-open-btn" onClick={() => setShowEvalSummary(true)}>评估</button>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {(() => {
            // Derive member spawns from the live store roster
            const rosterIds = new Set(roster.map((m) => String(m.spawnId)));
            const memberSpawns = spawns.filter((s) => rosterIds.has(s.id));
            // Show only roster members; no fallback to mock names
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
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-warning opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-warning"></span>
                  </span>
                );
              } else if (isReviewPending) {
                // High-energy blinking alert indicator requesting action
                statusIndicator = (
                  <span className="relative flex h-2 w-2 mr-1">
                    <span className="animate-pulse absolute inline-flex h-full w-full rounded-full bg-danger/80 opacity-80 scale-125"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-danger animate-ping"></span>
                  </span>
                );
              } else {
                // Normal quiet breathing green indicator for ready/idle
                statusIndicator = (
                  <span className="relative flex h-1.5 w-1.5 mr-1">
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-success/80"></span>
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
                      ? 'border-danger/60 bg-danger/15 text-danger hover:border-danger shadow-md shadow-danger/5 animate-pulse'
                      : isWorking
                      ? 'border-warning/30 bg-warning/5 text-warning/80 hover:border-warning/60'
                      : isSplitActive
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border bg-surface/40 hover:border-border-strong text-muted-foreground hover:text-foreground'
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
          splitSpawnId ? 'w-[55%] border-r border-border' : 'w-full'
        }`}>
          {/* Scrollable Chat Area */}
          <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {chatHistory.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-2xl mx-auto py-10 px-4 space-y-8 select-none">
            {/* Greeting Header inspired by Claude's elegant style */}
            <div className="space-y-3 animate-fade-in">
              <div className="flex items-center justify-center gap-3">
                {/* Arslan mark */}
                <img src="/arslan-mark.png" alt="Arslan" className="w-11 h-11 object-contain select-none arslan-mark" draggable={false} />

                {/* Elegant serif-style greeting */}
                <h1 className="text-3xl sm:text-4.5xl font-serif text-primary tracking-tight font-medium leading-none">
                  {(() => {
                    const hr = new Date().getHours();
                    if (hr < 12) return 'Morning';
                    if (hr < 18) return 'Afternoon';
                    return 'Evening';
                  })()}, Mirzat
                </h1>
              </div>
            </div>

            {/* No-model hint — shown when zero ProviderConfigs are configured */}
            <NoModelHint hasModel={hasModel} onOpenSettings={onOpenSettings ?? (() => {})} />

            {/* Luxurious prompt input box resembling Claude's container design */}
            <div className="w-full max-w-xl bg-surface border border-border-strong rounded-2xl p-4 flex flex-col space-y-3 focus-within:border-primary/60 focus-within:ring-1 focus-within:ring-ring/30 shadow-2xl transition-all">
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
                placeholder={t('orchestrator.placeholder_empty')}
                className="w-full bg-transparent text-sm text-foreground placeholder-subtle-foreground focus:outline-none resize-none px-2 pt-1 font-sans leading-relaxed min-h-[55px]"
              />

              {/* Action options row */}
              <div className="flex items-center justify-between pt-2 border-t border-border/50 select-none">
                <button 
                  type="button" 
                  onClick={() => alert("Local datasets & specialized credentials mounted securely inside workspace.")} 
                  className="p-1.5 text-subtle-foreground hover:text-muted-foreground hover:bg-foreground/[0.03] rounded-lg transition-all"
                  title="Attach workspace documents or source context"
                >
                  <Plus className="w-4.5 h-4.5 text-subtle-foreground" />
                </button>

                <div className="flex items-center gap-2">
                  {/* Model Choice indicator */}
                  <div className="flex items-center gap-1 bg-background/40 hover:bg-background/60 px-2.5 py-1 rounded-full border border-border text-[10px] font-mono text-muted-foreground hover:text-foreground cursor-pointer transition-colors max-w-[130px] sm:max-w-none truncate">
                    <Cpu className="w-3 h-3 text-primary" />
                    <span className="ml-0.5">Arslan v4.8 High</span>
                    <ChevronDown className="w-3 h-3 text-subtle-foreground" />
                  </div>

                  {/* Micro icon */}
                  <button type="button" className="p-1 text-subtle-foreground hover:text-muted-foreground" title="Audio transcription input">
                    <svg className="w-4 h-4 text-subtle-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                      <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 19v4M8 23h8" />
                    </svg>
                  </button>

                  {/* Wave icon */}
                  <button type="button" className="p-1 text-subtle-foreground hover:text-muted-foreground" title="Simulated audio feedback channel">
                    <svg className="w-4 h-4 text-subtle-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
                    className="p-1.5 bg-primary text-primary-foreground hover:bg-primary-hover disabled:bg-surface-raised/80 disabled:text-subtle-foreground rounded-lg transition-all flex items-center justify-center ml-1"
                  >
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>

            {/* Quick action pill suggestions inspired by Claude suggestions */}
            <div className="w-full max-w-xl text-center space-y-2">
              <span className="text-[10px] font-mono text-subtle-foreground uppercase tracking-widest block">{t('orchestrator.presets_label')}</span>
              <div className="flex flex-wrap gap-1.5 justify-center">
                {[
                  { icon: 'vuln-test', label: t('orchestrator.preset_code_audit'), prompt: "Conduct automatic code analysis on sandbox files to discover vulnerability patterns." },
                  { icon: 'financial-res', label: t('orchestrator.preset_financial'), prompt: "Summarize Q1 market ratings and consensus predictions for Blackwell chipsets output." },
                  { icon: 'seo-opt', label: t('orchestrator.preset_slogan'), prompt: "Draft optimized copywriting hooks for key promotional tech campaigns with emojis." },
                  { icon: 'web-search', label: t('orchestrator.preset_drive'), prompt: "Use Brave registry crawler tool to catalog recent AI deployment metrics." }
                ].map((item, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      setInputValue(item.prompt);
                      document.getElementById('landing-message-input')?.focus();
                    }}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-surface/60 hover:bg-surface-raised border border-border/80 rounded-full text-[11px] text-muted-foreground hover:text-foreground transition-all cursor-pointer select-none font-sans"
                  >
                    {getIcon(item.icon, 'w-3.5 h-3.5')}
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

            // Roster notice: render for all themes as a subtle centered line
            if (msg.rosterAction) {
              const name = msg.rosterSpawnName ?? '';
              const label = msg.rosterAction === 'joined'
                ? t('chat.roster_joined', { name })
                : t('chat.roster_left', { name });
              return (
                <div key={msg.id} className="flex items-center gap-3 py-1 select-none">
                  <div className="flex-1 h-px bg-border/60" />
                  <span className="text-[10px] text-subtle-foreground font-mono whitespace-nowrap">
                    {msg.rosterAction === 'joined' ? '🔗' : '✕'} {label}
                  </span>
                  <div className="flex-1 h-px bg-border/60" />
                </div>
              );
            }

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
                      <div className="relative">
                        {isArslan ? (
                          <img src="/arslan-mark.png" alt="Arslan" className="w-9 h-9 object-contain select-none arslan-mark" draggable={false} />
                        ) : (
                          <SpawnAvatar seed={msg.senderName} size={36} />
                        )}
                        <span className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-background ${
                          isArslan ? 'bg-success' : 'bg-primary'
                        }`} />
                      </div>
                      <span className="text-[9px] text-subtle-foreground font-mono mt-1 font-semibold">{msg.timestamp}</span>
                    </div>
                  )}

                  {/* Message Bubble */}
                  <div className={`space-y-3 ${isUser ? 'order-1 max-w-[68%]' : 'max-w-2xl'}`}>
                    {/* Sender label name (non-user only) */}
                    {!isUser && (
                      <div className="flex items-center gap-1.5 select-none">
                        <span className="text-[11px] font-semibold text-muted-foreground">{msg.senderName}</span>
                        {isArslan ? (
                          <span className="text-[9px] bg-primary/10 text-primary px-2 py-0.5 rounded font-semibold font-mono uppercase tracking-wider">
                            {t('app.name')} Orchestrator
                          </span>
                        ) : (
                          <div className="flex items-center gap-1">
                            <span className="text-[9px] bg-primary/10 text-primary px-2 py-0.5 rounded font-mono uppercase tracking-wider font-semibold">
                              Spawn Core
                            </span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Styled Bubble Body */}
                    <div className={`px-4 py-3 text-[12.5px] leading-relaxed relative ${
                      isUser
                        ? 'bg-[rgba(120,140,170,0.10)] border border-[rgba(255,255,255,0.08)] rounded-[12px_12px_4px_12px] text-foreground text-left'
                        : isArslan
                        ? 'bg-surface/80 backdrop-blur border border-border-strong text-foreground rounded-2xl rounded-tl-none shadow-sm shadow-black/40'
                        : 'bg-background/90 backdrop-blur border border-primary/15 text-foreground rounded-2xl rounded-tl-none'
                    }`}>
                      {/* Message Content */}
                      {isUser
                        ? <p className="whitespace-pre-line font-sans leading-relaxed">{msg.text}</p>
                        : <Markdown className="text-[12.5px] leading-relaxed font-sans [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">{msg.text}</Markdown>
                      }

                      {/* Routed Indicator - specifically asked in prompt */}
                      {msg.routedTo && (
                        <div className="mt-3.5 pt-3 border-t border-border/50 flex items-center gap-2.5 text-[11px] font-mono bg-surface/50 p-2 rounded-lg border border-border-strong">
                          <div className="w-2 h-2 rounded-full bg-primary animate-ping" />
                          <div className="flex items-center gap-1 text-muted-foreground">
                            <span>Workflow context routed to</span>
                            <span className="text-primary font-semibold flex items-center gap-0.5">
                              <CornerDownRight className="w-3 h-3 inline-block" />
                              {msg.routedTo.spawnName}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* 1. Spawn Intro Card Sub-Component (specifically asked in prompt) */}
                    {msg.spawnIntro && (
                      <div className="bg-gradient-to-b from-surface/90 to-background/95 border border-primary/30 rounded-2xl p-4 shadow-xl shadow-primary/5 space-y-3.5 relative overflow-hidden group">
                        {/* Decorative background glow for card */}
                        <div className="absolute top-0 right-0 w-24 h-24 bg-primary/5 blur-xl group-hover:bg-primary/10 transition-all rounded-full pointer-events-none"></div>

                        <div className="flex items-start gap-3.5">
                          <SpawnAvatar seed={msg.spawnIntro.name} size={44} />
                          <div>
                            <div className="flex items-center gap-2">
                              <h4 className="text-xs font-bold text-foreground font-sans">{msg.spawnIntro.name}</h4>
                              <span className="text-[9px] bg-primary/15 text-primary font-mono px-2 py-0.5 rounded font-bold uppercase tracking-widest">Introduced</span>
                            </div>
                            <p className="text-[10px] text-muted-foreground font-mono mt-0.5">{msg.spawnIntro.domain}</p>
                          </div>
                        </div>

                        {/* Equipped Capabilities Rendering */}
                        <div className="space-y-2">
                          <div className="text-[10px] text-subtle-foreground font-mono font-medium tracking-wide uppercase">{t('orchestrator.equipped_capabilities')}</div>
                          <div className="flex flex-wrap gap-1.5">
                            {/* Render Tool tags with lucide icon */}
                            {msg.spawnIntro.tools.map(toolId => {
                              const toolMeta = TOOLS.find(t => t.id === toolId);
                              return (
                                <span
                                  key={toolId}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-mono bg-surface text-muted-foreground px-2 py-0.5 rounded-lg hover:text-foreground transition-all"
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
                                  className="inline-flex items-center gap-1 text-[10.5px] font-mono bg-primary/10 text-primary px-2 py-0.5 rounded-lg transition-all"
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
                      <div className="bg-surface border border-border-strong rounded-2xl shadow-lg shadow-background/30 overflow-hidden text-[11px] font-sans">
                        {/* Header bar */}
                        <div className="bg-background px-4 py-2.5 flex items-center justify-between border-b border-border select-none">
                          <div className="flex items-center gap-2">
                            <RefreshCcw className="animate-spin w-3.5 h-3.5 text-primary" />
                            <span className="font-mono text-muted-foreground">Tool Socket actively engaged:</span>
                            <span className="flex items-center gap-1 bg-primary/15 text-primary px-2 py-0.5 rounded-md font-mono text-[10px] uppercase font-bold tracking-wider">
                              {getIcon(msg.toolActivity.toolName.toLowerCase().replace(/\s+/g, '-') || msg.toolActivity.emoji, 'w-3 h-3')}
                              {msg.toolActivity.toolName}
                            </span>
                          </div>
                          <button
                            onClick={() => toggleToolCollapse(msg.toolActivity!.id)}
                            className="text-[10px] font-mono text-subtle-foreground hover:text-primary transition-all bg-surface-raised border border-border px-2 py-0.5 rounded-md"
                          >
                            {collapsedToolActivities[msg.toolActivity.id] ? t('orchestrator.expand_results') : t('orchestrator.collapse_results')}
                          </button>
                        </div>

                        {/* Collateral body content */}
                        {!collapsedToolActivities[msg.toolActivity.id] ? (
                          <div className="p-4 space-y-3 font-mono">
                            <div className="flex items-start gap-2 bg-background/45 p-2 rounded-lg border border-border/50 text-success">
                              <span className="text-subtle-foreground select-none">sh$</span>
                              <span className="text-[10.5px]">{msg.toolActivity.action}</span>
                            </div>
                            <div className="space-y-1 mt-1">
                              <div className="text-subtle-foreground text-[10px] uppercase">{t('orchestrator.stdout_label')}</div>
                              <p className="text-muted-foreground text-[10.5px] bg-surface p-3 rounded-lg border border-border-strong/50 leading-relaxed whitespace-pre-line border-l-2 border-l-primary">
                                {msg.toolActivity.outputSummary}
                              </p>
                            </div>
                            {/* 🔒 SECURITY: artifactSvg is populated ONLY from the backend render_chart tool_result
                                frame (arslanStore), NEVER from LLM message text. Do not render SVG from any other source. */}
                            {msg.toolActivity?.artifactSvg && (
                              <div className="tool-chart" dangerouslySetInnerHTML={{ __html: msg.toolActivity.artifactSvg }} />
                            )}
                            <div className="flex items-center gap-1 text-[10px] text-primary/70">
                              <CheckCircle2 className="w-3.5 h-3.5 text-success inline mr-0.5" />
                              <span>{t('orchestrator.exec_validated')}</span>
                            </div>
                          </div>
                        ) : (
                          <div className="px-4 py-2 bg-background/20 text-subtle-foreground text-[10.5px] font-mono flex items-center gap-1.5 border-t border-border/50">
                            <Clock className="w-3 h-3 text-subtle-foreground inline" />
                            <span>Run details flattened to summary statement: {msg.toolActivity.outputSummary.slice(0, 50)}...</span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* 3. Escalation Banner Status Indicator (specifically asked in prompt) */}
                    {msg.escalation && (
                      <div className={`p-4 rounded-2xl border flex items-start gap-3.5 shadow-md ${
                        msg.escalation.status === 'need_raised'
                          ? 'bg-warning/15 border-warning/60 text-warning shadow-warning/5'
                          : msg.escalation.status === 'arslan_resolving'
                          ? 'bg-primary/20 border-primary/30 text-primary shadow-primary/5'
                          : msg.escalation.status === 'resolved'
                          ? 'bg-success/15 border-success/60 text-success shadow-success/5'
                          : 'bg-danger/15 border-danger/60 text-danger shadow-danger/5'
                      }`}>
                        <div className="mt-0.5">
                          {msg.escalation.status === 'need_raised' && <AlertTriangle className="w-4.5 h-4.5 animate-bounce" />}
                          {msg.escalation.status === 'arslan_resolving' && <Cpu className="w-4.5 h-4.5 animate-spin" />}
                          {msg.escalation.status === 'resolved' && <CheckCircle2 className="w-4.5 h-4.5 text-success" />}
                          {msg.escalation.status === 'refused' && <XOctagon className="w-4.5 h-4.5 text-danger" />}
                        </div>
                        <div className="space-y-1 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-[11.5px] font-bold font-mono tracking-wide uppercase">
                              {msg.escalation.status === 'need_raised' && t('orchestrator.escalation_raised')}
                              {msg.escalation.status === 'arslan_resolving' && t('orchestrator.arslan_resolving')}
                              {msg.escalation.status === 'resolved' && t('orchestrator.escalation_resolved')}
                              {msg.escalation.status === 'refused' && t('orchestrator.escalation_refused')}
                            </span>
                            <span className="text-[9px] bg-background/30 font-mono px-2 py-0.5 rounded">
                              From: {msg.escalation.spawnName}
                            </span>
                          </div>
                          <p className="text-[11px] text-muted-foreground font-sans leading-relaxed">{msg.escalation.issue}</p>

                          {/* Inner details if context resolution message exists */}
                          {msg.escalation.resolutionMessage && (
                            <div className="mt-2.5 p-2.5 bg-background/50 rounded-lg border border-danger/40 text-danger font-mono text-[10.5px] leading-relaxed">
                              {msg.escalation.resolutionMessage}
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Staged orchestration: proposal confirm button (quartz) */}
                    {isSpawn && msg.isProposal && msg.spawnId && (
                      <button
                        onClick={() => onConfirmDirection?.(Number(msg.spawnId))}
                        className="flex items-center gap-2 px-4 py-2 bg-primary/10 hover:bg-primary/20 border border-primary/40 hover:border-primary/70 text-primary text-[11px] font-mono font-bold uppercase tracking-wider rounded-lg transition-all select-none"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>{t('orchestrator.confirm_direction')}</span>
                      </button>
                    )}

                    {/* Staged orchestration: deliverable verdict bar (quartz) */}
                    {isSpawn && !msg.isProposal && msg.spawnId && (
                      msg.verdict ? (
                        <div className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-mono font-bold uppercase tracking-wider text-subtle-foreground select-none">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>{msg.verdict === 'discard' ? t('orchestrator.verdict_discarded') : t('orchestrator.verdict_accepted')}</span>
                        </div>
                      ) : (
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <button
                            onClick={() => onDeliverableVerdict?.('accept', Number(msg.spawnId), msg.messageId)}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-success/20 hover:bg-success/40 border border-success/40 hover:border-success/70 text-success text-[10px] font-mono font-bold uppercase tracking-wider rounded-lg transition-all select-none"
                          >
                            <CheckCircle2 className="w-3 h-3" />
                            <span>{t('orchestrator.verdict_accept')}</span>
                          </button>
                          <button
                            onClick={() => onDeliverableVerdict?.('redo', Number(msg.spawnId), msg.messageId, msg.taskBrief)}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-surface-raised border border-border-strong/60 hover:border-warning/30 text-muted-foreground hover:text-warning text-[10px] font-mono font-bold uppercase tracking-wider rounded-lg transition-all select-none"
                          >
                            <RefreshCcw className="w-3 h-3" />
                            <span>{t('orchestrator.verdict_redo')}</span>
                          </button>
                          <button
                            onClick={() => onDeliverableVerdict?.('discard', Number(msg.spawnId), msg.messageId)}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-danger/20 border border-border-strong/60 hover:border-danger/40 text-subtle-foreground hover:text-danger text-[10px] font-mono font-bold uppercase tracking-wider rounded-lg transition-all select-none"
                          >
                            <X className="w-3 h-3" />
                            <span>{t('orchestrator.verdict_discard')}</span>
                          </button>
                          {msg.sender === "spawn" && msg.runId != null && (
                            <button
                              type="button"
                              className="msg__replay-btn"
                              onClick={() => setReplayRunId(msg.runId ?? null)}
                            >
                              查看回放
                            </button>
                          )}
                        </div>
                      )
                    )}
                  </div>

                  {/* Timestamp for user bubble (right-aligned, no avatar needed — position conveys identity) */}
                  {isUser && (
                    <div className="flex flex-col items-end select-none mt-1">
                      <span className="text-[9px] text-subtle-foreground font-mono font-semibold">{msg.timestamp}</span>
                    </div>
                  )}
                </div>
              );
            }

            // Brutalist Theme Rendering (High-contrast, terminal-like blocks, retro orange elements)
            if (currentStyle === 'brutalist') {
              if (isUser) {
                return (
                  <div key={msg.id} className="flex justify-end">
                    <div className="max-w-[68%] border border-[rgba(255,255,255,0.08)] bg-[rgba(120,140,170,0.10)] p-3 font-mono text-[12px] text-foreground text-left" style={{ borderRadius: '12px 12px 4px 12px' }}>
                      <p className="whitespace-pre-line leading-relaxed">{msg.text}</p>
                      <div className="text-[9px] text-subtle-foreground mt-2 text-right">{msg.timestamp}</div>
                    </div>
                  </div>
                );
              }
              return (
                <div
                  key={msg.id}
                  className={`border-2 border-primary/60 p-4 font-mono text-[12px] bg-background shadow-[4px_4px_0px_var(--color-primary)] relative`}
                >
                  {/* Sender Headers */}
                  <div className="flex items-center justify-between pb-2 border-b border-dashed border-border select-none mb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-primary font-bold flex items-center gap-1.5">
                        [<SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5 inline-block" />] {msg.senderName.toUpperCase()}
                      </span>
                      <span className="text-[10px] px-2 py-0.5 bg-primary/20 text-primary">
                        {msg.sender.toUpperCase()}
                      </span>
                    </div>
                    <span className="text-subtle-foreground text-[10px]">{msg.timestamp}</span>
                  </div>

                  {isUser
                    ? <p className="whitespace-pre-line text-muted-foreground font-mono leading-relaxed">{msg.text}</p>
                    : <Markdown className="text-muted-foreground font-sans leading-relaxed [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">{msg.text}</Markdown>
                  }

                  {/* Routed branch block */}
                  {msg.routedTo && (
                    <div className="mt-3 p-2 bg-primary/5 border-2 border-primary text-[11px] text-primary uppercase font-bold flex items-center gap-1.5 shadow-[2px_2px_0px_black]">
                      <span>≫ DELEGATING THREAD DIRECTLY TO {msg.routedTo.spawnName.toUpperCase()}</span>
                    </div>
                  )}

                  {/* Spawn Intro Brutalist version */}
                  {msg.spawnIntro && (
                    <div className="mt-4 border-2 border-primary bg-background p-3 space-y-2 text-[11px]">
                      <div className="flex items-center gap-2 font-bold text-primary">
                        <span>SPAWN CREATION INDEX: {msg.spawnIntro.name.toUpperCase()}</span>
                      </div>
                      <p className="text-muted-foreground text-[10px]">DOMAIN: {msg.spawnIntro.domain.toUpperCase()}</p>

                      <div className="pt-2 border-t border-border space-y-1">
                        <span className="text-subtle-foreground font-bold">EQUIPPED CAPABILITIES:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {msg.spawnIntro.tools.map(toolId => (
                            <span key={toolId} className="px-2 py-0.5 bg-background text-muted-foreground">
                              [TOOL] {toolId.toUpperCase()}
                            </span>
                          ))}
                          {msg.spawnIntro.skills.map(skillId => (
                            <span key={skillId} className="px-2 py-0.5 bg-background text-primary">
                              [SKILL] {skillId.toUpperCase()}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Tool Activity Brutalist version */}
                  {msg.toolActivity && (
                    <div className="mt-4 border-2 border-primary bg-background p-3 text-[11px] font-mono">
                      <div className="text-primary font-bold uppercase pb-1 border-b border-primary/20 flex justify-between items-center">
                        <span className="flex items-center gap-1.5">
                          <Wrench className="w-3 h-3" />
                          EXECUTING SOCKET ACTIVITY: {msg.toolActivity.toolName.toUpperCase()}
                        </span>
                        <span className="text-[9px] bg-primary text-primary-foreground px-1">RUNNING</span>
                      </div>

                      <div className="mt-2 text-muted-foreground p-1 bg-background border border-border">
                        <span className="text-subtle-foreground">$</span> {msg.toolActivity.action}
                      </div>

                      <div className="mt-2 text-primary">
                        RETURN VALUE SUMMARY: {msg.toolActivity.outputSummary}
                      </div>
                      {/* 🔒 SECURITY: artifactSvg is populated ONLY from the backend render_chart tool_result
                          frame (arslanStore), NEVER from LLM message text. Do not render SVG from any other source. */}
                      {msg.toolActivity?.artifactSvg && (
                        <div className="tool-chart" dangerouslySetInnerHTML={{ __html: msg.toolActivity.artifactSvg }} />
                      )}
                    </div>
                  )}

                  {/* Brutalist Escalation Panel */}
                  {msg.escalation && (
                    <div className="mt-4 border-2 border-danger bg-background p-3 text-[11px]">
                      <div className="text-danger font-bold uppercase select-none pb-2 flex justify-between">
                        <span>⚠️ EXTREME PRIORITY ESCALATION INDEX ⚠️</span>
                        <span>{msg.escalation.status.toUpperCase()}</span>
                      </div>
                      <p className="text-muted-foreground font-semibold">{msg.escalation.issue.toUpperCase()}</p>
                      {msg.escalation.resolutionMessage && (
                        <div className="mt-2 bg-danger/20 text-danger p-2 border border-danger">
                          LOG REJECTION DETAILED STATEMENT: {msg.escalation.resolutionMessage.toUpperCase()}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Staged orchestration: proposal confirm button (brutalist) */}
                  {isSpawn && msg.isProposal && msg.spawnId && (
                    <div className="mt-4">
                      <button
                        onClick={() => onConfirmDirection?.(Number(msg.spawnId))}
                        className="flex items-center gap-2 px-4 py-2 border-2 border-primary bg-primary/10 hover:bg-primary/20 text-primary text-[11px] font-mono font-bold uppercase tracking-wider transition-all select-none shadow-[2px_2px_0px_black]"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>{t('orchestrator.confirm_direction')}</span>
                      </button>
                    </div>
                  )}

                  {/* Staged orchestration: deliverable verdict bar (brutalist) */}
                  {isSpawn && !msg.isProposal && msg.spawnId && (
                    msg.verdict ? (
                      <div className="mt-4 flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-mono font-bold uppercase tracking-wider text-subtle-foreground select-none">
                        <CheckCircle2 className="w-3 h-3" />
                        <span>{msg.verdict === 'discard' ? t('orchestrator.verdict_discarded') : t('orchestrator.verdict_accepted')}</span>
                      </div>
                    ) : (
                      <div className="mt-4 flex items-center gap-2 flex-wrap">
                        <button
                          onClick={() => onDeliverableVerdict?.('accept', Number(msg.spawnId), msg.messageId)}
                          className="flex items-center gap-1.5 px-3 py-1.5 border-2 border-success bg-success/20 hover:bg-success/40 text-success text-[10px] font-mono font-bold uppercase tracking-wider transition-all select-none"
                        >
                          <CheckCircle2 className="w-3 h-3" />
                          <span>{t('orchestrator.verdict_accept')}</span>
                        </button>
                        <button
                          onClick={() => onDeliverableVerdict?.('redo', Number(msg.spawnId), msg.messageId, msg.taskBrief)}
                          className="flex items-center gap-1.5 px-3 py-1.5 border-2 border-border bg-background hover:border-warning text-muted-foreground hover:text-warning text-[10px] font-mono font-bold uppercase tracking-wider transition-all select-none"
                        >
                          <RefreshCcw className="w-3 h-3" />
                          <span>{t('orchestrator.verdict_redo')}</span>
                        </button>
                        <button
                          onClick={() => onDeliverableVerdict?.('discard', Number(msg.spawnId), msg.messageId)}
                          className="flex items-center gap-1.5 px-3 py-1.5 border-2 border-border bg-background hover:border-danger text-subtle-foreground hover:text-danger text-[10px] font-mono font-bold uppercase tracking-wider transition-all select-none"
                        >
                          <X className="w-3 h-3" />
                          <span>{t('orchestrator.verdict_discard')}</span>
                        </button>
                        {msg.sender === "spawn" && msg.runId != null && (
                          <button
                            type="button"
                            className="msg__replay-btn"
                            onClick={() => setReplayRunId(msg.runId ?? null)}
                          >
                            查看回放
                          </button>
                        )}
                      </div>
                    )
                  )}
                </div>
              );
            }

            // Linear Minimal Theme Rendering (Sleek layout, precise margins, subtle borders, thin colors)
            if (currentStyle === 'linear') {
              if (isUser) {
                return (
                  <div key={msg.id} className="flex justify-end text-[12px]">
                    <div className="max-w-[68%]">
                      <div
                        className="px-4 py-2.5 text-foreground text-[12.5px] leading-relaxed font-sans whitespace-pre-line"
                        style={{
                          background: 'rgba(120,140,170,0.10)',
                          border: '1px solid rgba(255,255,255,0.08)',
                          borderRadius: '12px 12px 4px 12px',
                        }}
                      >
                        {msg.text}
                      </div>
                      <div className="text-[9px] text-subtle-foreground font-mono mt-1 text-right select-none">{msg.timestamp}</div>
                    </div>
                  </div>
                );
              }

              return (
                <div key={msg.id} className="text-[12px] space-y-2">
                  {/* Sender Metadata Row */}
                  <div className="flex items-center gap-2 select-none text-[11px]">
                    {isArslan
                      ? <img src="/arslan-mark.png" alt="Arslan" className="w-5 h-5 object-contain select-none arslan-mark" draggable={false} />
                      : isUser
                      ? <span className="text-subtle-foreground flex items-center justify-center"><SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5" /></span>
                      : <SpawnAvatar seed={msg.senderName} size={18} />}
                    <span className="font-bold text-foreground">{msg.senderName}</span>
                    <span className="text-subtle-foreground font-mono">•</span>
                    <span className="text-subtle-foreground font-mono">{msg.timestamp}</span>
                    {isArslan && (
                      <span className="text-[9px] bg-surface-raised text-primary px-2 py-0.5 rounded font-mono uppercase">
                        Orchestrator
                      </span>
                    )}
                    {!isArslan && !isUser && (
                      <span className="text-[9px] bg-background text-primary px-2 py-0.5 rounded font-mono uppercase">
                        Spawn • Core
                      </span>
                    )}
                  </div>

                  {/* Body Content */}
                  <Markdown className="text-muted-foreground font-sans leading-relaxed text-[12.5px] pl-5 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">{msg.text}</Markdown>

                  {/* Linear clean route badge */}
                  {msg.routedTo && (
                    <div className="text-[10px] text-subtle-foreground font-mono flex items-center gap-1.5 pl-5">
                      <span className="text-subtle-foreground">→ Routed process to:</span>
                      <span className="text-primary hover:underline font-bold select-none cursor-pointer">
                        {msg.routedTo.spawnName}
                      </span>
                    </div>
                  )}

                  {/* Linear Minimal Spawn intro */}
                  {msg.spawnIntro && (
                    <div className="pl-5 pt-2">
                      <div className="border border-border bg-background rounded-lg p-3 space-y-2.5 max-w-xl">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-foreground text-[11px]">{msg.spawnIntro.name} Spawn Registry</span>
                          </div>
                          <span className="text-[9px] bg-surface text-muted-foreground px-2 py-0.5 rounded font-mono">active</span>
                        </div>
                        <div className="text-[10px] text-subtle-foreground">{t('orchestrator.capabilities_matrix')}</div>
                        <div className="flex flex-wrap gap-1">
                          {msg.spawnIntro.tools.map(toolId => (
                            <span key={toolId} className="text-[10px] bg-surface text-muted-foreground px-2 py-0.5 rounded">
                              {toolId}
                            </span>
                          ))}
                          {msg.spawnIntro.skills.map(skillId => (
                            <span key={skillId} className="text-[10px] bg-primary/15 text-primary px-2 py-0.5 rounded">
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
                      <div className="border border-border bg-background/50 rounded-lg p-2 max-w-xl font-mono text-[10.5px]">
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                          <Wrench className="w-3.5 h-3.5 text-primary" />
                          <span>Standard Executor tool {msg.toolActivity.toolName}:</span>
                          <span className="text-subtle-foreground bg-surface px-1.5 py-0.5 rounded uppercase tracking-wider text-[8px]">OK</span>
                        </div>
                        <div className="mt-1 text-subtle-foreground pl-5">
                          {msg.toolActivity.action}
                        </div>
                        <div className="mt-1 pl-5 text-primary">
                          Summary Outcome: {msg.toolActivity.outputSummary}
                        </div>
                        {/* 🔒 SECURITY: artifactSvg is populated ONLY from the backend render_chart tool_result
                            frame (arslanStore), NEVER from LLM message text. Do not render SVG from any other source. */}
                        {msg.toolActivity?.artifactSvg && (
                          <div className="tool-chart" dangerouslySetInnerHTML={{ __html: msg.toolActivity.artifactSvg }} />
                        )}
                      </div>
                    </div>
                  )}

                  {/* Linear Minimal Escalation status */}
                  {msg.escalation && (
                    <div className="pl-5 pt-2">
                      <div className="border border-danger/40 bg-danger/5 border-l-2 border-l-danger rounded-r-lg p-3 max-w-xl">
                        <div className="flex items-center gap-1 text-[10.5px] text-danger font-mono font-bold uppercase select-none">
                          <AlertTriangle className="w-3.5 h-3.5" />
                          <span>Escalation Exception - Spawn Access Lockout ({msg.escalation.status})</span>
                        </div>
                        <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">{msg.escalation.issue}</p>
                        {msg.escalation.resolutionMessage && (
                          <p className="mt-2 text-danger text-[10px] font-mono whitespace-pre-wrap pl-2 bg-background/40 py-1.5 rounded">{msg.escalation.resolutionMessage}</p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Staged orchestration: proposal confirm button */}
                  {isSpawn && msg.isProposal && msg.spawnId && (
                    <div className="pl-5 pt-2">
                      <button
                        onClick={() => onConfirmDirection?.(Number(msg.spawnId))}
                        className="flex items-center gap-2 px-4 py-2 bg-primary/10 hover:bg-primary/20 border border-primary/40 hover:border-primary/70 text-primary text-[11px] font-mono font-bold uppercase tracking-wider rounded-lg transition-all select-none"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>{t('orchestrator.confirm_direction')}</span>
                      </button>
                    </div>
                  )}

                  {/* Staged orchestration: deliverable verdict bar */}
                  {isSpawn && !msg.isProposal && msg.spawnId && (
                    msg.verdict ? (
                      <div className="pl-5 pt-2 flex items-center gap-1.5 text-[10px] font-mono font-bold uppercase tracking-wider text-subtle-foreground select-none">
                        <CheckCircle2 className="w-3 h-3" />
                        <span>{msg.verdict === 'discard' ? t('orchestrator.verdict_discarded') : t('orchestrator.verdict_accepted')}</span>
                      </div>
                    ) : (
                      <div className="pl-5 pt-2 flex flex-wrap items-center gap-1.5">
                        <button
                          onClick={() => onDeliverableVerdict?.('accept', Number(msg.spawnId), msg.messageId)}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-success/20 hover:bg-success/40 border border-success/40 hover:border-success/70 text-success text-[10px] font-mono font-bold uppercase tracking-wider rounded-lg transition-all select-none"
                        >
                          <CheckCircle2 className="w-3 h-3" />
                          <span>{t('orchestrator.verdict_accept')}</span>
                        </button>
                        <button
                          onClick={() => onDeliverableVerdict?.('redo', Number(msg.spawnId), msg.messageId, msg.taskBrief)}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-surface-raised border border-border-strong/60 hover:border-warning/30 text-muted-foreground hover:text-warning text-[10px] font-mono font-bold uppercase tracking-wider rounded-lg transition-all select-none"
                        >
                          <RefreshCcw className="w-3 h-3" />
                          <span>{t('orchestrator.verdict_redo')}</span>
                        </button>
                        <button
                          onClick={() => onDeliverableVerdict?.('discard', Number(msg.spawnId), msg.messageId)}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-surface hover:bg-danger/20 border border-border-strong/60 hover:border-danger/40 text-subtle-foreground hover:text-danger text-[10px] font-mono font-bold uppercase tracking-wider rounded-lg transition-all select-none"
                        >
                          <X className="w-3 h-3" />
                          <span>{t('orchestrator.verdict_discard')}</span>
                        </button>
                        {msg.sender === "spawn" && msg.runId != null && (
                          <button
                            type="button"
                            className="msg__replay-btn"
                            onClick={() => setReplayRunId(msg.runId ?? null)}
                          >
                            查看回放
                          </button>
                        )}
                      </div>
                    )
                  )}
                </div>
              );
            }

            return null;
          })
        )}
        {/* LLM error banner: shown when the backend emits an error frame (e.g. LLM timeout, auth failure) */}
        {llmError && (
          <div className="flex gap-3 items-start py-2 select-none">
            <img src="/arslan-mark.png" alt="Arslan" className="w-7 h-7 object-contain select-none shrink-0 arslan-mark mt-0.5" draggable={false} />
            <div className="flex items-start gap-2 px-3 py-2.5 bg-danger/10 border border-danger/30 rounded-2xl rounded-tl-none max-w-2xl">
              <AlertTriangle className="w-3.5 h-3.5 text-danger shrink-0 mt-0.5" />
              <div className="flex flex-col gap-1 min-w-0">
                <span className="text-[11px] text-danger font-semibold">{t('chat.llm_error_title', 'Model error')}</span>
                <span className="text-[11px] text-danger/80 font-mono break-words">{llmError}</span>
              </div>
              <button
                onClick={clearLlmError}
                className="ml-auto shrink-0 p-0.5 rounded hover:bg-danger/20 text-danger/60 hover:text-danger transition-colors"
                aria-label="Dismiss error"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          </div>
        )}
        {/* Thinking indicator: shown from send until first real content chunk.
            We no longer gate on !streaming because stream_start begins streaming
            with empty text (slow models like Gemini 2.5 Pro have a long delay
            before the first token). thinking stays true until stream_chunk clears
            it, so the dots show through the blank gap. */}
        {thinking && (
          <div className="flex gap-3 items-center py-2 select-none">
            <img src="/arslan-mark.png" alt="Arslan" className="w-7 h-7 object-contain select-none shrink-0 arslan-mark" draggable={false} />
            <div className="flex items-center gap-1.5 px-3 py-2 bg-surface/80 border border-border-strong rounded-2xl rounded-tl-none">
              <span className="text-[11px] text-muted-foreground font-mono">{t('chat.thinking')}</span>
              <span className="flex gap-0.5 ml-1">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="w-1 h-1 rounded-full bg-primary/70 animate-bounce"
                    style={{ animationDelay: `${i * 150}ms` }}
                  />
                ))}
              </span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input Message Form Panel */}
      {chatHistory.length > 0 && (
        <footer className="p-4 border-t border-border bg-background/80 backdrop-blur shrink-0 z-10 select-none">
          <div className="max-w-4xl mx-auto">
            <AttachBar key={attachKey} onChange={setAttachments} />
          </div>
          <form onSubmit={handleSendMessage} className="max-w-4xl mx-auto flex items-center gap-2 relative">
            <input
              id="chat-message-input"
              type="text"
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder={t('orchestrator.placeholder_chat')}
              className="w-full bg-surface border border-border hover:border-border-strong focus:border-primary/60 focus:ring-1 focus:ring-ring/30 rounded-xl px-4 py-3 text-xs text-foreground placeholder-subtle-foreground focus:outline-none pr-12 transition-all font-sans"
            />
            <button
              id="chat-send-submit"
              type="submit"
              disabled={!inputValue.trim()}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-primary text-primary-foreground hover:bg-primary-hover disabled:bg-surface-raised disabled:text-subtle-foreground disabled:opacity-50 font-bold uppercase rounded-lg transition-all"
            >
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>
          <div className="flex items-center justify-center gap-6 mt-2 text-[10px] text-subtle-foreground font-mono">
            <span>{t('orchestrator.footer_hint')}</span>
            <span>•</span>
            <span className="flex items-center gap-1.5 font-sans">
              <Layers className="w-3.5 h-3.5 text-subtle-foreground" />
              {t('orchestrator.footer_sandboxed')}
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
        <div className="w-[45%] border-l border-border bg-sidebar flex flex-col h-full animate-slide-in-right relative overflow-hidden shrink-0 z-20">
          {/* Sandbox Top Header */}
          <div className="h-[52px] border-b border-border px-4.5 bg-background/80 backdrop-blur flex items-center justify-between select-none shrink-0">
            <div className="flex items-center gap-2.5">
              <SpawnAvatar seed={spawn.name} size={28} />
              <div>
                <div className="flex items-center gap-1.5 leading-none">
                  <span className="text-xs font-bold text-foreground font-sans">{spawn.name}</span>
                  <span className="text-[9px] bg-primary/10 text-primary px-2 py-0.5 rounded font-mono font-bold uppercase">
                    Sandbox
                  </span>
                </div>
                <span className="text-[9px] text-primary font-mono mt-1 block uppercase tracking-wider">{spawn.domain}</span>
              </div>
            </div>

            <button 
              onClick={() => setSplitSpawnId(null)}
              className="p-1 text-muted-foreground hover:text-foreground bg-surface border border-border/80 rounded hover:bg-background/30"
              title="Minimize Sandbox"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Sandbox Content: Coming Soon — dispatch + draft backend not yet wired */}
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-4 select-none">
            <SpawnAvatar seed={spawn.name} size={48} className="mx-auto" />
            <div className="space-y-2">
              <div className="flex items-center justify-center gap-2">
                <span className="text-xs font-bold text-foreground font-sans">{spawn.name} Sandbox</span>
                <span className="text-[9px] font-mono bg-primary/10 text-primary px-2 py-0.5 rounded uppercase tracking-wider">{t('orchestrator.coming_soon_badge')}</span>
              </div>
              <p className="text-[11px] text-subtle-foreground font-sans leading-relaxed max-w-xs">
                {t('orchestrator.sandbox_coming_soon_desc')}
              </p>
            </div>
            <button
              onClick={() => setSplitSpawnId(null)}
              className="mt-2 px-4 py-1.5 bg-transparent hover:bg-foreground/[0.04] text-muted-foreground hover:text-foreground text-[10px] rounded-xl border border-border/80 font-mono uppercase tracking-wider transition-all"
            >
              {t('orchestrator.close_panel')}
            </button>
          </div>
        </div>
      );
    })()}
  </div>

  {replayRunId != null && (
    <div className="run-replay-overlay" onClick={() => setReplayRunId(null)}>
      <div className="run-replay-overlay__panel" onClick={(e) => e.stopPropagation()}>
        <RunReplay runId={replayRunId} onClose={() => setReplayRunId(null)} />
      </div>
    </div>
  )}

  {showEvalSummary && (
    <div className="run-replay-overlay" onClick={() => setShowEvalSummary(false)}>
      <div className="run-replay-overlay__panel" onClick={(e) => e.stopPropagation()}>
        <EvalSummary onClose={() => setShowEvalSummary(false)} />
      </div>
    </div>
  )}
</div>
);
}
