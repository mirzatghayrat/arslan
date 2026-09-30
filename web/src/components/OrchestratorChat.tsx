import BrandMark from './BrandMark';
import HostRunResultButton from './HostRunResultButton';
import React, { useState, useRef, useEffect, useCallback } from 'react';
import type { ImagePayload } from "../lib/imagePayload";
import {
  ArrowRight,
  AlertTriangle, CheckCircle2, XOctagon,
  CornerDownRight,
  Cpu, X, Square,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import JobCard, { JobResultLabel } from './JobCard';

import { formatUiTime } from '../lib/localeFormatting';
import { getIcon } from './iconMap';
import { Message, MessageAttachment, Spawn } from '../types';
import type { ProviderConfig, ProviderOption } from '../api/client.types';
import ModelSwitcher from './ModelSwitcher';
import { useCapabilityLabel } from '../stores/registryStore';
import { useProfileStore } from '../stores/profileStore';
import SFSymbol from './SFSymbol';
import { SpawnAvatar } from './SpawnAvatar';
import MessageBody, { HtmlDocCard } from './MessageBody';
import CopyButton from './CopyButton';
import LiveActivity from './LiveActivity';
import ToolActivityCard from './ToolActivityCard';
import { useArslanStore } from '../stores/arslanStore';
import { taskErrorKey } from './companion/errors';
import { runtimeErrorText } from '../lib/runtimeErrorText';
import { api } from '../api/client';
import { useSettingsStore } from '../stores/settingsStore';
import { clampEndpointSilenceMs } from '../api/adapters';
import NoModelHint from './NoModelHint';
import RunReplay from './RunReplay';
import PushToTalk from './PushToTalk';
import ConversationToggle from './ConversationToggle';
import { useConversationMode } from '../hooks/useConversationMode';
import { preferredVoiceLocale } from '../lib/speech';
import { useComposerAttach, AttachChips, AttachControl, SentAttachments, attachmentImages, attachmentDelivery, attachmentImageBudgetExceeded } from './ComposerAttach';
import { composerDrafts, getAttachmentDraft, discardComposerDraft } from '../lib/composerDrafts';
import ClarifyOptionsCard from './ClarifyOptionsCard';
import MentionText from './MentionText';
import UsageChip from './UsageChip';

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

// Composer drafts by conversation — module scope so they outlive the component.

interface OrchestratorChatProps {
  chatHistory: Message[];
  setChatHistory: React.Dispatch<React.SetStateAction<Message[]>>;
  /** When provided, user prompts are sent via this callback (live WS) instead of the mock simulation.
   *  `display` echoes ALL attachments into the sent bubble (session-only); `context`/`names`
   *  carry only the text-bearing ones to the backend. */
  onSendMessage?: (text: string, attached?: { context: string; names: string[]; display?: MessageAttachment[]; images?: ImagePayload[] }, opts?: { fromClarify?: boolean }) => void;
  spawns: Spawn[];
  currentStyle: 'quartz' | 'brutalist' | 'linear';
  setCurrentStyle: (style: 'quartz' | 'brutalist' | 'linear') => void;
  activeThread: any;
  /** True when at least one ProviderConfig exists. When false, a hint to configure a model is shown. */
  hasModel?: boolean;
  /** Navigate to the Settings screen. Used by the no-model hint. */
  onOpenSettings?: () => void;
  /** Saved model configs — drives the composer's model chip and its switcher. */
  providerConfigs?: ProviderConfig[];
  /** Provider catalog, for display labels in the switcher. */
  llmProviders?: ProviderOption[];
  /** Ids whose launch-time test is still running. */
  providerTestingIds?: Set<number>;
  /** Make the picked model the primary one. */
  onSelectModel?: (id: number) => void;
  /** The active conversation id. */
  conversationId?: string;
  /** True when the orchestrator-shell capability is enabled (drives the policy pill). */
  shellEnabled?: boolean;
  /** Current shell confirmation posture, shown + flippable in the composer pill. */
  shellPolicy?: 'ask_all' | 'ask_risky';
  /** Called when the user flips the confirmation posture from the composer pill. */
}

export default function OrchestratorChat({
  chatHistory,
  setChatHistory,
  onSendMessage,
  spawns,
  currentStyle,
  setCurrentStyle,
  activeThread,
  hasModel = true,
  onOpenSettings,
  providerConfigs,
  llmProviders,
  providerTestingIds,
  onSelectModel,
  conversationId,
  shellEnabled = false,
  shellPolicy = 'ask_all',
}: OrchestratorChatProps) {
  const { t, i18n } = useTranslation();
  const settings = useSettingsStore((s) => s.settings);
  // What the recogniser should EXPECT to hear. Its own setting first, because
  // the language someone speaks is not the language their interface is in —
  // reading replies aloud already made that mistake once, giving an English
  // voice Chinese sentences.
  const voiceLocale = preferredVoiceLocale(settings?.voice_input_locale, settings?.language);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  // Which microphone control the composer shows. The setting is the user's
  // choice; the toggle below is per session — an app must not start
  // listening because a setting was flipped last week.
  const voiceMode = settings?.voice_mode === 'off' || settings?.voice_mode === 'conversation' ? settings.voice_mode : 'push_to_talk';
  const [conversationOn, setConversationOn] = useState(false);
  const conversation = useConversationMode({
    enabled: voiceMode === 'conversation' && conversationOn,
    locale: voiceLocale,
    silenceMs: clampEndpointSilenceMs(settings?.voice_endpoint_silence_ms),
    onFinal: (text) => { setVoiceError(null); onSendMessage?.(text, undefined); },
    onError: (msg) => { setVoiceError(msg); setConversationOn(false); },
    // The helper is gone (it exited, or the shell lost it). The toggle is ours,
    // so put it back — a lit button over a dead session takes two presses to
    // restart, and the first one looks like it did nothing.
    onEnded: () => setConversationOn(false),
  });
  // 0.1.48: replies are spoken while a voice conversation is running, and only
  // then — the separate "read replies aloud" switch is gone. Talking to it is
  // the request to be talked back to; typing is not.
  const setVoice = useArslanStore((s) => s.setVoice);
  React.useEffect(() => {
    setVoice({ enabled: voiceMode === 'conversation' && conversationOn, lang: voiceLocale });
  }, [voiceMode, conversationOn, voiceLocale, setVoice]);
  // 0.1.42: with voice conversation on, a background job that finishes (or
  // stops to ask for a confirmation) gets ONE spoken line. The confirmation
  // itself is still a click in the window — speech never approves anything.
  const jobNotice = useArslanStore((s) => s.jobNotice);
  const speakLine = useArslanStore((s) => s.speakLine);
  const spokenSeq = React.useRef(jobNotice?.seq ?? 0);
  React.useEffect(() => {
    if (!jobNotice || jobNotice.seq <= spokenSeq.current) return;
    spokenSeq.current = jobNotice.seq;
    if (!(voiceMode === 'conversation' && conversationOn)) return;
    const goal = jobNotice.goal.length > 60 ? `${jobNotice.goal.slice(0, 60)}…` : jobNotice.goal;
    speakLine(jobNotice.kind === 'needs_approval'
      ? t('jobs.spokenApproval')
      : t('jobs.spokenFinished', { goal, outcome: t(`jobs.outcome.${jobNotice.outcome ?? 'partial'}`) }), voiceLocale);
  }, [jobNotice, voiceMode, conversationOn, speakLine, t, voiceLocale]);
  const micControl = voiceMode === 'push_to_talk' ? (
    <PushToTalk
      locale={voiceLocale}
      onPartial={(text) => { setVoiceError(null); setInputValue(text); }}
      onFinal={(text) => setInputValue(text)}
      onError={(msg) => setVoiceError(msg)}
    />
  ) : voiceMode === 'conversation' ? (
    <ConversationToggle
      active={conversationOn}
      phase={conversation.phase}
      partial={conversation.partial}
      onToggle={() => setConversationOn((v) => !v)}
    />
  ) : null;
  // Real capability display names (key → name) for equipped-capability chips.
  const capabilityLabel = useCapabilityLabel();
  // Client-side user display name for the greeting + own-message sender label.
  const displayName = useProfileStore((s) => s.displayName);
  const pendingRoute = useArslanStore((s) => s.pendingRoute);
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
  const llmErrorTranslations = useArslanStore((s) => s.errorTranslations);
  const clearLlmError = useArslanStore((s) => s.clearError);
  // Draft survives unmount. The composer used to hold its text in plain
  // component state, so switching to Settings (say, to fix an API key) and
  // back destroyed whatever was typed — reported from the first packaged
  // install, where that round-trip is the very first thing a new user does.
  // Module-level map keyed by conversation: deliberately NOT localStorage
  // (drafts are session-scoped, and persisting every keystroke to disk buys
  // nothing) and NOT a re-render source (read once on mount).
  const draftKey = conversationId ?? 'main';
  const temporary = activeThread?.temporary === true;
  const [inputValue, _setInputValue] = useState(() => temporary ? '' : composerDrafts.get(draftKey) ?? '');
  const setInputValue = useCallback((v: string) => {
    if (!temporary) composerDrafts.set(draftKey, v);
    _setInputValue(v);
  }, [draftKey, temporary]);
  useEffect(() => {
    if (temporary) discardComposerDraft(draftKey);
    return () => { if (temporary) discardComposerDraft(draftKey); };
  }, [draftKey, temporary]);
  const attach = useComposerAttach(() => {}, false, {
    allowUrlExtraction: !temporary,
    draft: temporary ? undefined : getAttachmentDraft(draftKey),
  });
  const attachments = attach.attachments;

  const [replayRunId, setReplayRunId] = useState<number | null>(null);

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
    if (!inputValue.trim() || attach.busy) return;
    if (attachmentImageBudgetExceeded(attachments)) {
      attach.setError(t("inputs.imageBudget"));
      return;
    }

    const text = inputValue.trim();
    setInputValue('');

    const { display, sources } = attachmentDelivery(attachments, t);
    const context = sources.map((a) => a.text).join("\n\n---\n\n");
    const names = sources.map((a) => a.name);
    // Every attachment (incl. OCR-none images) echoes into the sent bubble as a
    // thumbnail/chip. previewUrl is a session-only object-URL — kept alive by clearing
    // with { revokeUrls: false } below so the rendered message can still show it.
    // Images ride as real image blocks (vision round), separate from `context`
    // which is extracted TEXT. An image chip that failed preparation has no
    // payload; its limitation is instead carried in the text context.
    const images = attachmentImages(attachments);
    const clearAttachments = () => attach.clear({ revokeUrls: false });

    if (onSendMessage) {
      // Live WS path: delegate to parent's onSendMessage (store + WS send)
      // `images` is OMITTED when empty, not passed as []: a text-only send must
      // stay byte-identical to what it was before vision existed — the same
      // principle build_user_blocks applies on the server.
      onSendMessage(text, context || display.length || images.length
        ? {
            context, names, display,
            ...(images.length ? { images: images as NonNullable<typeof images[number]>[] } : {}),
          }
        : undefined);
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
      timestamp: formatUiTime(Date.now(), i18n?.resolvedLanguage),
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



      <div className="flex-1 flex overflow-hidden relative">
        <div className="flex-1 flex flex-col h-full overflow-hidden transition-all duration-300 relative w-full">
          {/* Scrollable Chat Area */}
          <div ref={scrollContainerRef} onScroll={handleScrollContainerScroll} className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {chatHistory.length === 0 ? (
          <div className="min-h-full flex flex-col items-center justify-center text-center max-w-2xl mx-auto py-10 px-4 space-y-8 select-none">
            {/* Shared product typography; wraps safely with long display names. */}
            <div className="space-y-3 animate-fade-in">
              <div className="flex items-center justify-center gap-3">
                {/* Arslan mark */}
                <BrandMark alt="Arslan" className="w-11 h-11 object-contain select-none" draggable={false} />

                { /* Greeting */ }
                <h1 className="min-w-0 break-words text-2xl sm:text-3xl font-sans text-foreground tracking-tight font-medium leading-tight">
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

              {voiceError && (
                <p data-testid="voice-error" className="px-2 pb-1 text-[11px] text-danger font-sans">
                  {voiceError}
                </p>
              )}
              {/* Action options row */}
              <div className="flex items-center justify-between pt-2 border-t border-border/50 select-none">
                {/* Left group: attach control + model indicator */}
                <div className="flex items-center gap-2 min-w-0">
                  <AttachControl busy={attach.busy} onPickFiles={attach.addFiles} />
                  {micControl}
                  {/* Which model is about to answer — and a way to change it.
                      This read `settings.llm_provider · settings.llm_model` until
                      now: two fields adapters.ts stopped mapping when the
                      multi-config list became the source of truth, so the chip
                      rendered a bare "·" forever. */}
                  <ModelSwitcher
                    configs={providerConfigs ?? []}
                    llmProviders={llmProviders ?? []}
                    testingIds={providerTestingIds}
                    onSelect={(id) => onSelectModel?.(id)}
                    onManage={onOpenSettings}
                  />
                </div>

                <button
                  type="button"
                  aria-label={t('chat.send')}
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

            // 0.1.42: a background job's live card sits where the job was started.
            if (msg.jobId) return <JobCard key={msg.id} jobId={msg.jobId} />;

            // Roster notice (0.1.42): experts are not a standing cast in the chat.
            // One quiet line says who was asked to help; leaving says nothing.
            if (msg.rosterAction) {
              if (msg.rosterAction === 'left') return null;
              return (
                <p key={msg.id} className="py-0.5 text-center text-[10px] text-subtle-foreground select-none">
                  {t('chat.expert_involved', { name: msg.rosterSpawnName ?? '' })}
                </p>
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
                  <BrandMark alt="Arslan" className="w-7 h-7 object-contain select-none shrink-0 mt-0.5" draggable={false} />
                  <ClarifyOptionsCard
                    question={co.question}
                    options={co.options}
                    answered={co.answered}
                    onPick={(label) => {
                      useArslanStore.getState().markClarifyAnswered(Number(msg.id));
                      // fromClarify: answering Arslan's own question is not
                      // "moving on", so it must not implicitly decline the
                      // spawn invite sitting beside it.
                      onSendMessage?.(label, undefined, { fromClarify: true });
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
                          {t(msg.sender === 'user' ? 'common.you' : msg.sender === 'arslan' ? 'app.name' : 'ui.expert')}
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
                      <BrandMark alt="Arslan" className="w-5 h-5 object-contain select-none" draggable={false} />
                      <span className="font-bold text-foreground">{msg.senderName}</span>
                      <span className="text-[9px] bg-surface-raised text-primary px-2 py-0.5 rounded font-mono uppercase">
                        {t('nav.arslan')}
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
                      <BrandMark alt="Arslan" className="w-9 h-9 object-contain select-none" draggable={false} />
                      <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-background bg-success" />
                    </div>
                  </div>
                  <div className="space-y-3 max-w-2xl">
                    <div className="flex items-center gap-1.5 select-none">
                      <span className="text-[11px] font-semibold text-muted-foreground">{msg.senderName}</span>
                      <span className="text-[9px] bg-primary/10 text-primary px-2 py-0.5 rounded font-semibold font-mono uppercase tracking-wider">
                        {t('app.name')} {t('nav.arslan')}
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
                          <BrandMark alt="Arslan" className="w-9 h-9 object-contain select-none" draggable={false} />
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
                            {t('app.name')} {t('nav.arslan')}
                          </span>
                        ) : (
                          <div className="flex items-center gap-1">
                            <span className="text-[9px] bg-primary/10 text-primary px-2 py-0.5 rounded font-mono uppercase tracking-wider font-semibold">
                              {t('ui.expert')}
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
{msg.resultOfJob && <JobResultLabel outcome={msg.jobOutcome} />}
                      {msg.usage && <UsageChip usage={msg.usage} />}
                      {isArslan && msg.id !== '__streaming__' && <HostRunResultButton runId={msg.runId} onOpen={setReplayRunId} />}

                      {/* Routed Indicator - specifically asked in prompt */}
                      {msg.routedTo && (
                        <div className="mt-3.5 pt-3 border-t border-border/50 flex items-center gap-2.5 text-[11px] font-mono bg-surface/50 p-2 rounded-lg border border-border-strong">
                          <div className="w-2 h-2 rounded-full bg-primary animate-ping" />
                          <div className="flex items-center gap-1 text-muted-foreground">
                            <span>{t('ui.routedTo')}</span>
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
                              <span className="text-[9px] bg-primary/15 text-primary font-mono px-2 py-0.5 rounded font-bold uppercase tracking-widest">{t('ui.introduced')}</span>
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
                      <HtmlDocCard html={msg.artifactHtml.content} title={msg.artifactHtml.title || undefined}
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
                              {t('ui.from')} {msg.escalation.spawnName}
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

                    {/* 0.1.48: an old expert message keeps copy + its run; the expert actions went with the experts. */}
                    {isSpawn && !msg.isProposal && msg.spawnId && (
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <CopyButton text={msg.text} className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-primary text-[11px] rounded-md hover:bg-primary/10 transition-all select-none" />
                        <HostRunResultButton runId={msg.runId} onOpen={setReplayRunId} />
                      </div>
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
                        {t(msg.sender === 'user' ? 'common.you' : msg.sender === 'arslan' ? 'app.name' : 'ui.expert')}
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
{msg.resultOfJob && <JobResultLabel outcome={msg.jobOutcome} />}
                  {msg.usage && <UsageChip usage={msg.usage} />}
                  {isArslan && msg.id !== '__streaming__' && <HostRunResultButton runId={msg.runId} onOpen={setReplayRunId} />}

                  {/* Routed branch block */}
                  {msg.routedTo && (
                    <div className="mt-3 p-2 bg-primary/5 border-2 border-primary text-[11px] text-primary uppercase font-bold flex items-center gap-1.5 shadow-[2px_2px_0px_black]">
                      <span>{t('ui.delegate', { name: msg.routedTo.spawnName })}</span>
                    </div>
                  )}

                  {/* Spawn Intro Brutalist version */}
                  {msg.spawnIntro && (
                    <div className="mt-4 border-2 border-primary bg-background p-3 space-y-2 text-[11px]">
                      <div className="flex items-center gap-2 font-bold text-primary">
                        <span>{t('ui.expertCreated', { name: msg.spawnIntro.name })}</span>
                      </div>
                      <p className="text-muted-foreground text-[10px]">{t('ui.domain', { domain: msg.spawnIntro.domain })}</p>

                      <div className="pt-2 border-t border-border space-y-1">
                        <span className="text-subtle-foreground font-bold">{t('orchestrator.equipped_capabilities')}</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {msg.spawnIntro.tools.map(toolId => (
                            <span key={toolId} className="px-2 py-0.5 bg-background text-muted-foreground">
                              [{t('capabilities.tabs.tools')}] {toolId.toUpperCase()}
                            </span>
                          ))}
                          {msg.spawnIntro.skills.map(skillId => (
                            <span key={skillId} className="px-2 py-0.5 bg-background text-primary">
                              [{t('capabilities.hero.kind.skill')}] {skillId.toUpperCase()}
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
                      <HtmlDocCard html={msg.artifactHtml.content} title={msg.artifactHtml.title || undefined}
                                   filename={msg.artifactHtml.filename} bytes={msg.artifactHtml.bytes}
                                   truncated={!msg.artifactHtml.complete} hasMessageActions />
                    </div>
                  )}

                  {/* Brutalist Escalation Panel */}
                  {msg.escalation && (
                    <div className="mt-4 border-2 border-danger bg-background p-3 text-[11px]">
                      <div className="text-danger font-bold uppercase select-none pb-2 flex justify-between">
                        <span>{t('ui.escalation')}</span>
                        <span>{t(({ need_raised: 'orchestrator.escalation_raised', arslan_resolving: 'orchestrator.arslan_resolving', resolved: 'orchestrator.escalation_resolved', refused: 'orchestrator.escalation_refused' } as Record<string, string>)[msg.escalation.status] ?? 'ui.escalation')}</span>
                      </div>
                      <p className="text-muted-foreground font-semibold">{msg.escalation.issue.toUpperCase()}</p>
                      {msg.escalation.resolutionMessage && (
                        <div className="mt-2 bg-danger/20 text-danger p-2 border border-danger">
                          {t('ui.resolution')} {msg.escalation.resolutionMessage.toUpperCase()}
                        </div>
                      )}
                    </div>
                  )}

                  {/* 0.1.48: an old expert message keeps copy + its run; the expert actions went with the experts. */}
                  {isSpawn && !msg.isProposal && msg.spawnId && (
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <CopyButton text={msg.text} className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-primary text-[11px] rounded-md hover:bg-primary/10 transition-all select-none" />
                      <HostRunResultButton runId={msg.runId} onOpen={setReplayRunId} />
                    </div>
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
                      ? <BrandMark alt="Arslan" className="w-5 h-5 object-contain select-none" draggable={false} />
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
                        {t('nav.arslan')}
                      </span>
                    )}
                    {!isArslan && !isUser && (
                      <span className="text-[9px] bg-background text-primary px-2 py-0.5 rounded font-mono uppercase">
                        {t('ui.expert')}
                      </span>
                    )}
                  </div>

                  {/* Body Content */}
                  <MessageBody text={msg.text} indent streaming={msg.id === '__streaming__'} hasMessageActions={isSpawn && !msg.isProposal && !!msg.spawnId} className="text-foreground font-sans leading-relaxed text-[12.5px] pl-5 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0" />
                  {msg.cancelled && <div className="pl-5"><RunCancelledMarker /></div>}
                  {msg.resultOfJob && <div className="pl-5"><JobResultLabel outcome={msg.jobOutcome} /></div>}
                  {msg.usage && <div className="pl-5"><UsageChip usage={msg.usage} /></div>}
                  {isArslan && msg.id !== '__streaming__' && <HostRunResultButton runId={msg.runId} onOpen={setReplayRunId} />}

                  {/* Linear clean route badge */}
                  {msg.routedTo && (
                    <div className="text-[10px] text-subtle-foreground font-mono flex items-center gap-1.5 pl-5">
                      <span className="text-subtle-foreground">→ {t('ui.routedTo')}</span>
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
                            <span className="font-bold text-foreground text-[11px]">{t('ui.expertEntry', { name: msg.spawnIntro.name })}</span>
                          </div>
                          <span className="text-[9px] bg-surface text-muted-foreground px-2 py-0.5 rounded font-mono">{t('ui.active')}</span>
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
                      <HtmlDocCard html={msg.artifactHtml.content} title={msg.artifactHtml.title || undefined}
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
                          <span>{t('ui.accessBlocked', { status: t(({ need_raised: 'orchestrator.escalation_raised', arslan_resolving: 'orchestrator.arslan_resolving', resolved: 'orchestrator.escalation_resolved', refused: 'orchestrator.escalation_refused' } as Record<string, string>)[msg.escalation.status] ?? 'ui.escalation') })}</span>
                        </div>
                        <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">{msg.escalation.issue}</p>
                        {msg.escalation.resolutionMessage && (
                          <p className="mt-2 text-danger text-[10px] font-mono whitespace-pre-wrap pl-2 bg-background/40 py-1.5 rounded">{msg.escalation.resolutionMessage}</p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* 0.1.48: an old expert message keeps copy + its run; the expert actions went with the experts. */}
                  {isSpawn && !msg.isProposal && msg.spawnId && (
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <CopyButton text={msg.text} className="flex items-center gap-1 px-2 py-1 text-subtle-foreground hover:text-primary text-[11px] rounded-md hover:bg-primary/10 transition-all select-none" />
                      <HostRunResultButton runId={msg.runId} onOpen={setReplayRunId} />
                    </div>
                  )}
                </div>
              );
            }

            return null;
          })
        )}
        {/* LLM error banner: shown when the backend emits an error frame (e.g. LLM timeout, auth failure) */}
        {llmError && (() => {
          // 0.1.44: a task-status code (a check to make, a budget used up…) is not a
          // model failure; it gets its own neutral title instead of "Model error".
          const taskKey = taskErrorKey(llmError);
          // Literal class strings: Tailwind cannot see names spliced at runtime.
          const c = taskKey
            ? { box: 'bg-warning/10 border-warning/30', icon: 'text-warning', title: 'text-warning', body: 'text-warning/80', close: 'hover:bg-warning/20 text-warning/60 hover:text-warning' }
            : { box: 'bg-danger/10 border-danger/30', icon: 'text-danger', title: 'text-danger', body: 'text-danger/80 font-mono', close: 'hover:bg-danger/20 text-danger/60 hover:text-danger' };
          return (
          <div className="flex gap-3 items-start py-2 select-none" data-testid="chat-error" data-kind={taskKey ? 'task' : 'model'}>
            <BrandMark alt="Arslan" className="w-7 h-7 object-contain select-none shrink-0 mt-0.5" draggable={false} />
            <div className={`flex items-start gap-2 px-3 py-2.5 border ${c.box} rounded-2xl rounded-tl-none max-w-2xl`}>
              <AlertTriangle className={`w-3.5 h-3.5 ${c.icon} shrink-0 mt-0.5`} />
              <div className="flex flex-col gap-1 min-w-0">
                <span className={`text-[11px] ${c.title} font-semibold`}>{t(taskKey ? 'ui.needsYourCheck' : 'ui.modelError')}</span>
                <span className={`text-[11px] ${c.body} break-words`}>{taskKey ? t(taskKey) : runtimeErrorText(llmError, llmErrorTranslations, i18n?.resolvedLanguage)}</span>
              </div>
              <button
                onClick={clearLlmError}
                className={`ml-auto shrink-0 p-0.5 rounded ${c.close} transition-colors`}
                aria-label={t('errors.dismiss')}
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          </div>
          );
        })()}
        {/* Thinking indicator: shown from send until first real content chunk.
            We no longer gate on !streaming because stream_start begins streaming
            with empty text (slow models like Gemini 2.5 Pro have a long delay
            before the first token). thinking stays true until stream_chunk clears
            it, so the dots show through the blank gap. */}
        {(thinking || liveStreaming) && (
          <div className="flex gap-3 items-start py-2 select-none">
            <BrandMark alt="Arslan" className="w-7 h-7 object-contain select-none shrink-0" draggable={false} />
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

      </div>

      {/* Input Message Form Panel */}
      {chatHistory.length > 0 && (
        <footer className="p-4 border-t border-border bg-background/80 backdrop-blur shrink-0 z-10 select-none">
          <form onSubmit={handleSendMessage} className="max-w-4xl mx-auto">
            <div
              className={`composer-box${attach.dragActive ? ' composer-box--drop' : ''}`}
              {...attach.dndHandlers}
            >
              <AttachChips attachments={attachments} onRemove={attach.removeAt} />
              <input
                id="chat-message-input"
                type="text"
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                spellCheck={false}
                value={inputValue}
                onChange={(e) => { setInputValue(e.target.value); attach.onInputChange(e.target.value); }}
                onPaste={attach.onPaste}
                placeholder={t('orchestrator.placeholder_chat')}
                className="w-full bg-transparent text-xs text-foreground placeholder-subtle-foreground focus:outline-none font-sans px-1 py-1.5"
              />
              <div className="composer-row">
                <div data-testid="composer-input-tools" className="flex items-center gap-2">
                  <AttachControl busy={attach.busy} onPickFiles={attach.addFiles} />
                  {micControl}
                </div>
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
          {/* 0.1.42: the command-confirmation control lives in Settings → Advanced.
              Only the non-default posture (read-only commands run without asking)
              stays visible here, as one line — it changes what happens without a card. */}
          {shellEnabled && shellPolicy === 'ask_risky' && (
            <p className="max-w-4xl mx-auto mt-1.5 text-[11px] text-muted-foreground" data-testid="execution-options">
              {t('workspace.readOnlyAutomatic')}
            </p>
          )}
        </footer>
      )}
    </div>

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
