import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { DEFAULT_SETTINGS } from './data';
import { Spawn, Message, MessageAttachment, AppSettings } from './types';
import { useSpawnStore } from './stores/spawnStore';
import { useArslanStore } from './stores/arslanStore';
import { useSettingsStore } from './stores/settingsStore';
import { api } from './api/client';
import { shouldAutoTitle, maybeAutoTitle } from './lib/autoTitle';
import { restoreThreads, persistThreads, consumeFreshSessionFlag } from './lib/sessionPersistence';
import { toUiSpawn, toUiSettings, toUiMessages } from './api/adapters';
import type { ArslanServerMessage, ProviderOption, ProviderConfig } from './api/client.types';
import { listProviderConfigs } from './api/client';
import { useWebSocket } from './hooks/useWebSocket';
import { useBackendStatus } from './hooks/useBackendStatus';
import Sidebar from './components/Sidebar';
import OrchestratorChat from './components/OrchestratorChat';
import SpawnDirectChat from './components/SpawnDirectChat';
import SpawnsDashboard from './components/SpawnsDashboard';
import SpawnStudio from './components/SpawnStudio';
import SettingsScreen from './components/SettingsScreen';
import Capabilities from './components/Capabilities';
import { X, Sparkles, Cpu, Sliders, Layers, Terminal, ShieldAlert, Network, Wifi, Settings2, ChevronRight, ChevronLeft, Plus, Play, CheckCircle2, LayoutGrid, Paintbrush, Wrench, Brain } from 'lucide-react';
import { getIcon } from './components/iconMap';
import { SpawnAvatar } from './components/SpawnAvatar';
import { ThemeApplier } from './components/ThemeApplier';
import { LedgerRow } from './components/LedgerRow';
import SuggestCreateCard from './components/SuggestCreateCard';
import SuggestUpdateCard from './components/SuggestUpdateCard';
import GapFillModal, { type GapFillKind, type GapFillResult } from './components/GapFillModal';
import StaffingPickerCard from './components/StaffingPickerCard';
import RunCommandCard from './components/RunCommandCard';
import RailMcpList, { type McpServerInfo } from './components/RailMcpList';
import SpawnRailKnowledge from './components/SpawnRailKnowledge';
import EvalDock from './components/EvalDock';
import KnowledgeOrrery from './components/orrery/KnowledgeOrrery';
import OrreryDetailPanel from './components/orrery/OrreryDetailPanel';
import { useKnowledgeGraph } from './hooks/useKnowledgeGraph';
import type { OrreryNodeIn } from './components/orrery/orreryLayout';
import WorkingPulse from './components/WorkingPulse';

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
  const { t } = useTranslation();
  // Backend reachability — polled every 10s, drives honest offline states
  const backendStatus = useBackendStatus();

