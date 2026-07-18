import React, { useState, useRef, useEffect } from 'react';
import {
  ArrowRight, Terminal,
  AlertTriangle, CheckCircle2, XOctagon,
  Layers, CornerDownRight,
  Cpu, X, Square,
  ThumbsUp, ThumbsDown, Wand2
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getIcon } from './iconMap';
import { Message, MessageAttachment, Spawn } from '../types';
import { useCapabilityLabel } from '../stores/registryStore';
import { useProfileStore } from '../stores/profileStore';
import SFSymbol from './SFSymbol';
import { SpawnAvatar } from './SpawnAvatar';
import MessageBody, { HtmlDocCard } from './MessageBody';
import CopyButton from './CopyButton';
import WorkingPulse from './WorkingPulse';
import LiveActivity from './LiveActivity';
import ToolActivityCard from './ToolActivityCard';
import { useArslanStore } from '../stores/arslanStore';
import { api } from '../api/client';
import { useSettingsStore } from '../stores/settingsStore';
import SandboxPanel from './SandboxPanel';
import NoModelHint from './NoModelHint';
import RunReplay from './RunReplay';
import { useComposerAttach, AttachChips, AttachControl, SentAttachments, type Attachment } from './ComposerAttach';
import InviteConfirmCard from './InviteConfirmCard';
import ClarifyOptionsCard from './ClarifyOptionsCard';
import MentionText from './MentionText';
import UsageChip from './UsageChip';
import { resolveSpawnName } from '../api/resolveSpawnName';
import { activeMention, filterRoster, insertMention } from '../lib/mentions';

/** S3-M1: muted "interrupted" line under a bubble whose run was cancelled
 *  mid-stream — same look as the stall indicator (⏸ + working.stalled, which
 *  reads 已中断/Interrupted in all locales). */
function RunCancelledMarker() {
  const { t } = useTranslation();
  return (
    <div data-testid="run-cancelled-marker" className="mt-2 text-[11px] font-mono text-danger/80 select-none">
      ⏸ {t('working.stalled')}
    </div>
  );
}

