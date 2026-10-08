import React, { useState, useEffect, useRef, useCallback } from 'react';
import { OPEN_SECTION_EVENT, readOpenSection, type Section } from "./lib/sections";
import { ConfirmHost, ToastHost, toast as showToast } from "./components/kit";
import AskSlot from "./components/AskSlot";
import { useTranslation } from 'react-i18next';
import { DEFAULT_SETTINGS } from './data';
import { Message, MessageAttachment, AppSettings } from './types';
import { useArslanStore } from './stores/arslanStore';
import { runLaunchTests } from './lib/launchTest';
import { useSettingsStore } from './stores/settingsStore';
import { useRegistryStore, useCapabilityLabel } from './stores/registryStore';
import { api } from './api/client';
import { shouldAutoTitle, maybeAutoTitle, seedTitledThreadIds } from "./lib/autoTitle";
import { restoreThreads, persistThreads, consumeFreshSessionFlag, mergeServerConversations } from './lib/sessionPersistence';
import { planBoot, pruneEmptyThreads } from './lib/bootSession';
import { firstLiveThread } from './lib/threadLifecycle';
import { normalizeLanguage } from './lib/languages';
import { toUiSettings, toUiMessages } from './api/adapters';
import type { ArslanServerMessage, ProviderOption, ProviderConfig } from './api/client.types';
import { listProviderConfigs, testProviderConfig, setPrimaryProviderConfig, distillConversation, deleteConversation } from './api/client';
import { useWebSocket } from './hooks/useWebSocket';
import { useBackendStatus } from './hooks/useBackendStatus';
import Sidebar from './components/Sidebar';
import OrchestratorChat from './components/OrchestratorChat';
import { composerDrafts, discardComposerDraft } from './lib/composerDrafts';
import SettingsScreen from './components/SettingsScreen';
import Capabilities from './components/Capabilities';
import { Globe, PanelRight } from 'lucide-react';
import { ThemeApplier } from './components/ThemeApplier';
import ActivityView from './components/ActivityView';
import MemorySection from './components/companion/MemorySection';
import ProjectsSection from './components/companion/ProjectsSection';
import { projectsApi } from './api/projects';
import ConversationControls from './components/companion/ConversationControls';
import TaskPanel from './components/companion/TaskPanel';
import LegacyExperts from './components/companion/LegacyExperts';
import { companionApi, type Project } from './api/companion';
import FirstRunWizard from './components/FirstRunWizard';
import UpdatePill from './components/UpdatePill';
import WorkDock from './components/WorkDock';
import { resolveSection, type SettingsSectionId } from './components/settings/sectionRegistry';
import { getFirstRunSeen, setFirstRunSeen, firstRunShouldShow, restoreFirstRunSeen } from './lib/firstRun';
import { threadNavAction } from './lib/threadNav';
import type { ImagePayload } from './lib/imagePayload';
import { threadDisplayTitle } from './lib/threadTitles';
import { useConversationIndex } from './hooks/useConversationIndex';
import { subscribeOpenConversation } from './lib/shell';
import { notificationTarget, OPEN_CONVERSATION_EVENT } from './lib/openConversation';
import ProactiveInbox from './components/proactive/ProactiveInbox';
import { useProactiveSummary } from './hooks/useProactiveSummary';
import ContextPanel from './components/panel/ContextPanel';
import { request } from './api/client';

interface ArslanThread {
  id: string;
  title: string;
  defaultTitle?: boolean;
  history: Message[];
  archived?: boolean;
  temporary?: boolean;
}