// Navigation Section: 'arslan' | 'spawn' | 'ledger' | 'capabilities' | 'brain' | 'settings'
  const [activeSection, setActiveSection] = useState<'arslan' | 'spawn' | 'ledger' | 'capabilities' | 'brain' | 'settings'>('arslan');
  const [panelView, setPanelView] = useState<'default' | 'editor'>('default');

  // Custom states for style variations (specifically asked in prompt)
  const [currentChatStyle, setCurrentChatStyle] = useState<'quartz' | 'brutalist' | 'linear'>('linear');

  // Control Center Right Drawer Toggle state for redesigned grand layout frame
  const [showControlPanel, setShowControlPanel] = useState<boolean>(true);

  // ── Orchestrator threads — declared early so activeThreadId is available for
  // the WS hook below (hooks must be called in a consistent order).
  // Restore the persisted thread list + active id on init (resume last
  // conversation, Claude/Gemini-style). Never reintroduce a literal
  // "thread-default"; on first run / post-wipe we get one fresh "New Session".
  const restoredInit = useRef(restoreThreads()).current;
  const [threads, setThreads] = useState<ArslanThread[]>(restoredInit.threads);
  const [activeThreadId, setActiveThreadId] = useState<string>(restoredInit.activeThreadId);

  // ── Session-ephemeral roster: detect a FRESH app session (absent on a brand-new
  // tab/app launch, present across same-tab reloads). Computed exactly once.
  const freshSession = useRef(consumeFreshSessionFlag()).current;
  // The thread id that was resumed on this fresh load — the ONLY thread whose
  // roster we reset (not threads the user later switches to or creates).
  const resumedThreadId = useRef(restoredInit.activeThreadId);
  // Guard so the one-shot roster_reset fires once per fresh session.
  const rosterResetSent = useRef(false);

  // ── Auto-title: track which threads have already received a generated title
  // so we never regenerate on re-renders or subsequent messages. Restored
  // threads already have real titles → seed them so the auto-title effect
  // doesn't re-title them.
  const titledThreadIds = useRef<Set<string>>(
    new Set(restoredInit.threads.map((t) => t.id)),
  );

  // Persist threads + active id whenever either changes (history is dropped).
  useEffect(() => {
    persistThreads(threads, activeThreadId);
  }, [threads, activeThreadId]);

  // ── Stage B: Orchestrator chat live WS ─────────────────────────────────────
  // The store holds all thread items; we derive UI messages from it.
  const arslanItems = useArslanStore((s) => s.items);
  const arslanStreaming = useArslanStore((s) => s.streaming);
  const arslanStreamingText = useArslanStore((s) => s.streamingText);
  // Live roster from backend roster_update frames
  const roster = useArslanStore((s) => s.roster);
  // suggest_create state — rendered as an inline card in the orchestrator area
  const suggestion = useArslanStore((s) => s.suggestion);
  const suggestionTaskBrief = useArslanStore((s) => s.suggestionTaskBrief);
  const suggestionOverlaps = useArslanStore((s) => s.suggestionOverlaps);
  const dismissSuggestion = useArslanStore((s) => s.dismissSuggestion);
  const pendingUpdate = useArslanStore((s) => s.pendingUpdate);
  const dismissUpdate = useArslanStore((s) => s.dismissUpdate);
  // propose_invite state — confirmation card before joining a spawn
  const pendingInvite = useArslanStore((s) => s.pendingInvite);
  const clearPendingInvite = useArslanStore((s) => s.clearPendingInvite);
  // propose_staffing state — candidate picker card
  const pendingStaffing = useArslanStore((s) => s.pendingStaffing);
  const clearPendingStaffing = useArslanStore((s) => s.clearPendingStaffing);
  // propose_run_command state — per-command confirmation card
  const pendingCommand = useArslanStore((s) => s.pendingCommand);
  const clearPendingCommand = useArslanStore((s) => s.clearPendingCommand);
  // Returns true if a spawn (identified by its UI string id) is in the current roster
  const isRosterMember = (spawnId: string) => roster.some((m) => m.spawnId === Number(spawnId));

  // Handler for incoming WS frames — routes to the proven store logic
  const handleArslanFrame = useCallback((raw: unknown) => {
    useArslanStore.getState().handleFrame(raw as ArslanServerMessage);
  }, []);

  // Stable ref to wsSend so handleWsOpen (fired from inside the socket's onOpen)
  // can send without re-subscribing the socket on every render. Assigned after
  // the hook below; read only at call time inside the open handler.
  const wsSendRef = useRef<((obj: unknown) => void) | null>(null);

  // One-shot roster reset on a fresh app session: when the resumed thread's WS
  // connection opens, clear that conversation's (stale, accumulated) roster so it
  // starts empty. Guarded to fire exactly once, and ONLY for the initially
  // resumed thread — NOT when the user later switches threads or starts a new
  // session within the same tab session. A normal same-tab reload (freshSession
  // === false) never resets.
  const handleWsOpen = useCallback((openedPath: string) => {
    if (!freshSession || rosterResetSent.current) return;
    const expectedPath = `/ws/arslan/${resumedThreadId.current}`;
    if (openedPath !== expectedPath) return;
    rosterResetSent.current = true;
    wsSendRef.current?.({ type: 'roster_reset', conversation_id: resumedThreadId.current });
  }, [freshSession]);

  // Connect to the live orchestrator WebSocket using the active thread's id as
  // the conversation_id. useWebSocket reconnects automatically when the URL
  // changes (path is in its effect dep array), so switching threads reconnects.
  const { send: wsSend } = useWebSocket(`/ws/arslan/${activeThreadId}`, handleArslanFrame, { onOpen: handleWsOpen });
  wsSendRef.current = wsSend;

  // Derived UI messages from the live store
  const liveOrchestratorHistory: Message[] = toUiMessages(arslanItems).map((m) =>
    m.text.startsWith('__SPAWN_UPDATED__:')
      ? { ...m, text: t('orchestrator.update_done', { name: m.text.slice('__SPAWN_UPDATED__:'.length) }) }
      : m,
  );

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

  // ── Auto-title effect: fires when the live history gains its first assistant
  // reply. Captures the active thread id at effect time (stable closure via
  // dependency array) so a mid-stream thread switch never titles the wrong thread.
  useEffect(() => {
    // Build a synthetic thread snapshot from the live store history so we can
    // reuse the pure shouldAutoTitle helper.
    const syntheticThread = {
      title: threads.find((t) => t.id === activeThreadId)?.title ?? 'New Session',
      history: liveOrchestratorHistory,
    };
    if (
      !titledThreadIds.current.has(activeThreadId) &&
      shouldAutoTitle(syntheticThread)
    ) {
      // Mark immediately so concurrent renders don't fire a second call.
      titledThreadIds.current.add(activeThreadId);
      const capturedThreadId = activeThreadId;
      maybeAutoTitle(
        capturedThreadId,
        { history: liveOrchestratorHistory },
        (msg, reply) => api.generateTitle(msg, reply),
        (tid, title) => {
          setThreads((prev) =>
            prev.map((t) => (t.id === tid ? { ...t, title } : t)),
          );
        },
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveOrchestratorHistory, activeThreadId]);

  // Send a user message to the live backend
  const sendOrchestratorMessage = useCallback((text: string, attached?: { context: string; names: string[]; display?: MessageAttachment[] }) => {
    // display = session-only echo for the sent bubble (image thumbnails / doc chips);
    // only text-bearing attachments ride to the backend as attached_context below.
    // Sending a new message without acting on a pending proposal card = implicitly
    // dismiss it, so un-acted suggest_create / propose_invite / propose_staffing /
    // suggest_update cards clear when the user moves on instead of stacking forever.
    useArslanStore.getState().dismissAllPending();
    useArslanStore.getState().addUserMessage(text, attached?.display);
    useArslanStore.getState().setThinking(true);
    wsSend({
      type: 'user_message',
      content: text,
      ...(attached?.context ? { attached_context: attached.context, attached_names: attached.names } : {}),
    });
  }, [wsSend]);

  // Composer policy pill: flip the shell confirm posture at task start (Claude-Code-style).
  // Optimistic local update + a best-effort PUT reusing the Settings write path.
  const handleShellPolicyChange = useCallback((policy: 'ask_all' | 'ask_risky') => {
    setSettings((prev) => ({ ...prev, shellConfirmPolicy: policy }));
    api.updateSettings({ shell_confirm_policy: policy }).catch(() => {
      /* best-effort — the pill already reflects the intended posture */
    });
  }, []);

  // Best-effort: flush a session_ended for the active thread if the page is closed/hidden
  // without an explicit thread switch, so the last conversation still gets its background
  // distill. pagehide fires on tab close and bfcache navigation; the WS send is best-effort.
  useEffect(() => {
    const onPageHide = () => {
      if (activeThreadId) wsSend({ type: 'session_ended', conversation_id: activeThreadId });
    };
    window.addEventListener('pagehide', onPageHide);
    return () => window.removeEventListener('pagehide', onPageHide);
  }, [wsSend, activeThreadId]);

  const [activeSpawnChatId, setActiveSpawnChatId] = useState<string>('');

  // Refine handoff: 精修 now opens a SandboxPanel inside OrchestratorChat (not full-nav).
  // refineCtx + setRefineCtx remain for SpawnDirectChat's onFinalize wiring below.
  const [refineCtx, setRefineCtx] = useState<{ spawnId: number; messageId?: number; spawnName: string; deliverable: string } | null>(null);

  // Shared application state databases
  // Spawns Ledger: initialized empty; populated on mount from live spawn store (Stage B)
  const [spawns, setSpawns] = useState<Spawn[]>([]);
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);

  // Stage B: provider/search-provider catalogs for Settings dropdowns (live from backend)
  const [llmProviders, setLlmProviders] = useState<ProviderOption[]>([]);
  const [searchProviders, setSearchProviders] = useState<string[]>([]);
  const [providerConfigs, setProviderConfigs] = useState<ProviderConfig[]>([]);

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
      // Also push into settingsStore so child components can read live settings
      useSettingsStore.getState().setSettings(backendSettings);
    }).catch(() => {
      // backend unavailable — keep DEFAULT_SETTINGS
    });

    // Load LLM provider catalog
    api.listProviders().then(setLlmProviders).catch(() => {});

    // Load search provider catalog
    api.listSearchProviders().then(setSearchProviders).catch(() => {});

    // Load multi-model provider configs
    listProviderConfigs().then(setProviderConfigs).catch(() => {});
  }, []);

  // MCP servers state — fetched once on mount, used in the diagnostics rail
  const [mcpServers, setMcpServers] = useState<McpServerInfo[]>([]);
  useEffect(() => { api.listMcpServers().then(setMcpServers).catch(() => setMcpServers([])); }, []);

  const [selectedSpawnId, setSelectedSpawnId] = useState<string | null>(null);

  // ── Second Brain: live knowledge graph + the node whose detail panel is open.
  const { graph: knowledgeGraph, loading: knowledgeLoading, error: knowledgeError } = useKnowledgeGraph();
  const [selectedNode, setSelectedNode] = useState<OrreryNodeIn | null>(null);

  // Spawn Studio — the roomy create/configure panel (replaces SpawnEditPopup +
  // the old full-screen SpawnEditor). `edit` carries a numeric spawn id.
  const [studio, setStudio] = useState<{ mode: 'edit' | 'create'; spawnId?: number } | null>(null);

  // Refresh the spawn list/roster after a studio save/create/delete so the rail
  // and ledger reflect the change.
  const refreshSpawnsList = useCallback(async () => {
    try {
      const fresh = await api.listSpawns();
      setSpawns(fresh.map(toUiSpawn));
    } catch { /* best-effort refresh */ }
  }, []);

  // New Spawn Creation modal/overlay state
  // Gap-fill: a focused, human-confirmed acquisition modal whose result is
  // piped back to SuggestCreateCard via a stored promise resolver (F4).
  const [gapFill, setGapFill] = useState<{ kind: GapFillKind; gap: string } | null>(null);
  const gapFillResolver = useRef<((r: GapFillResult | null) => void) | null>(null);

  const handleFillGap = useCallback<NonNullable<React.ComponentProps<typeof SuggestCreateCard>['onFillGap']>>(
    (kind, gap) => {
      // request_grant is a RUN-TIME escalation, not a create-time action: keep
      // the gap, no acquisition here (the card shows a defer note via title).
      if (kind === 'request_grant') return Promise.resolve(null);
      return new Promise<GapFillResult | null>((resolve) => {
        gapFillResolver.current = resolve;
        setGapFill({ kind, gap });
      });
    },
    [],
  );

  const closeGapFill = useCallback((result: GapFillResult | null) => {
    gapFillResolver.current?.(result);
    gapFillResolver.current = null;
    setGapFill(null);
  }, []);

  // If the suggestion card goes away (create/dismiss/refine or any external
  // dismissSuggestion) while a gap-fill modal is open, the card unmounts — so
  // resolve the pending promise null and close the modal too. Prevents an
  // orphaned modal resolving into a dead component / a stuck resolver.
  useEffect(() => {
    if ((!suggestion || activeSection !== 'arslan') && (gapFill || gapFillResolver.current)) {
      closeGapFill(null);
    }
  }, [suggestion, activeSection, gapFill, closeGapFill]);

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
    const nextThreadNumber = threads.filter(t => !t.title.includes('New Session')).length + 1;
    const newThread: ArslanThread = {
      id: threadId,
      title: `Orchestration thread #${nextThreadNumber}`,
      memberSpawnIds: [],
      history: []
    };

    // Signal the OLD conversation ended (backend may background-distill prefs).
    // wsSend targets the still-current /ws/arslan/${activeThreadId} connection.
    if (activeThreadId) wsSend({ type: 'session_ended', conversation_id: activeThreadId });

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

  // Handle opening the Spawn Studio (edit mode) for a specific spawn.
  const handleEditSpawnEquipment = (spawnId: string) => {
    setStudio({ mode: 'edit', spawnId: Number(spawnId) });
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
    const numericId = Number(spawnId);
    if (isRosterMember(spawnId)) {
      if (window.confirm(t('ledger.kickConfirm'))) {
        wsSend({ type: 'roster_kick', spawn_id: numericId });
      }
    } else {
      wsSend({ type: 'roster_invite', spawn_id: numericId });
    }
  };

  // Calculate current active histories
  const activeThread = threads.find(t => t.id === activeThreadId) || threads[0];
  const activeSpawn = spawns.find(s => s.id === activeSpawnChatId) || spawns[0];

  // Compute capability registries for current dialog / context
  const getContextCapabilities = () => {
    let title = "Global Capability Sandbox";
    let activeMembers: Spawn[] = [];

    if (activeSection === 'arslan') {
      activeMembers = spawns.filter((s) => isRosterMember(s.id));
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
    <div className="flex w-screen h-screen bg-background text-foreground overflow-hidden font-sans antialiased">
      <ThemeApplier />

      {/* Sidebar with macOS window decorations */}
      <Sidebar
        threads={threads}
        activeThreadId={activeThreadId}
        onSelectThread={(id) => {
          // Signal the OLD conversation ended (backend may background-distill prefs).
          // wsSend targets the still-current /ws/arslan/${activeThreadId} connection.
          if (activeThreadId) wsSend({ type: 'session_ended', conversation_id: activeThreadId });
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
        onCompleteChat={async (id) => {
          await api.completeChat(Number(id));
          // Refetch spawn list so hasActiveChat reflects the completed state
          const freshSpawns = await api.listSpawns();
          setSpawns(freshSpawns.map(toUiSpawn));
        }}
        backendStatus={backendStatus}
      />

      {/* Main Workspace Frame container with glass window feel */}
      <main className="flex-1 flex flex-col h-full bg-background relative">
      {/* Redesigned Grand Multi-column Frame layout */}
      <div className="flex-1 flex h-full relative">

        {/* Main Workspace Frame container */}
        <main className="flex-1 flex flex-col h-full bg-background relative overflow-hidden">
          {/* Top Bar for overall macro layout */}
          <div className="h-14 border-b border-border px-6 flex items-center justify-between bg-background/40 backdrop-blur-md z-30">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-success"></span>
              <span className="text-[10.5px] font-mono text-muted-foreground capitalize uppercase tracking-wider">
                {t('modal.workspace_label')} <span className="text-foreground font-bold">
                  {activeSection === 'arslan' ? t('modal.workspace_orchestrator', { title: activeThread.title }) :
                   activeSection === 'spawn' ? t('modal.workspace_specialist', { name: activeSpawn?.name || 'Direct Chat' }) :
                   activeSection === 'ledger' ? t('modal.workspace_ledger') :
                   activeSection === 'capabilities' ? t('modal.workspace_capabilities') :
                   activeSection === 'brain' ? t('modal.workspace_brain') : t('modal.workspace_settings')}
                </span>
              </span>
            </div>

            <div className="flex items-center gap-3">


              {/* Toggle Diagnostic Rail button — only where the rail can appear */}
              {!isThreadEmpty && (activeSection === 'arslan' || activeSection === 'spawn') && (
                <button
                  id="toggle-control-panel"
                  onClick={() => setShowControlPanel(!showControlPanel)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 border rounded-lg text-[10.5px] font-mono transition-all uppercase ${
                    showControlPanel
                      ? 'border-primary/30 bg-primary/5 text-primary hover:bg-primary/10'
                      : 'border-border text-muted-foreground hover:text-foreground hover:bg-foreground/[0.02]'
                  }`}
                >
                  <Cpu className="w-3.5 h-3.5" />
                  <span>{showControlPanel ? t('orchestrator.hide_rail') : t('orchestrator.show_rail')}</span>
                </button>
              )}
            </div>
          </div>

          <div className="flex-1 flex flex-col overflow-hidden relative">
            {activeSection === 'arslan' && pendingUpdate && (
              <div className="suggest-create-card-overlay">
                <SuggestUpdateCard
                  spawnName={pendingUpdate.spawnName}
                  current={pendingUpdate.current}
                  changes={pendingUpdate.changes}
                  reason={pendingUpdate.reason}
                  onConfirm={() => {
                    wsSend({ type: 'confirm_update', spawn_id: pendingUpdate.spawnId, changes: pendingUpdate.changes });
                    // card clears on the spawn_updated ack (or stays if an error frame lands)
                  }}
                  onDismiss={() => dismissUpdate()}
                />
              </div>
            )}

            {activeSection === 'arslan' && suggestion && (
              <div className="suggest-create-card-overlay">
                <SuggestCreateCard
                  draft={suggestion}
                  taskBrief={suggestionTaskBrief}
                  overlaps={suggestionOverlaps}
                  onCreate={(finalDraft) => {
                    wsSend({ type: 'confirm_create', draft: finalDraft, task_brief: finalDraft.brief });
                    dismissSuggestion();
                  }}
                  onRefine={() => dismissSuggestion()}
                  onDismiss={() => dismissSuggestion()}
                  onFillGap={handleFillGap}
                />
              </div>
            )}

            {activeSection === 'arslan' && suggestion && gapFill &&
              (gapFill.kind === 'discover_mcp' || gapFill.kind === 'distill_skill') && (
              <GapFillModal
                kind={gapFill.kind}
                gap={gapFill.gap}
                onDone={closeGapFill}
              />
            )}

            {activeSection === 'arslan' && pendingStaffing && (
              <div className="suggest-create-card-overlay">
                <StaffingPickerCard
                  candidates={pendingStaffing.candidates}
                  createDraft={pendingStaffing.createDraft}
                  onInvite={(spawnId) => {
                    wsSend({ type: 'roster_invite', spawn_id: spawnId });
                    clearPendingStaffing();
                  }}
                  onCreateNew={(draft) => {
                    // Open the existing editable SuggestCreateCard with this draft.
                    // Setting suggestion state causes App to render SuggestCreateCard,
                    // whose onCreate sends confirm_create — the existing flow is reused.
                    // Carry task_brief from the gathered staffing slots so the created
                    // spawn receives its first-task context.
                    useArslanStore.setState({
                      suggestion: draft,
                      suggestionTaskBrief: draft.task_brief ?? null,
                      suggestionOverlaps: null,
                    });
                    clearPendingStaffing();
                  }}
                  onDismiss={() => clearPendingStaffing()}
                />
              </div>
            )}

            {activeSection === 'arslan' && pendingCommand && (
              <div className="suggest-create-card-overlay">
                <RunCommandCard
                  callId={pendingCommand.callId}
                  pretty={pendingCommand.pretty}
                  reason={pendingCommand.reason}
                  onConfirm={(callId, remember) => {
                    wsSend({ type: 'confirm_run_command', call_id: callId, remember });
                    clearPendingCommand();
                  }}
                  onCancel={(callId) => {
                    wsSend({ type: 'cancel_run_command', call_id: callId });
                    clearPendingCommand();
                  }}
                />
              </div>
            )}

            {activeSection === 'arslan' && (
              <OrchestratorChat
                chatHistory={orchestratorChatHistory}
                setChatHistory={setChatHistoryForActiveThread}
                onSendMessage={sendOrchestratorMessage}
                spawns={spawns}
                currentStyle={currentChatStyle}
                setCurrentStyle={setCurrentChatStyle}
                activeThread={activeThread}
                hasModel={providerConfigs.length > 0}
                onOpenSettings={() => {
                  setActiveSection('settings');
                  setPanelView('default');
                }}
                onConfirmDirection={(spawnId) => {
                  wsSend({ type: 'confirm_direction', spawn_id: spawnId });
                  // one-shot: disable the confirm button immediately + show the pulse
                  useArslanStore.getState().markProposalConfirmed(spawnId);
                  useArslanStore.getState().setThinking(true);
                }}
                onDeliverableVerdict={(action, spawnId, messageId) => {
                  if (action === 'accept') {
                    wsSend({ type: 'accept_deliverable', spawn_id: spawnId, message_id: messageId });
                  } else if (action === 'discard') {
                    wsSend({ type: 'discard', spawn_id: spawnId, message_id: messageId });
                  }
                }}
                conversationId={activeThreadId}
                pendingInvite={pendingInvite}
                onAcceptInvite={(spawnId) => {
                  wsSend({ type: 'roster_invite', spawn_id: spawnId });
                  clearPendingInvite();
                }}
                onDismissInvite={() => {
                  wsSend({ type: 'dismiss_invite' });
                  clearPendingInvite();
                }}
                shellEnabled={settings.orchestratorShellEnabled}
                shellPolicy={settings.shellConfirmPolicy}
                onShellPolicyChange={handleShellPolicyChange}
              />
            )}

            {activeSection === 'spawn' && activeSpawn && (
              <SpawnDirectChat
                key={activeSpawn.id}
                spawn={activeSpawn}
                currentStyle={currentChatStyle}
                refineDeliverable={refineCtx && String(refineCtx.spawnId) === activeSpawnChatId ? refineCtx.deliverable : null}
                onFinalize={(content) => {
                  if (!refineCtx) return;
                  wsSend({ type: 'finalize_refinement', spawn_id: refineCtx.spawnId, message_id: refineCtx.messageId ?? null, content });
                  setRefineCtx(null);
                }}
              />
            )}

            {activeSection === 'ledger' && panelView === 'default' && (
              <SpawnsDashboard
                spawns={spawns}
                selectedSpawnId={selectedSpawnId}
                setSelectedSpawnId={setSelectedSpawnId}
                onEditEquipment={handleEditSpawnEquipment}
                onCreateSpawnClick={() => setStudio({ mode: 'create' })}
                onOpenDirectChat={(spawnId) => {
                  setActiveSpawnChatId(spawnId);
                  setActiveSection('spawn');
                  setPanelView('default');
                }}
                setSpawns={setSpawns}
                setThreads={setThreads}
                activeThreadId={activeThreadId}
                backendStatus={backendStatus}
              />
            )}

            {activeSection === 'capabilities' && (
              <Capabilities />
            )}

            {activeSection === 'brain' && (
              <div className="flex-1 flex h-full overflow-hidden relative">
                <div className="flex-1 relative h-full">
                  {knowledgeLoading ? (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <WorkingPulse
                        phrases={[t('brain.loading')]}
                        className="text-[11px] text-subtle-foreground uppercase tracking-widest"
                      />
                    </div>
                  ) : knowledgeError ? (
                    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-8 text-center select-none">
                      <span className="text-lg">⚠️</span>
                      <p className="text-[11px] font-mono text-muted-foreground max-w-sm leading-relaxed">
                        {t('brain.error')}
                      </p>
                    </div>
                  ) : knowledgeGraph.nodes.length <= 1 ? (
                    <div className="absolute inset-0 flex items-center justify-center px-8 text-center select-none">
                      <p className="text-[11px] font-mono text-subtle-foreground max-w-sm leading-relaxed">
                        {t('brain.empty')}
                      </p>
                    </div>
                  ) : (
                    <KnowledgeOrrery
                      nodes={knowledgeGraph.nodes}
                      edges={knowledgeGraph.edges}
                      onSelect={setSelectedNode}
                      className="w-full h-full"
                    />
                  )}
                </div>

                {selectedNode && (
                  <OrreryDetailPanel
                    node={selectedNode}
                    nodes={knowledgeGraph.nodes}
                    edges={knowledgeGraph.edges}
                    onSelect={setSelectedNode}
                  />
                )}
              </div>
            )}

            {activeSection === 'settings' && (
              <SettingsScreen
                settings={settings}
                setSettings={setSettings}
                llmProviders={llmProviders}
                searchProviders={searchProviders}
                backendStatus={backendStatus}
                providerConfigs={providerConfigs}
                onProviderConfigsChange={setProviderConfigs}
              />
            )}
          </div>
        </main>

        {/* Collapsible Panel Section in Overall Layout Redesign */}
        {/* Diagnostics rail is a CONVERSATION panel — only show it on the orchestrator
            chat + spawn direct chat. On Settings/Ledger/Capabilities it has no relevant
            context (and would leak the chat-only "Spawns Pipeline"), so hide it. */}
        {showControlPanel && !isThreadEmpty && (activeSection === 'arslan' || activeSection === 'spawn') && (
          <aside className="w-80 border-l border-border bg-sidebar flex flex-col justify-between h-full select-none relative z-20 animate-slide-in-right overflow-y-auto">
            {/* Top diagnostic state */}
            <div className="p-5 border-b border-border/50 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 bg-primary rounded-full animate-ping"></span>
                  <span className="text-[10px] font-mono tracking-widest text-primary font-bold uppercase">{t('rail.diagnostics_engine')}</span>
                </div>
                <button
                  onClick={() => setShowControlPanel(false)}
                  className="text-subtle-foreground hover:text-foreground transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Ambient stats box */}
              <div className="bg-background/50 border border-border/80 rounded-xl p-3.5 space-y-2 text-[11px] font-mono">
                <div className="flex justify-between">
                  <span className="text-subtle-foreground">{t('rail.routing_agent')}</span>
                  <span className="text-primary">{settings?.llmStrategy ?? '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-subtle-foreground">{t('rail.roster_count')}</span>
                  <span className="text-foreground">{currentCaps.members.length}</span>
                </div>
              </div>
            </div>

            {/* Active Workspace Capability Registries / MCP, Tools, Skills */}
            {currentCaps.members.length > 0 && (
              <div className="p-5 border-b border-border/50 space-y-4">
                <div className="flex items-center justify-between border-b border-border/30 pb-2">
                  <div className="flex items-center gap-1.5">
                    <Terminal className="w-3.5 h-3.5 text-primary animate-pulse" />
                    <span className="text-[10px] font-mono text-foreground uppercase tracking-wider font-bold">{t('rail.dialogue_capabilities')}</span>
                  </div>
                  <span className="text-[8px] font-mono text-muted-foreground uppercase tracking-widest bg-primary/10 text-primary px-1.5 py-0.5 rounded">
                    {activeSection === 'arslan' ? t('rail.thread_bound') : activeSection === 'spawn' ? t('rail.spawn_bound') : t('rail.global_pool')}
                  </span>
                </div>

                {/* Dynamic Focus Scope Header */}
                <div className="text-[9.5px] font-mono bg-background/70 p-2 rounded-lg border border-border/50 space-y-1">
                  <span className="text-subtle-foreground text-[8px] uppercase tracking-wider block">{t('rail.active_scope')}</span>
                  <span className="font-bold text-primary block truncate">≫ {currentCaps.title}</span>
                </div>

                {/* 1. MCP (Model Context Protocol) Registry — real data from /mcp/servers */}
                <RailMcpList servers={mcpServers} />

                {/* 2. Equipped Agent Tools — shows the active roster's real equipped tools */}
                <div className="space-y-1.5">
                  <span className="text-[9px] font-mono text-subtle-foreground uppercase tracking-wider font-bold block flex items-center gap-1"><Wrench className="w-3 h-3" /> {t('rail.dialogue_tools')}</span>
                  {currentCaps.tools.length === 0 ? (
                    <p className="text-[9px] font-mono text-subtle-foreground italic">{t('rail.dialogue_tools_empty')}</p>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {currentCaps.tools.map((tId) => {
                        const details = toolDetails[tId] || { name: tId, emoji: '🔧' };
                        return (
                          <div
                            key={tId}
                            className="px-2 py-1 rounded text-[10px] font-mono flex items-center gap-1 select-none bg-surface text-info"
                            title={`Tool: ${tId}`}
                          >
                            {getIcon(tId, 'w-3 h-3')}
                            <span className="text-[10px] font-medium">{details.name}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* 3. Activated Skills — per-conversation skill tracking not yet available */}
                <div className="space-y-1.5">
                  <span className="text-[9px] font-mono text-subtle-foreground uppercase tracking-wider font-bold block flex items-center gap-1"><Brain className="w-3 h-3" /> {t('rail.dialogue_skills')}</span>
                  {currentCaps.skills.length === 0 ? (
                    <p className="text-[9px] font-mono text-subtle-foreground italic">{t('rail.dialogue_skills_empty')}</p>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {currentCaps.skills.map((sId) => {
                        const details = skillDetails[sId] || { name: sId, emoji: '🎓' };
                        return (
                          <div
                            key={sId}
                            className="bg-warning/10 text-warning px-2 py-1 rounded text-[10px] font-mono flex items-center gap-1 select-none"
                            title={details.name}
                          >
                            {getIcon(sId, 'w-3 h-3')}
                            <span className="text-[10px] font-medium">{details.name}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Per-spawn knowledge panel (when in spawn direct-chat) */}
            {activeSection === 'spawn' && spawns.find((s) => s.id === activeSpawnChatId) ? (
              <SpawnRailKnowledge spawnId={Number(spawns.find((s) => s.id === activeSpawnChatId)!.id)} />
            ) : (
            /* Spawns Active Pool list */
            <div className="p-5 flex-1 space-y-4 overflow-y-auto">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Network className="w-3.5 h-3.5 text-subtle-foreground" />
                  <span className="text-[10px] font-mono text-foreground uppercase tracking-wider font-bold">{t('rail.spawns_pipeline')}</span>
                </div>
                <button
                  onClick={() => setShowLedgerModal(true)}
                  className="text-subtle-foreground hover:text-primary transition-colors p-1 bg-border/40 rounded hover:bg-background/40"
                  title={t('rail.invite_spawns')}
                >
                  <Plus className="w-3.5 h-3.5" />
                </button>
              </div>

              <div className="space-y-2.5">
                {(() => {
                  const activeMembers = spawns.filter((s) => isRosterMember(s.id));

                  if (activeMembers.length === 0) {
                    return (
                      <div className="text-center py-6 px-4 bg-background/40 border border-border/30 rounded-xl space-y-2.5 select-none">
                        <p className="text-[10px] font-mono text-subtle-foreground uppercase leading-normal">
                          {t('rail.no_specialists')}
                        </p>
                        <button
                          onClick={() => setShowLedgerModal(true)}
                          className="px-2.5 py-1 text-[9.5px] font-mono font-bold bg-primary/10 hover:bg-primary/20 border border-primary/30 text-primary rounded-lg transition-all uppercase"
                        >
                          + {t('rail.invite_spawns')}
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
                        onClick={() => setStudio({ mode: 'edit', spawnId: Number(spawn.id) })}
                        className="p-2.5 bg-background/80 border border-border/50 hover:border-primary/30 rounded-xl transition-all cursor-pointer flex flex-col gap-2 group animate-fade-in"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <div>
                              <div className="text-[11px] font-medium text-foreground group-hover:text-primary transition-colors flex items-center gap-1.5">
                                <SpawnAvatar seed={spawn.name} size={20} />
                                <span>{spawn.name}</span>
                                <span className="text-[8px] font-mono bg-primary/10 text-primary rounded px-1.5 py-0.5 font-bold">L.{spawnLevel}</span>
                              </div>
                              <div className="text-[9px] text-subtle-foreground font-mono mt-0.5 max-w-[140px] truncate">{spawn.domain}</div>
                            </div>
                          </div>

                          <div className="flex items-center gap-2">
                            <span className={`w-1.5 h-1.5 rounded-full ${
                              spawn.status === 'working' ? 'bg-warning animate-pulse' : 'bg-success'
                            }`} />
                            <span className="text-[9px] font-mono text-subtle-foreground text-right uppercase">{spawn.status}</span>
                          </div>
                        </div>

                        {/* Level progress bar info segment */}
                        <div className="space-y-1">
                          <div className="flex justify-between items-center text-[7.5px] font-mono text-subtle-foreground uppercase tracking-wider">
                            <span>Level 進度</span>
                            <span className="text-primary font-bold">{progressPercent}%</span>
                          </div>
                          <div className="w-full bg-background border border-border/30 h-[3px] rounded-full overflow-hidden">
                            <div
                              className="bg-gradient-to-r from-warning to-primary h-full rounded-full transition-all duration-300"
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
            )}

            {/* Bottom-anchored evaluation dock (bar → slide-up summary → expand-left detail).
                On a spawn direct-chat, scope runs to that spawn; on the orchestrator, default
                to the ACTIVE conversation (same id the /ws/arslan/{id} WS uses), with an
                in-summary toggle to all sessions. */}
            <EvalDock
              spawnId={
                activeSection === 'spawn'
                  ? (() => {
                      const s = spawns.find((sp) => sp.id === activeSpawnChatId);
                      return s ? Number(s.id) : undefined;
                    })()
                  : undefined
              }
              conversationId={activeSection === 'arslan' ? activeThreadId : undefined}
            />
          </aside>
        )}
      </div>
      </main>

      {/* Spawn Studio — roomy create/configure panel (Ledger + right-rail entry). */}
      {studio && (
        <SpawnStudio
          mode={studio.mode}
          spawnId={studio.spawnId}
          onClose={() => setStudio(null)}
          onSaved={refreshSpawnsList}
        />
      )}

      {/* Dynamic Spawn Creator Dialog Box overlay */}
      {showCreateModal && (
        <div id="create-spawn-modal" className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in">
          <div className="w-full max-w-lg bg-surface/95 border border-border-strong rounded-2xl shadow-2xl overflow-hidden shadow-primary/20 select-none">

            {/* Header */}
            <div className="px-6 py-4 border-b border-border/80 flex items-center justify-between bg-background">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4.5 h-4.5 text-primary" />
                <h3 className="text-xs font-bold font-mono text-foreground uppercase tracking-widest leading-none">{t('modal.create_spawn_title')}</h3>
              </div>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="w-4.5 h-4.5" />
              </button>
            </div>

            {/* Form */}
            <form onSubmit={handleCreateSpawnSubmit} className="p-6 space-y-5">

              {/* Row: Name and Emoji Choice */}
              <div className="grid grid-cols-3 gap-4">
                <div className="col-span-2 space-y-1.5">
                  <label className="block text-[10px] font-mono text-muted-foreground uppercase tracking-wider">{t('modal.spawn_identifier')}</label>
                  <input
                    type="text"
                    required
                    value={newSpawnName}
                    placeholder="e.g., CrimsonWriter"
                    onChange={(e) => setNewSpawnName(e.target.value)}
                    className="w-full bg-background border border-border-strong focus:border-primary/60 focus:ring-1 focus:ring-ring/20 rounded-xl px-3.5 py-2.5 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-sans"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-mono text-muted-foreground uppercase tracking-wider">{t('modal.avatar_emoji')}</label>
                  <div className="flex items-center gap-3 bg-background border border-border-strong rounded-xl px-3.5 py-2">
                    <SpawnAvatar seed={newSpawnName || 'new spawn'} size={36} />
                    <span className="text-[10px] text-subtle-foreground font-mono">Auto-generated from name</span>
                  </div>
                </div>
              </div>

              {/* Input: Domain */}
              <div className="space-y-1.5">
                <label className="block text-[10px] font-mono text-muted-foreground uppercase tracking-wider">{t('modal.assigned_domain')}</label>
                <input
                  type="text"
                  required
                  value={newSpawnDomain}
                  placeholder={t('modal.domain_placeholder')}
                  onChange={(e) => setNewSpawnDomain(e.target.value)}
                  className="w-full bg-background border border-border-strong focus:border-primary/60 focus:ring-1 focus:ring-ring/20 rounded-xl px-3.5 py-2.5 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-sans"
                />
              </div>

              {/* Input: Description */}
              <div className="space-y-1.5">
                <label className="block text-[10px] font-mono text-muted-foreground uppercase tracking-wider">{t('modal.domain_scope')}</label>
                <textarea
                  value={newSpawnDescription}
                  placeholder={t('modal.description_placeholder')}
                  rows={3}
                  onChange={(e) => setNewSpawnDescription(e.target.value)}
                  className="w-full bg-background border border-border-strong focus:border-primary/60 focus:ring-1 focus:ring-ring/20 rounded-xl px-3.5 py-2.5 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all resize-none font-sans"
                />
              </div>

              {/* Footnote instruction info */}
              <div className="text-[10px] text-subtle-foreground font-mono leading-relaxed bg-background p-3 border border-border/20 rounded-xl">
                <span>{t('modal.default_capabilities_note')}</span>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-border/50 select-none">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-3.5 py-2 bg-transparent hover:bg-foreground/[0.03] rounded-lg text-xs font-sans font-medium text-muted-foreground hover:text-foreground transition-all border border-transparent"
                >
                  {t('common.cancel')}
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-primary hover:bg-primary-hover text-primary-foreground text-xs font-bold font-sans uppercase rounded-lg transition-all flex items-center gap-1 shadow-lg shadow-primary/10"
                >
                  {t('modal.confirm_synthesis')}
                </button>
              </div>

            </form>
          </div>
        </div>
      )}

      {/* Spawns Ledger Invitation Modal */}
      {showLedgerModal && (
        <div id="spawns-ledger-modal" className="fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in">
          <div className="w-full max-w-4xl h-[80vh] bg-surface/95 border border-border-strong rounded-2xl shadow-2xl overflow-hidden shadow-primary/25 flex flex-col">

            {/* Header */}
            <div className="px-6 py-4.5 border-b border-border/80 flex items-center justify-between bg-background shrink-0">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/30 flex items-center justify-center">
                  <Network className="w-4 h-4 text-primary" />
                </div>
                <div>
                  <h3 className="text-xs font-bold font-mono text-foreground uppercase tracking-wider">{t('modal.ledger_modal_title')}</h3>
                  <p className="text-[10px] text-subtle-foreground font-sans mt-0.5">{t('modal.ledger_modal_subtitle')}</p>
                </div>
              </div>
              <button
                onClick={() => {
                  setShowLedgerModal(false);
                  setLedgerSearch('');
                }}
                className="text-muted-foreground hover:text-foreground transition-colors p-1 bg-white/[0.02] border border-border rounded-lg"
              >
                <X className="w-4.5 h-4.5" />
              </button>
            </div>

            {/* Sub-header context banner */}
            <div className="px-6 py-3 bg-background/50 border-b border-border/40 flex items-center justify-between text-[11px] font-mono select-none">
              <span className="text-subtle-foreground">{t('modal.ledger_active_chat')}</span>
              <span className="text-primary font-bold max-w-xs truncate">≫ {activeThread.title}</span>
            </div>

            {/* Local ledger search input section */}
            <div className="p-4 bg-background/40 border-b border-border/40 shrink-0">
              <input
                type="text"
                value={ledgerSearch}
                onChange={(e) => setLedgerSearch(e.target.value)}
                placeholder={`🔍 ${t('modal.ledger_search_placeholder')}`}
                className="w-full bg-background border border-border-strong focus:border-primary/60 focus:ring-1 focus:ring-ring/20 rounded-xl px-4 py-3 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-sans"
              />
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
                    <div className="text-center py-12 text-muted-foreground font-mono text-xs select-none space-y-2">
                      <span className="block text-lg">⚠️</span>
                      <span className="text-subtle-foreground">{t('modal.ledger_no_results')}</span>
                    </div>
                  );
                }

                return filtered.map((spawn) => {
                  const spawnLevel = Math.max(1, Math.floor(spawn.totalTasks / 10) + 1);
                  const numericId = Number(spawn.id);

                  return (
                    <div
                      key={spawn.id}
                      className="p-4 border rounded-xl border-border/60 bg-background/90 flex items-center justify-between gap-4 select-none"
                    >
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div className="space-y-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <SpawnAvatar seed={spawn.name} size={20} />
                            <span className="font-bold text-foreground text-xs select-text">{spawn.name}</span>
                            <span className="text-[8px] font-mono bg-background text-muted-foreground rounded-md px-1.5 py-0.5 select-none font-bold uppercase tracking-wider">L.{spawnLevel}</span>
                            <span className="text-[8px] font-mono bg-primary/10 text-primary rounded px-1.5 py-0.5 select-none font-bold uppercase tracking-wider">{spawn.domain}</span>
                          </div>
                          <p className="text-[11px] text-muted-foreground leading-normal line-clamp-2 max-w-lg font-sans">
                            {spawn.description}
                          </p>
                          {/* Display Tools */}
                          <div className="flex items-center gap-1.5 pt-1">
                            {spawn.tools.map(toolId => (
                              <span key={toolId} className="text-[8px] font-mono text-subtle-foreground bg-background px-1.5 py-0.5 rounded-md">
                                #{toolId}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>

                      <LedgerRow
                        spawn={{ id: numericId, name: spawn.name }}
                        isMember={isRosterMember(spawn.id)}
                        onInvite={(id) => wsSend({ type: 'roster_invite', spawn_id: id })}
                        onKick={(id) => {
                          if (window.confirm(t('ledger.kickConfirm'))) {
                            wsSend({ type: 'roster_kick', spawn_id: id });
                          }
                        }}
                      />
                    </div>
                  );
                });
              })()}
            </div>

            {/* Footer containing synthetic action CTA */}
            <div className="p-4.5 bg-background border-t border-border/85 flex items-center justify-between shrink-0">
              <button
                onClick={() => {
                  setShowLedgerModal(false);
                  setStudio({ mode: 'create' });
                }}
                className="text-[10px] font-mono text-muted-foreground hover:text-foreground flex items-center gap-1.5 uppercase tracking-wider px-3 py-1.5 bg-foreground/[0.01] border border-border/80 rounded-lg hover:bg-foreground/[0.03] transition-all"
              >
                <Sparkles className="w-3.5 h-3.5 text-primary shrink-0" />
                <span>{t('modal.ledger_synthesize_cta')}</span>
              </button>
              <button
                onClick={() => {
                  setShowLedgerModal(false);
                  setLedgerSearch('');
                }}
                className="px-4 py-1.5 bg-surface hover:bg-surface-raised text-foreground text-[10px] font-bold font-mono uppercase rounded-lg border border-border-strong/50 transition-all select-none"
              >
                {t('modal.ledger_close')}
              </button>
            </div>

          </div>
        </div>
      )}

    </div>
  );
}