interface OrchestratorChatProps {
  chatHistory: Message[];
  setChatHistory: React.Dispatch<React.SetStateAction<Message[]>>;
  /** When provided, user prompts are sent via this callback (live WS) instead of the mock simulation.
   *  `display` echoes ALL attachments into the sent bubble (session-only); `context`/`names`
   *  carry only the text-bearing ones to the backend. */
  onSendMessage?: (text: string, attached?: { context: string; names: string[]; display?: MessageAttachment[] }) => void;
  spawns: Spawn[];
  currentStyle: 'quartz' | 'brutalist' | 'linear';
  setCurrentStyle: (style: 'quartz' | 'brutalist' | 'linear') => void;
  activeThread: any;
  /** Called when the user confirms a proposed direction. spawnId is the numeric backend id. */
  onConfirmDirection?: (spawnId: number) => void;
  /** Called when the user submits a verdict on a spawn deliverable. */
  onDeliverableVerdict?: (action: string, spawnId: number, messageId?: number, taskBrief?: string | null) => void;
  /** Called when the user clicks 精修 (Refine) on a spawn deliverable. */
  onRefine?: (spawnId: number, messageId: number | undefined, content: string, spawnName: string) => void;
  /** True when at least one ProviderConfig exists. When false, a hint to configure a model is shown. */
  hasModel?: boolean;
  /** Navigate to the Settings screen. Used by the no-model hint. */
  onOpenSettings?: () => void;
  /** The active conversation id — consumed by SandboxPanel (later task). */
  conversationId?: string;
  /** Pending inline roster invite (from a backend `propose_invite` frame). */
  pendingInvite?: { spawnId: number; reason: string } | null;
  /** Accept the pending invite → join + dispatch the parked task. */
  onAcceptInvite?: (spawnId: number) => void;
  /** Dismiss the pending invite → clear it (no dispatch). */
  onDismissInvite?: () => void;
  /** True when the orchestrator-shell capability is enabled (drives the policy pill). */
  shellEnabled?: boolean;
  /** Current shell confirmation posture, shown + flippable in the composer pill. */
  shellPolicy?: 'ask_all' | 'ask_risky';
  /** Called when the user flips the confirmation posture from the composer pill. */
  onShellPolicyChange?: (policy: 'ask_all' | 'ask_risky') => void;
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
  onRefine,
  hasModel = true,
  onOpenSettings,
  conversationId,
  pendingInvite,
  onAcceptInvite,
  onDismissInvite,
  shellEnabled = false,
  shellPolicy = 'ask_all',
  onShellPolicyChange,
}: OrchestratorChatProps) {
  const { t } = useTranslation();
  const settings = useSettingsStore((s) => s.settings);
  // Real capability display names (key → name) for equipped-capability chips.
  const capabilityLabel = useCapabilityLabel();
  // Client-side user display name for the greeting + own-message sender label.
  const displayName = useProfileStore((s) => s.displayName);
  // Live roster from store — used to determine which spawns are in this conversation
  const roster = useArslanStore((s) => s.roster);
  // Per-spawn "running a turn now" signal for the pill shimmer: pendingRoute is set on the
  // routing frame and cleared on stream_end; streamSpawnId covers the token-streaming window.
  const pendingRoute = useArslanStore((s) => s.pendingRoute);
  const streamSpawnId = useArslanStore((s) => s.streamSpawnId);
  // Known spawn names (ledger prop + names learned from frames) — grounds the
  // @-mention chips in routing announcements; unknown @text stays plain.
  const spawnNameMap = useArslanStore((s) => s.spawnNames);
  const mentionNames = React.useMemo(
    () => [...new Set([...spawns.map((s) => s.name), ...Object.values(spawnNameMap)])].filter(Boolean),
    [spawns, spawnNameMap],
  );
  const thinking = useArslanStore((s) => (s as any).thinking as boolean);
  const liveSteps = useArslanStore((s) => (s as any).activitySteps as import('../api/client.types').ToolStep[]);
  const liveStreaming = useArslanStore((s) => (s as any).streaming as boolean);
  const workStartedAt = useArslanStore((s) => (s as any).workStartedAt as number | null);
  const streaming = useArslanStore((s) => s.streaming);
  // HX-4/A1: stall watchdog — while a turn is active (runtime-frame flags only,
  // never message text), tick checkStall() so a turn whose frames stop arriving
  // for >90s renders a static 「已中断」 instead of an infinite pulse. Any new
  // frame un-stalls (handled in the store).
  const pendingSend = useArslanStore((s) => s.pending);
  const stalled = useArslanStore((s) => s.stalled);
  // S3-M1: the in-flight recorded run's id (spawn dispatches only) — the cancel
  // target for the composer stop button. Null ⇒ nothing cancellable ⇒ no button.
  const activeRunId = useArslanStore((s) => s.activeRunId);
  // Latch after a stop click so a second click can't double-POST; a new run
  // (activeRunId change, including → null on stream_end/run_cancelled) resets it.
  const [stopPending, setStopPending] = useState(false);
  useEffect(() => { setStopPending(false); }, [activeRunId]);
  const handleStopRun = () => {
    if (activeRunId == null || stopPending) return;
    setStopPending(true);
    // Fire-and-forget (one-shot action convention): the authoritative outcome
    // arrives as a run_cancelled frame; on failure re-enable so the user can retry.
    api.cancelRun(activeRunId).catch((err) => {
      console.error(`[cancelRun] failed for run ${activeRunId}`, err);
      setStopPending(false);
    });
  };
  const turnActive = thinking || liveStreaming || pendingSend || pendingRoute != null;
  useEffect(() => {
    if (!turnActive) return;
    const iv = setInterval(() => useArslanStore.getState().checkStall(), 5_000);
    return () => clearInterval(iv);
  }, [turnActive]);
  const llmError = useArslanStore((s) => s.error);
  const clearLlmError = useArslanStore((s) => s.clearError);
  const [inputValue, setInputValue] = useState('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const attach = useComposerAttach(setAttachments);

  // @-mention autocomplete for the chat composer — a dropdown of this conversation's roster
  // members that filters as you type `@…` and inserts the full `@Name ` on pick (so routing
  // gets an exact name). Chat composer only (empty-state hero intentionally excluded).
  const chatInputRef = useRef<HTMLInputElement>(null);
  const [mention, setMention] = useState<{ query: string; index: number } | null>(null);
  const mentionCands = React.useMemo(
    () => (mention ? filterRoster(roster, mention.query).slice(0, 8) : []),
    [mention, roster],
  );
  const syncMention = (value: string, caret: number | null) => {
    const tok = caret == null ? null : activeMention(value, caret);
    setMention(tok ? { query: tok.query, index: 0 } : null);
  };
  const pickMention = (name: string) => {
    const el = chatInputRef.current;
    const caret = el?.selectionStart ?? inputValue.length;
    const tok = activeMention(inputValue, caret);
    if (!tok) return;
    const next = insertMention(inputValue, tok, caret, name);
    setInputValue(next.value);
    attach.onInputChange(next.value);
    setMention(null);
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(next.caret, next.caret); });
  };
  const onMentionKeyDown = (e: React.KeyboardEvent) => {
    if (!mention || mentionCands.length === 0) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setMention((m) => m && { ...m, index: (m.index + 1) % mentionCands.length }); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setMention((m) => m && { ...m, index: (m.index - 1 + mentionCands.length) % mentionCands.length }); }
    else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickMention(mentionCands[mention.index]?.spawnName ?? ''); }
    else if (e.key === 'Escape') { e.preventDefault(); setMention(null); }
  };
  // Optimistic verdicts: filled immediately on click, before the backend verdict_recorded
  // frame round-trips (which sets msg.verdict via the store). Keyed by messageId.
  // KNOWN LIMITATION: verdict_recorded carries no messageId, so the store marks the spawn's
  // MOST-RECENT deliverable. On a spawn with multiple un-voted deliverables, voting an older
  // one fills it optimistically here while the real verdict lands on the newest — they can
  // disagree (no rollback by design). The common single-deliverable case is exact. A proper
  // fix needs the backend to echo the messageId on verdict_recorded.
  const [optimisticVerdicts, setOptimisticVerdicts] = useState<Record<number, 'accept' | 'discard'>>({});
  const castVerdict = (action: 'accept' | 'discard', spawnId: number, messageId?: number) => {
    if (messageId != null) setOptimisticVerdicts((p) => ({ ...p, [messageId]: action }));
    onDeliverableVerdict?.(action, spawnId, messageId);
  };
  const [replayRunId, setReplayRunId] = useState<number | null>(null);

  // Open sandbox sessions: { spawnId, sessionId, seed? }. Multiple stay alive at once
  // (each SandboxPanel keeps its own socket); the 45% pane shows the active one, the
  // rest are mounted-but-hidden. seed = a deliverable to tune (refine entry).
  type OpenSandbox = { spawnId: string; sessionId: string; seed: string | null };
  const [openSandboxes, setOpenSandboxes] = useState<OpenSandbox[]>([]);
  const [activeSandboxSpawnId, setActiveSandboxSpawnId] = useState<string | null>(null);

  const openSandbox = (spawnId: string, seed: string | null = null) => {
    setOpenSandboxes((prev) =>
      prev.some((s) => s.spawnId === spawnId)
        ? prev.map((s) => (s.spawnId === spawnId && seed ? { ...s, seed } : s))
        : [...prev, { spawnId, sessionId: `sbx-${spawnId}-${prev.length}-${performance.now()}`, seed }]
    );
    setActiveSandboxSpawnId(spawnId);
  };
  const closeSandbox = (spawnId: string) => {
    const remaining = openSandboxes.filter((s) => s.spawnId !== spawnId);
    setOpenSandboxes(remaining);
    // If the closed pane was active, promote another open sandbox (if any) so the user
    // never lands on an empty-but-non-full layout.
    setActiveSandboxSpawnId((cur) => (cur === spawnId ? (remaining[0]?.spawnId ?? null) : cur));
  };
  const splitSpawnId = activeSandboxSpawnId;  // back-compat alias for the layout width logic

  // Global Integration Discovery & Repository Engine — no MCP backend yet; tool-hub disabled
  const [showSandboxSearch, setShowSandboxSearch] = useState(true);
  const [integrationQuery, setIntegrationQuery] = useState('');
  const isEvaluating = false; // evaluation backend not yet available
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [mcpRegistry] = useState<{name: string, url: string, description: string, tags: string[]}[]>([]); // no real MCP servers yet
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [skillRegistry] = useState<{name: string, repo: string, capabilities: string[]}[]>([]);
  const evaluationResult = null;

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

  // When user scrolls up, release the stick. When they scroll back near the bottom, re-engage.
  const handleScrollContainerScroll = () => {
    const el = scrollContainerRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  // Scroll container to bottom instantly (reliable during streaming).
  const scrollToBottom = () => {
    const el = scrollContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  // Observe the size of the scroll container's content so streaming tokens trigger scroll.
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      if (stickToBottomRef.current) scrollToBottom();
    });
    // Observe the first child (the inner content wrapper) if present, else the container itself.
    const target = el.firstElementChild ?? el;
    ro.observe(target);
    return () => ro.disconnect();
  }, []);

  // When chatHistory gains a new user message (just sent), force stick to bottom.
  useEffect(() => {
    const last = chatHistory[chatHistory.length - 1];
    if (last?.sender === 'user') {
      stickToBottomRef.current = true;
      scrollToBottom();
    } else if (stickToBottomRef.current) {
      scrollToBottom();
    }
  }, [chatHistory]);


  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim()) return;

    const text = inputValue.trim();
    setInputValue('');

    // Attachments with text (docs/urls/OCR'd images) ride into context; image chips
    // where OCR found nothing stay preview-only (empty text) and contribute nothing.
    const context = attachments.map((a) => a.text).filter(Boolean).join("\n\n---\n\n");
    const names = attachments.filter((a) => a.text).map((a) => a.name);
    // Every attachment (incl. OCR-none images) echoes into the sent bubble as a
    // thumbnail/chip. previewUrl is a session-only object-URL — kept alive by clearing
    // with { revokeUrls: false } below so the rendered message can still show it.
    const display: MessageAttachment[] = attachments.map((a) => ({ name: a.name, kind: a.kind, previewUrl: a.previewUrl }));
    const clearAttachments = () => attach.clear({ revokeUrls: false });

    if (onSendMessage) {
      // Live WS path: delegate to parent's onSendMessage (store + WS send)
      onSendMessage(text, context || display.length ? { context, names, display } : undefined);
      clearAttachments();
      return;
    }

    clearAttachments();

    // Non-wired thread: append the user message only; no fabricated assistant reply.
    const userMsg: Message = {
      id: `msg-user-${Date.now()}`,
      sender: 'user',
      senderName: displayName.trim() || t('common.you'),
      senderAvatar: '🦁',
      text,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      ...(display.length ? { attachments: display } : {}),
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
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {(() => {
            // Derive member spawns from the live store roster
            const rosterIds = new Set(roster.map((m) => String(m.spawnId)));
            const memberSpawns = spawns.filter((s) => rosterIds.has(s.id));
            // Show only roster members; no fallback to mock names
            const activeDisplayList = memberSpawns;

            return activeDisplayList.map(spawn => {
              const isSplitActive = activeSandboxSpawnId === spawn.id;
              const isOpen = openSandboxes.some((s) => s.spawnId === spawn.id);
              // spawn.id is a string; pendingRoute.spawnId / streamSpawnId are numbers → coerce.
              // HX-4/A1: shimmer stops when the turn is stalled — no animation may
              // outlive the runtime frames that justify it.
              const running = !stalled && ((pendingRoute?.spawnId != null && String(pendingRoute.spawnId) === spawn.id)
                || (streamSpawnId != null && String(streamSpawnId) === spawn.id));

              // Indicator: spawns with an open sandbox get a solid primary dot (the
              // active one pulses); spawns with no sandbox get a quiet green idle dot.
              const statusIndicator = isOpen ? (
                <span className="relative flex h-2 w-2 mr-1">
                  {isSplitActive && (
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-60"></span>
                  )}
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
                </span>
              ) : (
                <span className="relative flex h-1.5 w-1.5 mr-1">
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-success/80"></span>
                </span>
              );

              return (
                <button
                  key={spawn.id}
                  onClick={() => {
                    if (activeSandboxSpawnId === spawn.id) {
                      closeSandbox(spawn.id);
                    } else {
                      openSandbox(spawn.id);
                    }
                  }}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-all text-xs font-semibold select-none cursor-pointer ${
                    isSplitActive
                      ? 'border-primary bg-primary/10 text-primary'
                      : isOpen
                      ? 'border-primary/40 bg-primary/5 text-foreground hover:border-primary/60'
                      : 'border-border bg-surface/40 hover:border-border-strong text-muted-foreground hover:text-foreground'
                  }`}
                  title={
                    isOpen
                      ? `${spawn.name} sandbox open — click to ${isSplitActive ? 'close' : 'view'}`
                      : `Open ${spawn.name} sandbox`
                  }
                >
                  {statusIndicator}
                  <span className={running ? 'shiny-text' : undefined}>{spawn.name}</span>
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
          <div ref={scrollContainerRef} onScroll={handleScrollContainerScroll} className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
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
                    const period = hr < 12 ? 'morning' : hr < 18 ? 'afternoon' : 'evening';
                    const greeting = t(`orchestrator.greeting_${period}`);
                    const name = displayName.trim();
                    return name
                      ? t('orchestrator.greeting_named', { greeting, name })
                      : greeting;
                  })()}
                </h1>
              </div>
            </div>

            {/* No-model hint — shown when zero ProviderConfigs are configured */}
            <NoModelHint hasModel={hasModel} onOpenSettings={onOpenSettings ?? (() => {})} />

            {/* Luxurious prompt input box resembling Claude's container design */}
            <div
              className={`relative w-full max-w-xl bg-surface border rounded-2xl p-4 flex flex-col space-y-3 focus-within:border-primary/60 focus-within:ring-1 focus-within:ring-ring/30 shadow-2xl transition-all ${attach.dragActive ? 'border-primary border-dashed' : 'border-border-strong'}`}
              {...attach.dndHandlers}
            >
              <AttachChips attachments={attachments} onRemove={attach.removeAt} />
              <textarea
                id="landing-message-input"
                rows={3}
                value={inputValue}
                onChange={(e) => { setInputValue(e.target.value); attach.onInputChange(e.target.value); }}
                onPaste={attach.onPaste}
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
                {/* Left group: attach control + model indicator */}
                <div className="flex items-center gap-2 min-w-0">
                  <AttachControl busy={attach.busy} onPickFiles={attach.addFiles} />
                  {/* Model indicator — static chip showing real configured model */}
                  <div className="flex items-center gap-1 bg-background/40 px-2.5 py-1 rounded-full border border-border text-[10px] font-mono text-muted-foreground max-w-[160px] sm:max-w-none truncate">
                    <Cpu className="w-3 h-3 text-primary flex-shrink-0" />
                    <span className="ml-0.5 truncate">{settings ? `${settings.llm_provider} · ${settings.llm_model}` : '—'}</span>
                  </div>
                </div>

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

              {attach.error && <div className="attach-error mt-1" role="alert">{attach.error}</div>}
              {attach.dragActive && (
                <div className="absolute inset-0 z-10 rounded-2xl flex items-center justify-center pointer-events-none bg-primary/[0.08] text-primary text-xs font-semibold">
                  {t('attach.drop_hint')}
                </div>
              )}
            </div>

            {/* Quick action pill suggestions inspired by Claude suggestions */}
            <div className="w-full max-w-xl text-center space-y-2">
              <span className="text-[10px] font-mono text-subtle-foreground uppercase tracking-widest block">{t('orchestrator.presets_label')}</span>
              <div className="flex flex-wrap gap-1.5 justify-center">
                {[
                  { icon: 'vuln-test', label: t('orchestrator.preset_code_audit'), prompt: "Research and summarize the latest developments in AI agent frameworks — compare key architectures, use cases, and tradeoffs." },
                  { icon: 'financial-res', label: t('orchestrator.preset_financial'), prompt: "Analyze publicly available data on a company or market sector and produce a structured research report with key metrics and outlook." },
                  { icon: 'seo-opt', label: t('orchestrator.preset_slogan'), prompt: "Write polished, on-brand copy for a product launch: tagline, three feature bullet points, and a call-to-action paragraph." },
                  { icon: 'web-search', label: t('orchestrator.preset_drive'), prompt: "Find the top trending AI and developer tool repositories on GitHub this week and summarize what each one does." }
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
              // "recruited" (delegation cell 6): Arslan already answered the task doer-first;
              // accepting the invite enrolls the spawn into THIS session's roster (rosters are
              // session-ephemeral) so the user can @ it directly.
              // 'left' is matched explicitly; unknown future actions fall back to the
              // neutral joined label — an unknown action must never render as a LEAVE.
              const label = msg.rosterAction === 'left'
                ? t('chat.roster_left', { name })
                : msg.rosterAction === 'recruited'
                  ? t('chat.roster_recruited', { name })
                  : msg.rosterAction === 'joined_no_pending'
                    ? t('chat.roster_joined_no_pending', { name })
                    : t('chat.roster_joined', { name });
              return (
                <div key={msg.id} className="flex items-center gap-3 py-1 select-none">
                  <div className="flex-1 h-px bg-border/60" />
                  <span className="text-[10px] text-subtle-foreground font-mono whitespace-nowrap">
                    {msg.rosterAction === 'left' ? '✕' : '🔗'} {label}
                  </span>
                  <div className="flex-1 h-px bg-border/60" />
                </div>
              );
            }

            // PA-3 structured clarification card: Arslan needs the user to pick ONE of
            // 2-4 directions. Picking sends the option's LABEL as a normal user_message
            // over the same send path the composer uses, then flips the card to its
            // answered (disabled) state via the store — one click, one shot.
            if (msg.clarifyOptions) {
              const co = msg.clarifyOptions;
              return (
                <div key={msg.id} className="flex gap-3 items-start py-2">
                  <img src="/arslan-mark.png" alt="Arslan" className="w-7 h-7 object-contain select-none shrink-0 arslan-mark mt-0.5" draggable={false} />
                  <ClarifyOptionsCard
                    question={co.question}
                    options={co.options}
                    answered={co.answered}
                    onPick={(label) => {
                      useArslanStore.getState().markClarifyAnswered(Number(msg.id));
                      onSendMessage?.(label);
                    }}
                  />
                </div>
              );
            }

            // Routing announcement: need restatement + @spawn duty lines. Rendered as a
            // FULL Arslan message bubble (avatar + name header + arslan-bubble styling per
            // layout variant) — user feedback: the old quiet inline line above the
            // "X joined" divider read as an anonymous system line, not Arslan speaking.
            // MentionText keeps the @-mention chips inside the bubble.
            if (msg.isRouteAnnouncement) {
              if (currentStyle === 'brutalist') {
                return (
                  <div key={msg.id} className="border-2 border-primary/60 p-4 font-mono text-[12px] bg-background shadow-[4px_4px_0px_var(--color-primary)] relative">
                    <div className="flex items-center justify-between pb-2 border-b border-dashed border-border select-none mb-3">
                      <div className="flex items-center gap-2">
                        <span className="text-primary font-bold flex items-center gap-1.5">
                          [<SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5 inline-block" />] {msg.senderName.toUpperCase()}
                        </span>
                        <span className="text-[10px] px-2 py-0.5 bg-primary/20 text-primary">
                          {msg.sender.toUpperCase()}
                        </span>
                      </div>
                    </div>
                    <MentionText
                      text={msg.text}
                      knownNames={mentionNames}
                      className="text-muted-foreground font-sans leading-relaxed text-[12px]"
                    />
                  </div>
                );
              }
              if (currentStyle === 'linear') {
                return (
                  <div key={msg.id} className="text-[12px] space-y-2">
                    <div className="flex items-center gap-2 select-none text-[11px]">
                      <img src="/arslan-mark.png" alt="Arslan" className="w-5 h-5 object-contain select-none arslan-mark" draggable={false} />
                      <span className="font-bold text-foreground">{msg.senderName}</span>
                      <span className="text-[9px] bg-surface-raised text-primary px-2 py-0.5 rounded font-mono uppercase">
                        Orchestrator
                      </span>
                    </div>
                    <div className="pl-5">
                      <MentionText
                        text={msg.text}
                        knownNames={mentionNames}
                        className="text-foreground font-sans leading-relaxed text-[12.5px]"
                      />
                    </div>
                  </div>
                );
              }
              // quartz (default)
              return (
                <div key={msg.id} className="flex gap-4">
                  <div className="flex flex-col items-center select-none">
                    <div className="relative">
                      <img src="/arslan-mark.png" alt="Arslan" className="w-9 h-9 object-contain select-none arslan-mark" draggable={false} />
                      <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-background bg-success" />
                    </div>
                  </div>
                  <div className="space-y-3 max-w-2xl">
                    <div className="flex items-center gap-1.5 select-none">
                      <span className="text-[11px] font-semibold text-muted-foreground">{msg.senderName}</span>
                      <span className="text-[9px] bg-primary/10 text-primary px-2 py-0.5 rounded font-semibold font-mono uppercase tracking-wider">
                        {t('app.name')} Orchestrator
                      </span>
                    </div>
                    <div className="px-4 py-3 text-[12.5px] leading-relaxed relative bg-surface/80 backdrop-blur border border-border-strong text-foreground rounded-2xl rounded-tl-none shadow-sm shadow-black/40">
                      <MentionText
                        text={msg.text}
                        knownNames={mentionNames}
                        className="text-[12.5px] leading-relaxed font-sans"
                      />
                    </div>
                  </div>
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
                        {msg.refinedFrom != null && (
                          <span className="text-[9px] bg-success/10 text-success px-2 py-0.5 rounded font-mono uppercase tracking-wider font-semibold">{t('orchestrator.refined_badge')}</span>
                        )}
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
                        ? <>
                            <SentAttachments attachments={msg.attachments} />
                            <p className="whitespace-pre-line font-sans leading-relaxed">{msg.text}</p>
                          </>
                        : <MessageBody text={msg.text} streaming={msg.id === '__streaming__'} hasMessageActions={isSpawn && !msg.isProposal && !!msg.spawnId} className="text-[12.5px] leading-relaxed font-sans [&>*:first-child]:mt-0 [&>*:last-child]:mb-0" />
                      }
                      {msg.cancelled && <RunCancelledMarker />}
                      {msg.usage && <UsageChip usage={msg.usage} />}

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
                            {msg.spawnIntro.tools.map(toolId => (
                                <span
                                  key={toolId}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-mono bg-surface text-muted-foreground px-2 py-0.5 rounded-lg hover:text-foreground transition-all"
                                >
                                  {getIcon(toolId, 'w-3 h-3')}
                                  <span className="font-semibold">{capabilityLabel(toolId)}</span>
                                </span>
                            ))}
                            {/* Render Skill tags with lucide icon */}
                            {msg.spawnIntro.skills.map(skillId => (
                                <span
                                  key={skillId}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-mono bg-primary/10 text-primary px-2 py-0.5 rounded-lg transition-all"
                                >
                                  {getIcon(skillId, 'w-3 h-3')}
                                  <span className="font-semibold">{capabilityLabel(skillId)}</span>
                                </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* 2. Tool-Activity Card — humanized headline, raw JSON behind 详情 (shared component) */}
                    {msg.toolActivity && <ToolActivityCard activity={msg.toolActivity} />}

                    {/* 🔒 HTML deliverable card — artifactHtml comes ONLY from the backend
                        stream_end frame's kind:"html" artifact (HX-2), never LLM text.
                        Keep the card's own copy button here: the message row copies the
                        SUMMARY (display_content), not the source — without card-copy the
                        source would be un-copyable. (hasMessageActions only suppresses
                        card-copy on the salvage path, where row copy == card copy.) */}
                    {msg.artifactHtml && (
                      <HtmlDocCard html={msg.artifactHtml.content} title={msg.artifactHtml.title}
                                   filename={msg.artifactHtml.filename} bytes={msg.artifactHtml.bytes}
                                   truncated={!msg.artifactHtml.complete} />
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
                    {isSpawn && !msg.isProposal && msg.spawnId && (() => {
                      const verdict = msg.verdict ?? (msg.messageId != null ? optimisticVerdicts[msg.messageId] : undefined);
                      if (verdict) {
                        return (
                          <div data-testid="verdict-voted" data-verdict={verdict}
                            className="flex flex-wrap items-center gap-2 px-2 py-1">
                            <ThumbsUp className={`w-3.5 h-3.5 ${verdict === 'accept' ? 'text-success fill-current' : 'text-subtle-foreground opacity-30'}`} />
                            <ThumbsDown className={`w-3.5 h-3.5 ${verdict === 'discard' ? 'text-danger fill-current' : 'text-subtle-foreground opacity-30'}`} />
                            <CopyButton text={msg.text} className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-primary text-[11px] rounded-md hover:bg-primary/10 transition-all select-none" />
                            <button title={t('orchestrator.refine')}
                              onClick={() => openSandbox(String(msg.spawnId), msg.text)}
                              className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-primary text-[11px] font-mono uppercase tracking-wider rounded-md hover:bg-primary/10 transition-all select-none">
                              <Wand2 className="w-3.5 h-3.5" />
                              <span>{t('orchestrator.refine')}</span>
                            </button>
                          </div>
                        );
                      }
                      return (
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <button title={t('orchestrator.verdict_like')}
                            onClick={() => castVerdict('accept', Number(msg.spawnId), msg.messageId)}
                            className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-success text-[11px] rounded-md hover:bg-success/10 transition-all select-none">
                            <ThumbsUp className="w-3.5 h-3.5" />
                          </button>
                          <button title={t('orchestrator.verdict_dislike')}
                            onClick={() => castVerdict('discard', Number(msg.spawnId), msg.messageId)}
                            className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-danger text-[11px] rounded-md hover:bg-danger/10 transition-all select-none">
                            <ThumbsDown className="w-3.5 h-3.5" />
                          </button>
                          <CopyButton text={msg.text} className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-primary text-[11px] rounded-md hover:bg-primary/10 transition-all select-none" />
                          <button title={t('orchestrator.refine')}
                            onClick={() => openSandbox(String(msg.spawnId), msg.text)}
                            className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-primary text-[11px] font-mono uppercase tracking-wider rounded-md hover:bg-primary/10 transition-all select-none">
                            <Wand2 className="w-3.5 h-3.5" />
                            <span>{t('orchestrator.refine')}</span>
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
                      );
                    })()}
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
                      <SentAttachments attachments={msg.attachments} />
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
                      {msg.refinedFrom != null && (
                        <span className="text-[10px] px-2 py-0.5 bg-success/20 text-success">{t('orchestrator.refined_badge')}</span>
                      )}
                    </div>
                    <span className="text-subtle-foreground text-[10px]">{msg.timestamp}</span>
                  </div>

                  {isUser
                    ? <p className="whitespace-pre-line text-muted-foreground font-mono leading-relaxed">{msg.text}</p>
                    : <MessageBody text={msg.text} streaming={msg.id === '__streaming__'} hasMessageActions={isSpawn && !msg.isProposal && !!msg.spawnId} className="text-muted-foreground font-sans leading-relaxed [&>*:first-child]:mt-0 [&>*:last-child]:mb-0" />
                  }
                  {msg.cancelled && <RunCancelledMarker />}
                  {msg.usage && <UsageChip usage={msg.usage} />}

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

                  {/* Tool Activity — humanized headline, raw JSON behind 详情 (shared component) */}
                  {msg.toolActivity && (
                    <div className="mt-4">
                      <ToolActivityCard activity={msg.toolActivity} />
                    </div>
                  )}

                  {/* 🔒 HTML deliverable card — backend stream_end kind:"html" artifact only (HX-2). */}
                  {msg.artifactHtml && (
                    <div className="mt-4">
                      <HtmlDocCard html={msg.artifactHtml.content} title={msg.artifactHtml.title}
                                   filename={msg.artifactHtml.filename} bytes={msg.artifactHtml.bytes}
                                   truncated={!msg.artifactHtml.complete} hasMessageActions />
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
                  {isSpawn && !msg.isProposal && msg.spawnId && (() => {
                    const verdict = msg.verdict ?? (msg.messageId != null ? optimisticVerdicts[msg.messageId] : undefined);
                    if (verdict) {
                      return (
                        <div data-testid="verdict-voted" data-verdict={verdict}
                          className="mt-4 flex flex-wrap items-center gap-2 px-2 py-1">
                          <ThumbsUp className={`w-3.5 h-3.5 ${verdict === 'accept' ? 'text-success fill-current' : 'text-subtle-foreground opacity-30'}`} />
                          <ThumbsDown className={`w-3.5 h-3.5 ${verdict === 'discard' ? 'text-danger fill-current' : 'text-subtle-foreground opacity-30'}`} />
                          <CopyButton text={msg.text} className="flex items-center gap-1 px-2 py-1 border-2 border-border bg-background hover:border-primary text-subtle-foreground hover:text-primary text-[11px] transition-all select-none" />
                          <button title={t('orchestrator.refine')}
                            onClick={() => openSandbox(String(msg.spawnId), msg.text)}
                            className="flex items-center gap-1 px-2 py-1 border-2 border-border bg-background hover:border-primary text-subtle-foreground hover:text-primary text-[11px] font-mono uppercase tracking-wider transition-all select-none">
                            <Wand2 className="w-3.5 h-3.5" />
                            <span>{t('orchestrator.refine')}</span>
                          </button>
                        </div>
                      );
                    }
                    return (
                      <div className="mt-4 flex items-center gap-2 flex-wrap">
                        <button title={t('orchestrator.verdict_like')}
                          onClick={() => castVerdict('accept', Number(msg.spawnId), msg.messageId)}
                          className="flex items-center gap-1 px-2 py-1 border-2 border-border bg-background hover:border-success text-subtle-foreground hover:text-success text-[11px] transition-all select-none">
                          <ThumbsUp className="w-3.5 h-3.5" />
                        </button>
                        <button title={t('orchestrator.verdict_dislike')}
                          onClick={() => castVerdict('discard', Number(msg.spawnId), msg.messageId)}
                          className="flex items-center gap-1 px-2 py-1 border-2 border-border bg-background hover:border-danger text-subtle-foreground hover:text-danger text-[11px] transition-all select-none">
                          <ThumbsDown className="w-3.5 h-3.5" />
                        </button>
                        <CopyButton text={msg.text} className="flex items-center gap-1 px-2 py-1 border-2 border-border bg-background hover:border-primary text-subtle-foreground hover:text-primary text-[11px] transition-all select-none" />
                        <button title={t('orchestrator.refine')}
                          onClick={() => openSandbox(String(msg.spawnId), msg.text)}
                          className="flex items-center gap-1 px-2 py-1 border-2 border-border bg-background hover:border-primary text-subtle-foreground hover:text-primary text-[11px] font-mono uppercase tracking-wider transition-all select-none">
                          <Wand2 className="w-3.5 h-3.5" />
                          <span>{t('orchestrator.refine')}</span>
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
                    );
                  })()}
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
                        className="px-4 py-2.5 text-foreground text-[12.5px] leading-relaxed font-sans"
                        style={{
                          background: 'rgba(120,140,170,0.10)',
                          border: '1px solid rgba(255,255,255,0.08)',
                          borderRadius: '12px 12px 4px 12px',
                        }}
                      >
                        <SentAttachments attachments={msg.attachments} />
                        <span className="whitespace-pre-line">{msg.text}</span>
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
                    {msg.refinedFrom != null && (
                      <span className="text-[9px] bg-success/10 text-success px-2 py-0.5 rounded font-mono uppercase">{t('orchestrator.refined_badge')}</span>
                    )}
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
                  <MessageBody text={msg.text} indent streaming={msg.id === '__streaming__'} hasMessageActions={isSpawn && !msg.isProposal && !!msg.spawnId} className="text-foreground font-sans leading-relaxed text-[12.5px] pl-5 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0" />
                  {msg.cancelled && <div className="pl-5"><RunCancelledMarker /></div>}
                  {msg.usage && <div className="pl-5"><UsageChip usage={msg.usage} /></div>}

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

                  {/* Linear Minimal Tool activity — humanized headline, raw JSON behind 详情 (shared component) */}
                  {msg.toolActivity && (
                    <div className="pl-5 pt-2">
                      <ToolActivityCard activity={msg.toolActivity} />
                    </div>
                  )}

                  {/* 🔒 HTML deliverable card — backend stream_end kind:"html" artifact only (HX-2). */}
                  {msg.artifactHtml && (
                    <div className="pl-5 pt-2">
                      <HtmlDocCard html={msg.artifactHtml.content} title={msg.artifactHtml.title}
                                   filename={msg.artifactHtml.filename} bytes={msg.artifactHtml.bytes}
                                   truncated={!msg.artifactHtml.complete} hasMessageActions />
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
                  {isSpawn && !msg.isProposal && msg.spawnId && (() => {
                    const verdict = msg.verdict ?? (msg.messageId != null ? optimisticVerdicts[msg.messageId] : undefined);
                    if (verdict) {
                      return (
                        <div data-testid="verdict-voted" data-verdict={verdict}
                          className="pl-5 pt-2 flex flex-wrap items-center gap-2 px-2 py-1">
                          <ThumbsUp className={`w-3.5 h-3.5 ${verdict === 'accept' ? 'text-success fill-current' : 'text-subtle-foreground opacity-30'}`} />
                          <ThumbsDown className={`w-3.5 h-3.5 ${verdict === 'discard' ? 'text-danger fill-current' : 'text-subtle-foreground opacity-30'}`} />
                          <CopyButton text={msg.text} className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-primary text-[11px] rounded-md hover:bg-primary/10 transition-all select-none" />
                          <button title={t('orchestrator.refine')}
                            onClick={() => openSandbox(String(msg.spawnId), msg.text)}
                            className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-primary text-[11px] font-mono uppercase tracking-wider rounded-md hover:bg-primary/10 transition-all select-none">
                            <Wand2 className="w-3.5 h-3.5" />
                            <span>{t('orchestrator.refine')}</span>
                          </button>
                        </div>
                      );
                    }
                    return (
                      <div className="pl-5 pt-2 flex flex-wrap items-center gap-1.5">
                        <button title={t('orchestrator.verdict_like')}
                          onClick={() => castVerdict('accept', Number(msg.spawnId), msg.messageId)}
                          className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-success text-[11px] rounded-md hover:bg-success/10 transition-all select-none">
                          <ThumbsUp className="w-3.5 h-3.5" />
                        </button>
                        <button title={t('orchestrator.verdict_dislike')}
                          onClick={() => castVerdict('discard', Number(msg.spawnId), msg.messageId)}
                          className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-danger text-[11px] rounded-md hover:bg-danger/10 transition-all select-none">
                          <ThumbsDown className="w-3.5 h-3.5" />
                        </button>
                        <CopyButton text={msg.text} className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-primary text-[11px] rounded-md hover:bg-primary/10 transition-all select-none" />
                        <button title={t('orchestrator.refine')}
                          onClick={() => openSandbox(String(msg.spawnId), msg.text)}
                          className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-primary text-[11px] font-mono uppercase tracking-wider rounded-md hover:bg-primary/10 transition-all select-none">
                          <Wand2 className="w-3.5 h-3.5" />
                          <span>{t('orchestrator.refine')}</span>
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
                    );
                  })()}
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
        {(thinking || liveStreaming) && (
          <div className="flex gap-3 items-start py-2 select-none">
            <img src="/arslan-mark.png" alt="Arslan" className="w-7 h-7 object-contain select-none shrink-0 arslan-mark" draggable={false} />
            {/* LiveActivity carries its own motion (✳ pulse + per-step spinner) — the old
                bouncing-dots trio beside it was redundant noise (user-flagged). */}
            <div className="px-3 py-2 bg-surface/80 border border-border-strong rounded-2xl rounded-tl-none">
              {stalled ? (
                /* HX-4/A1: >90s without any runtime frame — everything goes still.
                   Static muted marker, no spinner/pulse/scramble. */
                <span data-testid="stalled-indicator" className="text-[11px] font-mono text-danger/80 select-none">
                  ⏸ {t('working.stalled')}
                </span>
              ) : (
                <LiveActivity steps={liveSteps} startedAt={workStartedAt} phrases={[t('working.summon'), t('working.context'), t('working.tools'), t('working.compose')]} />
              )}
            </div>
          </div>
        )}

        {/* Inline roster-invite card: rendered as the last item in the chat flow when
            Arslan proposes pulling a not-yet-in-roster spawn in. Accept → join + dispatch
            the parked task; Dismiss → clear. Not an overlay — it reads inline below the
            last message. */}
        {pendingInvite && (
          <InviteConfirmCard
            spawnId={pendingInvite.spawnId}
            spawnName={resolveSpawnName(spawns, pendingInvite.spawnId)}
            reason={pendingInvite.reason}
            onConfirm={(spawnId) => onAcceptInvite?.(spawnId)}
            onCancel={() => onDismissInvite?.()}
          />
        )}
      </div>

      {/* Input Message Form Panel */}
      {chatHistory.length > 0 && (
        <footer className="p-4 border-t border-border bg-background/80 backdrop-blur shrink-0 z-10 select-none">
          <form onSubmit={handleSendMessage} className="max-w-4xl mx-auto">
            <div
              className={`composer-box${attach.dragActive ? ' composer-box--drop' : ''}`}
              {...attach.dndHandlers}
            >
              {mention && mentionCands.length > 0 && (
                <div data-testid="mention-dropdown"
                  className="absolute bottom-full left-0 mb-1 w-64 max-h-56 overflow-auto bg-surface border border-border-strong rounded-xl shadow-2xl z-30 py-1">
                  {mentionCands.map((m, i) => (
                    <button key={m.spawnId} type="button"
                      onMouseDown={(e) => { e.preventDefault(); pickMention(m.spawnName ?? ''); }}
                      onMouseEnter={() => setMention((s) => s && { ...s, index: i })}
                      className={`w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-[13px] ${i === mention.index ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-foreground/[0.04]'}`}>
                      <SpawnAvatar seed={m.spawnName ?? ''} size={20} />
                      <span className="flex-1 truncate">{m.spawnName}</span>
                    </button>
                  ))}
                </div>
              )}
              <AttachChips attachments={attachments} onRemove={attach.removeAt} />
              <input
                id="chat-message-input"
                ref={chatInputRef}
                type="text"
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                spellCheck={false}
                value={inputValue}
                onChange={(e) => { setInputValue(e.target.value); attach.onInputChange(e.target.value); syncMention(e.target.value, e.target.selectionStart); }}
                onKeyDown={onMentionKeyDown}
                onBlur={() => setMention(null)}
                onPaste={attach.onPaste}
                placeholder={t('orchestrator.placeholder_chat')}
                className="w-full bg-transparent text-xs text-foreground placeholder-subtle-foreground focus:outline-none font-sans px-1 py-1.5"
              />
              <div className="composer-row">
                <AttachControl busy={attach.busy} onPickFiles={attach.addFiles} />
                {/* Right-side action group: composer-row is space-between, so stop
                    must share a wrapper with send to sit NEXT to it (not centered). */}
                <div className="flex items-center gap-1.5">
                  {/* S3-M1 stop button: only while a recorded run is in flight
                      (activeRunId set from stream_start). Renders NEXT to send —
                      the send button's disabled-while-active behavior is untouched. */}
                  {activeRunId != null && (
                    <button
                      type="button"
                      data-testid="stop-run-button"
                      title={t('chat.stopRun')}
                      aria-label={t('chat.stopRun')}
                      disabled={stopPending}
                      onClick={handleStopRun}
                      className="p-2 bg-danger/15 text-danger hover:bg-danger/25 disabled:opacity-50 rounded-lg transition-all"
                    >
                      <Square className="w-4 h-4" fill="currentColor" />
                    </button>
                  )}
                  <button
                    id="chat-send-submit"
                    type="submit"
                    disabled={!inputValue.trim()}
                    className="p-2 bg-primary text-primary-foreground hover:bg-primary-hover disabled:bg-surface-raised disabled:text-subtle-foreground disabled:opacity-50 font-bold uppercase rounded-lg transition-all"
                  >
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
              {attach.dragActive && <div className="composer-drop-hint">{t('attach.drop_hint')}</div>}
            </div>
            {attach.error && <div className="attach-error max-w-4xl mx-auto mt-1.5" role="alert">{attach.error}</div>}
          </form>
          {shellEnabled && (
            <div className="max-w-4xl mx-auto mt-2 flex items-center justify-end">
              <label className="shell-policy-pill" data-testid="shell-policy-pill">
                <Terminal className="w-3 h-3 text-primary shrink-0" />
                <span className="shell-policy-pill__label">{t('runcmd.pillLabel')}</span>
                <select
                  aria-label={t('settings.labelShellConfirmPolicy')}
                  data-testid="shell-policy-select"
                  value={shellPolicy}
                  onChange={(e) => onShellPolicyChange?.(e.target.value as 'ask_all' | 'ask_risky')}
                  className="shell-policy-pill__select"
                >
                  <option value="ask_all">{t('settings.shellPolicyAskAll')}</option>
                  <option value="ask_risky">{t('settings.shellPolicyAskRisky')}</option>
                </select>
              </label>
            </div>
          )}
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

    {/* Right Pane: Isolated Co-Pilot Private Sandboxes (副对话框). All open sessions stay
        mounted (sockets alive); only the active one is visible, the rest are hidden. */}
    {openSandboxes.map((open) => {
      const spawn = spawns.find((s) => s.id === open.spawnId);
      if (!spawn) return null;
      return (
        <SandboxPanel
          key={open.sessionId}
          spawn={spawn}
          sessionId={open.sessionId}
          seed={open.seed}
          conversationId={conversationId ?? 'main'}
          hidden={open.spawnId !== activeSandboxSpawnId}
          onClose={() => closeSandbox(spawn.id)}
          onMerged={(payload) => {
            // The card lives in the MAIN thread store — reuse the existing
            // deliverable_finalized + verdict_recorded handlers to append it live.
            const store = useArslanStore.getState();
            store.handleFrame({
              type: 'deliverable_finalized', spawn_id: payload.spawn_id,
              message_id: payload.message_id, content: payload.content,
              refined_from: null, spawn_name: payload.spawn_name,
            } as never);
            store.handleFrame({ type: 'verdict_recorded', spawn_id: payload.spawn_id, action: 'accept' } as never);
            closeSandbox(spawn.id);
          }}
        />
      );
    })}
  </div>

  {replayRunId != null && (
    <div className="run-replay-overlay" onClick={() => setReplayRunId(null)}>
      <div className="run-replay-overlay__panel" onClick={(e) => e.stopPropagation()}>
        <RunReplay runId={replayRunId} onClose={() => setReplayRunId(null)} />
      </div>
    </div>
  )}
</div>
);
}