export default function App() {
  const { t, i18n } = useTranslation();
  // Resolve equipped-capability keys to their REAL registry names (raw key when unknown).
  const capabilityLabel = useCapabilityLabel();
  const loadRegistry = useRegistryStore((s) => s.loadRegistry);
  // Backend reachability — polled every 10s, drives honest offline states
  const backendStatus = useBackendStatus();
  // 0.1.47: the Inbox badge (unread proactive items), polled while the window is visible.
  const proactive = useProactiveSummary();
  const [legacyExperts, setLegacyExperts] = useState(0);
  useEffect(() => {
    request<{ experts: { converted: boolean }[] }>('/experts/legacy')
      .then((body) => setLegacyExperts(body.experts.filter((e) => !e.converted).length)).catch(() => {});
  }, []);

  const [activeSection, setActiveSection] = useState<Section>('arslan');
  const [showBrowser, setShowBrowser] = useState(false);
  const [settingsInitialSection, setSettingsInitialSection] = useState<SettingsSectionId | undefined>();
  const [panelView, setPanelView] = useState<'default' | 'editor'>('default');

  // Custom states for style variations (specifically asked in prompt)
  const [currentChatStyle, setCurrentChatStyle] = useState<'quartz' | 'brutalist' | 'linear'>('linear');

  // 0.1.48: the context panel beside a conversation (what runs, what was saved, where).
  const [showControlPanel, setShowControlPanel] = useState<boolean>(false);

  // ── Orchestrator threads — declared early so activeThreadId is available for
  // the WS hook below (hooks must be called in a consistent order).
  // Restore the persisted thread list on init. The thread list is resumed; the
  // ACTIVE thread is not — launching the app opens a new session (see bootPlan
  // below). Never reintroduce a literal "thread-default"; on first run /
  // post-wipe restore hands back one fresh "New Session" and says so.
  const restoredInit = useRef(restoreThreads()).current;
  // Detect a FRESH app session (absent on a brand-new tab/app launch, present
  // across same-tab reloads). Declared here because the boot plan below needs
  // it; it also scopes the session-ephemeral spawn roster further down.
  const freshSession = useRef(consumeFreshSessionFlag()).current;
  // Launching the app opens a NEW session; a same-tab reload does not. Empty
  // sessions do not accumulate because the recovery effect below prunes the
  // ones the server has never heard of — see lib/bootSession.ts for why there
  // is no "is this session empty" flag anywhere.
  const bootPlan = useRef(
    planBoot(restoredInit, { freshLaunch: freshSession, now: Date.now() }),
  ).current;
  const [threads, setThreads] = useState<ArslanThread[]>(bootPlan.threads);
  const [activeThreadId, setActiveThreadId] = useState<string>(bootPlan.activeThreadId);
  // The recovery effect runs once with [] deps but must prune against whichever
  // thread is active when its fetch RESOLVES, not the one that was active when
  // it started.
  const activeThreadIdRef = useRef(activeThreadId);
  activeThreadIdRef.current = activeThreadId;

  // A clicked desktop notification asks for its conversation (0.1.41). Refs keep
  // the one subscription pointed at the current thread list and handler.
  const openFromNotification = useRef<(id: string) => void>(() => {});
  openFromNotification.current = (id: string) => {
    const target = notificationTarget(id, threads);
    if (target?.kind === 'inbox') { setActiveSection('inbox'); setPanelView('default'); }
    else if (target) selectConversation(target.id);
  };
  useEffect(() => subscribeOpenConversation(id => openFromNotification.current(id)), []);
  // 0.1.52 S3: a link to an earlier conversation in a reply (conversation_search) — same
  // rule as a notification: only a conversation the user has and has not archived.
  useEffect(() => {
    const onLink = (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      if (typeof id === 'string' && id) openFromNotification.current(id);
    };
    window.addEventListener(OPEN_CONVERSATION_EVENT, onLink);
    return () => window.removeEventListener(OPEN_CONVERSATION_EVENT, onLink);
  }, []);
  useEffect(() => {
    const onOpen = (event: Event) => {
      const asked = readOpenSection((event as CustomEvent<unknown>).detail);
      if (!asked) return;
      if (asked.section === 'settings') setSettingsInitialSection(resolveSection(asked.sub));
      setActiveSection(asked.section); setPanelView('default');
    };
    window.addEventListener(OPEN_SECTION_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_SECTION_EVENT, onOpen);
  }, []);


  // ── Auto-title: track which threads have already received a generated title
  // so we never regenerate on re-renders or subsequent messages.
  //
  // 🔴 This used to seed EVERY restored id, on the assumption that a restored
  // thread already has a real title. Not true for one still called "New
  // Session", which is exactly what restoreThreads hands back on a fresh
  // install — so the first conversation of every new user was marked titled
  // before it had ever been titled, and kept the truncated user text for good.
  const titledThreadIds = useRef<Set<string>>(
    seedTitledThreadIds(restoredInit.threads),
  );

  // Gate item ⑦ — recover conversations from the SERVER on boot.
  //
  // localStorage was the only record of which conversations existed, and the
  // packaged app wipes it every launch (ephemeral sidecar port -> new origin ->
  // fresh partition), so every restart orphaned the previous conversation while
  // its rows sat untouched in the database. Runs once; failure is silent by
  // design — a backend still booting must not look like an empty history.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const rows = await api.listConversations();
        if (cancelled || !rows.length) return;
        // A row exists server-side only once a conversation has at least one
        // message, so "the server has never heard of it" IS "it has no
        // messages" — the only emptiness signal that cannot go stale. Pruning
        // here rather than at boot is also what keeps it fail-open: offline,
        // still booting, or 401 prunes nothing.
        const serverIds = new Set(rows.map((r) => r.conversation_id));
        setThreads((prev) =>
          pruneEmptyThreads(mergeServerConversations(prev, rows), {
            serverIds,
            activeThreadId: activeThreadIdRef.current,
          }),
        );
      } catch {
        /* offline / still booting — keep whatever localStorage had */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // The server's conversation list kept fresh: glyphs for each conversation, and conversations
  // started elsewhere (a task handed over from the iPhone) appear without a restart.
  const conversationIndex = useConversationIndex();
  useEffect(() => {
    const rows = conversationIndex.rows;
    if (!rows.length) return;
    setThreads(prev => {
      const known = new Set(prev.map(thread => thread.id));
      return rows.some(row => !known.has(row.conversation_id)) ? mergeServerConversations(prev, rows) as typeof prev : prev;
    });
  }, [conversationIndex.rows]);

  // Persist threads + active id whenever either changes (history is dropped).
  useEffect(() => {
    persistThreads(threads, activeThreadId);
  }, [threads, activeThreadId]);

  // ── Stage B: Orchestrator chat live WS ─────────────────────────────────────
  // The store holds all thread items; we derive UI messages from it.
  const arslanItems = useArslanStore((s) => s.items);
  const dockTaskFrame = useArslanStore((s) => s.taskState);
  const arslanStreaming = useArslanStore((s) => s.streaming);
  const arslanRunning = useArslanStore((s) => s.thinking || s.streaming || s.pending || s.activeRunId != null);
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
  const liveOrchestratorHistory: Message[] = toUiMessages(arslanItems).map((m) => {
    // attachment_stored sentinel from arslanStore (stores stay i18n-free).
    if (m.text.startsWith('__ATTACHMENT_STORED__:')) {
      try {
        const p = JSON.parse(m.text.slice('__ATTACHMENT_STORED__:'.length)) as { name?: string | null; chunks?: number };
        return {
          ...m,
          text: p.name
            ? t('chat.attachment_stored', { name: p.name, chunks: p.chunks ?? 0 })
            : t('chat.attachment_stored_generic', { chunks: p.chunks ?? 0 }),
        };
      } catch {
        return m;
      }
    }
    return m;
  });

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
      !threads.find((thread) => thread.id === activeThreadId)?.temporary &&
      !titledThreadIds.current.has(activeThreadId) &&
      shouldAutoTitle(syntheticThread)
    ) {
      // Mark immediately so concurrent renders don't fire a second call.
      titledThreadIds.current.add(activeThreadId);
      const capturedThreadId = activeThreadId;
      maybeAutoTitle(
        capturedThreadId,
        { history: liveOrchestratorHistory },
        // S3-M3 fold-in: pass the conversation id so the titler's tokens are
        // ledgered against this conversation (TitleIn.conversation_id).
        (msg, reply) => api.generateTitle(msg, reply, capturedThreadId),
        (tid, title) => {
          setThreads((prev) =>
            prev.map((t) => (t.id === tid ? { ...t, title, defaultTitle: undefined } : t)),
          );
        },
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveOrchestratorHistory, activeThreadId]);

  // Send a user message to the live backend
  const sendOrchestratorMessage = useCallback((text: string, attached?: { context: string; names: string[]; display?: MessageAttachment[]; images?: ImagePayload[] }, opts?: { fromClarify?: boolean }) => {
    // display = session-only echo for the sent bubble (image thumbnails / doc chips);
    // only text-bearing attachments ride to the backend as attached_context below.
    useArslanStore.getState().addUserMessage(text, attached?.display);
    useArslanStore.getState().setThinking(true);
    wsSend({
      type: 'user_message',
      content: text,
      ...(attached?.context ? { attached_context: attached.context, attached_names: attached.names } : {}),
      // Real image blocks, not text. They participate in THIS turn only
      // (decision ③A) — history keeps a "[图片:name]" placeholder.
      ...(attached?.images?.length ? { images: attached.images } : {}),
    });
  }, [wsSend]);

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

  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [settingsReady, setSettingsReady] = useState(false);

  // Stage B: provider/search-provider catalogs for Settings dropdowns (live from backend)
  const [llmProviders, setLlmProviders] = useState<ProviderOption[]>([]);
  const [searchProviders, setSearchProviders] = useState<string[]>([]);
  const [providerConfigs, setProviderConfigs] = useState<ProviderConfig[]>([]);
  // First-run onboarding: only decide once the provider list has actually loaded
  // (avoids a wizard flash before the backend responds) and the wizard hasn't
  // been seen/dismissed before.
  const [providerConfigsReady, setProviderConfigsReady] = useState(false);
  /** Configs with a launch-time test still in flight — the only status that
   *  cannot come from the persisted rows. */
  const [providerTestingIds, setProviderTestingIds] = useState<Set<number>>(new Set());
  const [firstRunSeen, setFirstRunSeenState] = useState<boolean>(getFirstRunSeen());

  // Settings and model catalogs from the backend on mount
  useEffect(() => {
    // Load settings from backend; merge into UI state, preserving UI-only fields
    api.getSettings().then(async (backendSettings) => {
      setFirstRunSeenState(await restoreFirstRunSeen(
        backendSettings.first_run_seen,
        () => api.updateSettings({ first_run_seen: true }),
      ));
      const mapped = toUiSettings(backendSettings);
      setSettings((prev) => ({ ...prev, ...mapped }));
      // Apply the saved UI language on load — reconciles any legacy label value
      // stored before the selector switched to i18next codes.
      i18n.changeLanguage(normalizeLanguage(mapped.language));
      // Also push into settingsStore so child components can read live settings
      useSettingsStore.getState().setSettings(backendSettings);
    }).catch(() => {
      // backend unavailable — keep DEFAULT_SETTINGS
    }).finally(() => setSettingsReady(true));

    // Load LLM provider catalog
    api.listProviders().then(setLlmProviders).catch(() => {});

    // Load search provider catalog
    api.listSearchProviders().then(setSearchProviders).catch(() => {});

    // Load multi-model provider configs. Mark "ready" only on success so the
    // first-run wizard never shows while the backend is unreachable.
    listProviderConfigs()
      .then(async (cfgs) => {
        setProviderConfigs(cfgs);
        setProviderConfigsReady(true);

        // Launch-time verification. Every configured model is asked, once, the
        // only question worth asking: can it answer a message? The backend
        // persists each verdict, so we re-read the rows afterwards rather than
        // holding a parallel copy — one source of truth, and it survives a
        // remount. Only the in-flight spinner lives in memory.
        if (cfgs.length === 0) return;
        setProviderTestingIds(new Set(cfgs.map((c) => c.id)));
        await runLaunchTests(cfgs, {
          test: (id) => testProviderConfig(id),
          onStart: () => {},
          onResult: (id) => {
            setProviderTestingIds((prev) => {
              const next = new Set(prev);
              next.delete(id);
              return next;
            });
          },
        });
        // Re-read the persisted verdicts (including each failure's reason).
        listProviderConfigs().then(setProviderConfigs).catch(() => {});
      })
      .catch(() => {});
  }, []);

  // Real capability display-name map — fetched once so equipped-capability chips
  // resolve keys to their true names instead of fabricated placeholders.
  useEffect(() => { loadRegistry(); }, [loadRegistry]);

  // Handle addition of a brand new Orchestrator thread context
  const handleAddArslanThread = (threadId = `thread-${crypto.randomUUID()}`) => {
    const newThread: ArslanThread = {
      id: threadId,
      title: 'New Session',
      defaultTitle: true,
      history: []
    };

    // Signal the OLD conversation ended (backend may background-distill prefs).
    // wsSend targets the still-current /ws/arslan/${activeThreadId} connection.
    if (activeThreadId) wsSend({ type: 'session_ended', conversation_id: activeThreadId });

    // Clear the store so the new conversation starts with empty history (the
    // backend will send an empty `history` frame for the new conversation_id).
    useArslanStore.getState().resetForNewConversation();
    setThreads(prev => [...prev.filter(thread => !(thread.id === activeThreadId && thread.temporary)), newThread]);
    setActiveThreadId(threadId);
    setActiveSection('arslan');
    setPanelView('default');
  };

  /** A new conversation in the project. `prefill` (0.1.56 "交给 Arslan 起头") is typed into the
   *  composer for the user to send — nothing is sent on their behalf. */
  const handleStartProject = async (project: Project, prefill?: string, checkpointId?: string) => {
    const conversationId = `thread-${crypto.randomUUID()}`;
    if (prefill) composerDrafts.set(conversationId, prefill);
    await companionApi.saveContext({ conversation_id: conversationId, version: 0, project_id: null,
      no_memory: false, no_learning: false, temporary: false, cloud_memory_allowed: false, allow_sensitive: false },
    { project_id: project.id });
    // 0.1.56 §4.4: link the conversation to the checkpoint; best-effort — the chat opens either way.
    if (checkpointId) await projectsApi.handoff(project.id, checkpointId, conversationId).catch(() => undefined);
    handleAddArslanThread(conversationId);
  };

  // ── Conversation row overflow actions (Distill / Archive / Delete) ──────────

  // Distill: harvest this conversation's spawn chats into memory (backend call),
  // then surface how many were distilled via the transient toast.
  const handleDistillThread = async (id: string) => {
    try {
      const res = await distillConversation(id);
      // `distilled_spawns` is a count of AGENTS folded into memory, NOT memory items.
      // Zero producing spawns → a truthful no-op message instead of "distilled 0".
      showToast(
        res.distilled_spawns > 0
          ? t('sidebar.distilled_toast', { count: res.distilled_spawns })
          : t('sidebar.distilled_none'),
      );
    } catch {
      showToast(t('sidebar.distill_failed'));
    }
  };

  // Archive is purely client-side (persisted via sessionPersistence). If the
  // archived thread was active, hop to the first remaining non-archived thread
  // so we never leave an active-but-hidden conversation.
  const handleArchiveThread = (id: string) => {
    setThreads((prev) => prev.map((th) => (th.id === id ? { ...th, archived: true } : th)));
    if (id === activeThreadId) {
      useArslanStore.getState().resetForNewConversation();
      const next = firstLiveThread(threads, id);
      if (next) {
        setActiveThreadId(next.id);
      } else {
        // Archived the only non-archived thread — mirror delete's "nothing left" case
        // and mint a fresh session so the main pane never shows an archived thread.
        const fresh: ArslanThread = {
          id: `thread-${Date.now()}`,
          title: 'New Session',
      defaultTitle: true,
              history: [],
        };
        setThreads((prev) => [...prev, fresh]);
        setActiveThreadId(fresh.id);
      }
      setActiveSection('arslan');
      setPanelView('default');
    }
  };

  const handleUnarchiveThread = (id: string) => {
    setThreads((prev) => prev.map((th) => (th.id === id ? { ...th, archived: false } : th)));
  };

  // Delete: remove the thread locally + fire the backend delete (fire-and-forget,
  // best-effort like other calls). If it was the active thread, select the first
  // remaining non-archived thread; if none remain, mint a fresh session. The
  // persisted active-thread key is rewritten by the persistThreads effect.
  const handleDeleteThread = (id: string) => {
    discardComposerDraft(id);
    const remaining = threads.filter((th) => th.id !== id);
    const wasActive = id === activeThreadId;
    deleteConversation(id).catch((err) => {
      // Best-effort — the row is already gone from the UI, but a failed server-side
      // purge must be observable rather than silently swallowed.
      console.error(`[deleteConversation] backend purge failed for ${id}`, err);
    });
    if (wasActive) {
      useArslanStore.getState().resetForNewConversation();
      const next = firstLiveThread(remaining, id);
      if (next) {
        setThreads(remaining);
        setActiveThreadId(next.id);
      } else {
        const fresh: ArslanThread = {
          id: `thread-${Date.now()}`,
          title: 'New Session',
      defaultTitle: true,
              history: [],
        };
        setThreads([...remaining, fresh]);
        setActiveThreadId(fresh.id);
      }
      setActiveSection('arslan');
      setPanelView('default');
    } else {
      setThreads(remaining);
    }
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
          if (!t.temporary && (t.title === 'New Session' || t.title.startsWith('Orchestration thread'))) {
            const userMsg = newHistory.find(m => m.sender === 'user');
            if (userMsg) {
              const cleaned = userMsg.text.replace(/[#*`_]/g, '').trim();
              updatedTitle = cleaned.length > 22 ? cleaned.substring(0, 22) + '...' : cleaned;
            }
          }

          return { ...t, history: newHistory, title: updatedTitle, defaultTitle: updatedTitle === t.title ? t.defaultTitle : undefined };
        }
        return t;
      });
    });
  };

  // Calculate current active histories
  const activeThread = threads.find(t => t.id === activeThreadId) || threads[0];

  // All orchestrator threads now use the live WS; history comes from the store.
  const isThreadEmpty = activeSection === 'arslan' && orchestratorChatHistory.length === 0;
  function selectConversation(id: string) {
    const nav = threadNavAction(activeThreadId, id);
    if (nav.endPrevious) wsSend({ type: 'session_ended', conversation_id: activeThreadId });
    if (nav.resetStore) useArslanStore.getState().resetForNewConversation();
    if (nav.endPrevious) setThreads(prev => prev.filter(thread => !(thread.id === activeThreadId && thread.temporary)));
    setActiveThreadId(id); setActiveSection('arslan'); setPanelView('default');
  }
  // A proactive item was accepted: the job reports into `conversationId`. A conversation the app does
  // not have yet (or no longer has) is created first, so its job card has somewhere to appear.
  function openInboxConversation(conversationId: string, created: boolean) {
    if (created || !threads.some(thread => thread.id === conversationId)) { handleAddArslanThread(conversationId); return; }
    setThreads(old => old.map(thread => thread.id === conversationId ? { ...thread, archived: false } : thread));
    selectConversation(conversationId);
  }
  // 0.1.44/0.1.48: former experts can be turned into skills; the tab shows only while any remain.
  const experts = legacyExperts > 0 ? <LegacyExperts /> : null;



  return (
    <div className="flex w-screen h-screen bg-background text-foreground overflow-hidden font-sans antialiased">
      <ThemeApplier />
      <UpdatePill />

      {/* Sidebar with macOS window decorations */}
      {activeSection !== 'settings' && <Sidebar
        threads={threads}
        activeThreadId={activeThreadId}
        onSelectThread={selectConversation}
        onOpenConversation={conversationId => {
          setThreads(old => old.map(thread => thread.id === conversationId ? { ...thread, archived: false } : thread));
          selectConversation(conversationId);
          setActiveSection('arslan');
        }}
        onAddThread={() => handleAddArslanThread()}
        inboxUnread={proactive.unread + (proactive.approvals ?? 0) + (proactive.memory ?? 0)}
        inboxHigh={proactive.high + (proactive.approvals ?? 0)}
        activeSection={activeSection}
        onChangeSection={(section) => {
          if (section === 'settings') setSettingsInitialSection(undefined);
          setActiveSection(section);
          setPanelView('default');
        }}
        onDistillThread={handleDistillThread}
        onArchiveThread={handleArchiveThread}
        onUnarchiveThread={handleUnarchiveThread}
        onDeleteThread={handleDeleteThread}
        backendStatus={backendStatus}
        meta={conversationIndex.meta}
      />}

      {/* Main Workspace Frame container with glass window feel */}
      {/* min-w-0: without it a flex child refuses to shrink below its content's
          min width, and one wide unwrappable row (M7-#1: the Skills chips) pushes
          the whole main pane past the right edge of the window. */}
      <main className="flex-1 min-w-0 flex flex-col h-full bg-background relative">
      {/* Redesigned Grand Multi-column Frame layout */}
      <div className="flex-1 min-w-0 flex h-full relative">

        {/* Main Workspace Frame container */}
        <main className="flex-1 min-w-0 flex flex-col h-full bg-background relative overflow-hidden">
          {/* Top Bar for overall macro layout */}
          {/* Shared by EVERY section, which is what makes the window draggable
              everywhere rather than only in chat. "deep" covers the labels
              inside; Tauri's drag script skips real controls on its own. */}
          <div data-tauri-drag-region="deep" data-testid="workspace-bar"
            className="h-14 shrink-0 gap-3 border-b border-border px-4 lg:px-6 flex items-center justify-between bg-background/40 backdrop-blur-md z-30">
            {activeSection === 'settings' && <span className="absolute left-1/2 -translate-x-1/2 text-sm text-muted-foreground pointer-events-none">Arslan</span>}
            {/* The label is a CONVERSATION thing, so it appears only there.
                The BAR itself stays on every section, and that is not tidiness:
                it carries data-tauri-drag-region, and it is the only region the
                window can be dragged by under titleBarStyle Overlay. Removing
                it outside chat would reintroduce the bug fixed in v0.1.8 —
                every non-chat screen becomes unmovable. Empty, same height, no
                layout shift (decision A). */}
            <div className="flex items-center gap-2 min-w-0">
              {activeSection === 'arslan' ? (
                <>
                  {/* The dot IS the "active session workspace" label — it was
                      three words of chrome saying what a green dot already says. */}
                  <span className="w-2 h-2 rounded-full bg-success shrink-0"></span>
                  <span className="text-xs font-sans text-foreground font-medium truncate">
                    {threadDisplayTitle(activeThread, t, conversationIndex.meta[activeThreadId]?.kind)}
                  </span>
                  {/* 0.1.42: one header row — title · project (opens project and
                      memory settings) · a status chip only for work that needs a look. */}
                  {activeSection === 'arslan' && <div data-testid="conversation-context-bar" className="flex min-w-0 items-center gap-3 pl-2">
                    <ConversationControls compact key={`context:${activeThreadId}`} conversationId={activeThreadId} running={arslanRunning} empty={orchestratorChatHistory.length === 0}
                      onChanged={context => setThreads(prev => prev.map(thread => thread.id === context.conversation_id && thread.temporary !== context.temporary
                        ? { ...thread, temporary: context.temporary, ...(context.temporary ? { title: t('companion.temporary') } : {}) } : thread))} />
                    {!activeThread?.temporary && <TaskPanel compact key={`task:${activeThreadId}`} conversationId={activeThreadId}
                      onResume={task => { useArslanStore.getState().clearError(); wsSend({ type: 'resume_task', task_id: task.spec.id, expected_version: task.version }); }} />}
                  </div>}
                </>
              ) : (
                /* 🔴 The bar itself must stay on EVERY section — it carries
                   data-tauri-drag-region, and v0.1.7 shipped with it only on
                   chat: "The window could only be dragged from the chat view"
                   (bab6273). Deleting it outside chat, which is what "remove
                   this empty strip" literally asks for, brings that back.
                   So the strip stops being EMPTY instead: each section's own
                   title moves up into it, which is what made the space read as
                   dead in the first place. */
                <span className={`text-xs font-sans text-foreground font-medium truncate ${activeSection === 'settings' ? 'invisible' : ''}`}>
                  {t(`nav.${activeSection}`)}
                </span>
              )}
            </div>

            <div className={`flex shrink-0 items-center gap-3 ${activeSection === 'settings' ? 'hidden' : ''}`}>


              {/* The context panel: what runs for this conversation, what was saved, where. */}
              {!isThreadEmpty && activeSection === 'arslan' && !activeThread?.temporary && (
                <button
                  id="toggle-control-panel"
                  aria-label={t('panel.title')}
                  aria-expanded={showControlPanel}
                  aria-controls="context-panel"
                  onClick={() => setShowControlPanel(!showControlPanel)}
                  className={`flex items-center px-2 py-1.5 rounded-lg border transition-colors ${
                    showControlPanel
                      ? 'border-primary/30 bg-primary/5 text-primary'
                      : 'border-border text-muted-foreground hover:text-foreground'
                  }`}
                >
                  <PanelRight className="w-3.5 h-3.5" />
                </button>
              )}

              {/* Explicit-user static preview, not an autonomous browser agent. */}
              <button
                data-testid="browser-indicator"
                onClick={() => setShowBrowser(true)}
                title={t('dock.title')}
                aria-label={t('dock.title')}
                className="flex items-center px-2 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-primary hover:border-primary"
              >
                <Globe className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <div className="flex-1 flex flex-col overflow-hidden relative">
            {/* 0.1.55: every pending ask in ONE slot, queued "‹ 1 / 3 ›" (they used to
                render into the same absolute spot and overlap). Same frames, same answers. */}
            {activeSection === 'arslan' && <AskSlot send={wsSend} />}

            {activeSection === 'arslan' && (
              <div className="flex h-full min-h-0 flex-col">
              <OrchestratorChat
                key={`chat:${activeThreadId}:${activeThread?.temporary === true}`}
                chatHistory={orchestratorChatHistory}
                setChatHistory={setChatHistoryForActiveThread}
                onSendMessage={sendOrchestratorMessage}
                spawns={[]}
                currentStyle={currentChatStyle}
                setCurrentStyle={setCurrentChatStyle}
                activeThread={activeThread}
                hasModel={providerConfigs.length > 0}
                providerConfigs={providerConfigs}
                llmProviders={llmProviders}
                providerTestingIds={providerTestingIds}
                onSelectModel={async (id) => {
                  await setPrimaryProviderConfig(id);
                  listProviderConfigs().then(setProviderConfigs).catch(() => {});
                }}
                onOpenSettings={() => {
                  setActiveSection('settings');
                  setPanelView('default');
                }}
                conversationId={activeThreadId}
                shellEnabled={settings.orchestratorShellEnabled}
                shellPolicy={settings.shellConfirmPolicy}
              />
              </div>
            )}

            {activeSection === 'capabilities' && (
              // The primary config is the one that answers; falling back to the
              // first is for the window before a primary is assigned, not a
              // guess about which one runs.
              <Capabilities
                experts={experts}
                provider={
                  (providerConfigs.find((c) => c.is_primary) ?? providerConfigs[0])?.provider
                }
              />
            )}

            {activeSection === 'projects' && <ProjectsSection onStart={handleStartProject} />}
            {activeSection === 'inbox' && <ProactiveInbox onOpenConversation={openInboxConversation}
              onOpenSettings={() => { setSettingsInitialSection('background'); setActiveSection('settings'); }}
              onOpenModelSettings={() => { setSettingsInitialSection('models'); setActiveSection('settings'); }} />}
            {activeSection === 'brain' && <MemorySection legacy={!restoredInit.mintedFresh} />}
            {activeSection === 'activity' && <ActivityView />}

            {activeSection === 'settings' && (
              <SettingsScreen
                initialSection={settingsInitialSection}
                onOpenActivity={() => setActiveSection('activity')}
                settings={settings}
                setSettings={setSettings}
                llmProviders={llmProviders}
                searchProviders={searchProviders}
                backendStatus={backendStatus}
                providerConfigs={providerConfigs}
                onProviderConfigsChange={setProviderConfigs}
                onBack={() => setActiveSection('arslan')}
              />
            )}
          </div>
        </main>

        <WorkDock open={showBrowser} onOpen={() => setShowBrowser(true)} onClose={() => setShowBrowser(false)}
          conversationId={activeThreadId}
          taskId={dockTaskFrame?.conversation_id === activeThreadId ? dockTaskFrame.task_id : null}
          temporary={Boolean(activeThread.temporary)} />
        {showControlPanel && !showBrowser && !isThreadEmpty && !activeThread.temporary && activeSection === 'arslan' && (
          <div id="context-panel" className="contents">
            <ContextPanel conversationId={activeThreadId} onClose={() => setShowControlPanel(false)} />
          </div>
        )}
      </div>
      </main>

      {/* First-run onboarding — shown once when no provider/model is configured.
          The bare NoModelHint remains the inline nudge for later visits. */}
      {firstRunShouldShow({
        ready: providerConfigsReady && settingsReady,
        hasProvider: providerConfigs.length > 0,
        seen: firstRunSeen,
      }) && (
        <FirstRunWizard
          llmProviders={llmProviders}
          onLanguageChange={(language) => {
            setSettings((prev) => ({ ...prev, language }));
            const store = useSettingsStore.getState();
            if (store.settings) store.setSettings({ ...store.settings, language });
          }}
          onAdded={(cfg) => setProviderConfigs((prev) => [...prev, cfg])}
          onClose={() => {
            setFirstRunSeen();
            setFirstRunSeenState(true);
            api.updateSettings({ first_run_seen: true }).catch(() => {});
          }}
        />
      )}

      {/* 0.1.55 surface kit: the one toast stack and the one confirm sheet. */}
      <ToastHost />
      <ConfirmHost />

    </div>
  );
}
