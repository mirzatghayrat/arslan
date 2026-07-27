import { create } from "zustand";
import type { ArslanServerMessage, ArslanThreadItem, SuggestDraft, ToolStep, OverlapInfo, RosterMember, StaffingCandidate, SpawnUpdateChanges, SpawnUpdateCurrent } from "../api/client.types";
import type { MessageAttachment } from "../types";

interface ArslanState {
  items: ArslanThreadItem[];
  streaming: boolean;
  streamingText: string;
  streamSource: "arslan" | "spawn" | null;
  streamSpawnId: number | null;
  streamSpawnName: string | null;
  pendingRoute: { spawnId: number; spawnName: string | null } | null;
  suggestion: SuggestDraft | null;
  spawnNames: Record<number, string>;
  error: string | null;
  lastMessageId: number;
  pending: boolean;
  suggestionTaskBrief: string | null;
  suggestionOverlaps: OverlapInfo | null;
  // spawn_meta frames can arrive BEFORE the stream_end that creates the item
  // (production order). Stash them here keyed by arslan_message_id and apply on
  // stream_end. Cleared per-key once applied.
  pendingSpawnMeta: Record<number, { assistant_message_id: number; task_brief: string; run_id?: number }>;
  // Live tool-loop steps for the in-flight spawn turn, paired from
  // tool_call/tool_result frames; folded into the reply item on stream_end.
  activitySteps: ToolStep[];
  // Pending proposal: when a `proposal` frame arrives, the next spawn deliverable
  // created at stream_end for that spawn_id should be flagged isProposal: true.
  pendingProposalSpawnId: number | null;
  // Active conversation roster: spawns currently joined to this conversation thread.
  roster: RosterMember[];
  // Pending invite: set when a `propose_invite` frame arrives; cleared once the
  // user confirms (sends roster_invite) or cancels.
  pendingInvite: { spawnId: number; reason: string } | null;
  // Pending shell command: set when a `propose_run_command` frame arrives; cleared
  // once the user confirms (sends confirm_run_command) or cancels.
  pendingCommand: { callId: string; pretty: string; reason: string } | null;
  // NEXT BUILD (conversation-driven MCP, Task 5): set when a `propose_connect_mcp`
  // frame arrives. env_keys carries credential NAMES + metadata only — the card
  // collects VALUES locally and sends them only over REST (addMcpServer). Cleared
  // once the connect card's follow-up (`mcp_connect_followup`) lands, or on cancel.
  pendingConnectMcp: {
    callId: string;
    key: string;
    label: string;
    transport: string;
    command: string;
    argv: string[];
    url: string | null;
    envKeys: { name: string; description: string; get_it_url: string; paid: boolean }[];
    prerequisites: string;
    requiresPath: boolean;
    pathPlaceholder: string | null;
  } | null;
  // Pending staffing decision: set when a `propose_staffing` frame arrives.
  // Candidates are mapped snake→camel. Cleared once the user picks or dismisses.
  pendingStaffing: { candidates: { spawnId: number; name: string | null; score: number; why: string }[]; createDraft: SuggestDraft | null } | null;
  // Pending conversational spawn edit: set by a `suggest_update` frame; cleared on
  // confirm (sends confirm_update) or dismiss. Applied ONLY by the backend on confirm.
  pendingUpdate: { spawnId: number; spawnName: string; current: SpawnUpdateCurrent; changes: SpawnUpdateChanges; reason?: string } | null;
  // True from the moment the user sends a message until the first response frame arrives.
  thinking: boolean;
  // Timestamp of the current turn's start (send/confirm) — drives the LiveActivity timer.
  workStartedAt: number | null;
  // ── HX-4 / A1 · stall watchdog ─────────────────────────────────────────────
  // Working indicators are driven ONLY by runtime WS frames — never by message
  // text. lastFrameAt is refreshed on EVERY incoming frame (and on turn start);
  // checkStall() flips `stalled` when a turn is active but no frame has arrived
  // for > STALL_MS, so the UI shows a static 「已中断」 instead of an infinite
  // spinner. Any new frame un-stalls; stream_end/error end the turn entirely.
  lastFrameAt: number | null;
  stalled: boolean;
  // S3-M1 · cancellable runs: the recorded run id of the in-flight stream (from
  // stream_start's run_id — spawn runs only). The stop button POSTs
  // /runs/{activeRunId}/cancel. Cleared on stream_end/error/run_cancelled.
  activeRunId: number | null;

  setSpawnNames: (map: Record<number, string>) => void;
  setThinking: (v: boolean) => void;
  addUserMessage: (content: string, attachments?: MessageAttachment[]) => void;
  handleFrame: (frame: ArslanServerMessage) => void;
  dismissSuggestion: () => void;
  dismissUpdate: () => void;
  // Implicit-dismiss: clear ALL user-facing proposal cards in one call. Fired when
  // the user sends a new message without acting on a pending card. Does NOT touch
  // pendingRoute / pendingProposalSpawnId (execution-phase markers cleared on stream_end).
  dismissAllPending: () => void;
  markProposalConfirmed: (spawnId: number) => void;
  // PA-3: flip a clarify card to its answered (disabled) state once the user picked
  // an option — a stale re-click can never send a second user_message.
  markClarifyAnswered: (itemId: number) => void;
  clearPendingInvite: () => void;
  clearPendingCommand: () => void;
  clearPendingConnectMcp: () => void;
  clearPendingStaffing: () => void;
  clearError: () => void;
  resetForNewConversation: () => void;
  // Watchdog tick: marks the current turn `stalled` if it is active and no frame
  // has arrived for > STALL_MS. No-op on an idle store. Called on an interval by
  // the chat view while a turn is running.
  checkStall: () => void;
}

// A turn is "stalled" (server went quiet mid-turn) after this many ms without
// any incoming frame. Indicators then show 「已中断」 instead of animating.
export const STALL_MS = 90_000;

// Negative, decrementing ids for client-only items (user echoes, fact chips)
// so they never collide with server message ids.
let clientSeq = -1;
const nextClientId = () => clientSeq--;

// Honest, tier-aware copy for the `mcp_connect_followup` chat note. Counts are the
// server's recomputed-from-DB truth (Task 3) — never the client's own tally.
// assignable=false (no tool wired "safe") gets a needs-review note pointed at
// Settings, never phrasing that implies the connector is ready to equip.
function _mcpConnectFollowupText(frame: {
  tool_count: number;
  safe_count: number;
  restricted_count: number;
  assignable: boolean;
}): string {
  if (!frame.assignable) {
    const n = frame.tool_count;
    return `Connected — all ${n} tool${n === 1 ? "" : "s"} need review in Settings → MCP before any spawn can use ${n === 1 ? "it" : "them"}.`;
  }
  return frame.restricted_count > 0
    ? `Connected — ${frame.safe_count} ready, ${frame.restricted_count} restricted; equip which spawn?`
    : `Connected — ${frame.safe_count} ready; equip which spawn?`;
}

// Data-only initial state. Actions are attached separately and merged in so a
// `setState(initialArslanState(), true)` full-replace (used by tests) keeps the
// action methods intact.
function initialData() {
  return {
    items: [] as ArslanThreadItem[],
    streaming: false,
    streamingText: "",
    streamSource: null as "arslan" | "spawn" | null,
    streamSpawnId: null as number | null,
    streamSpawnName: null as string | null,
    pendingRoute: null as { spawnId: number; spawnName: string | null } | null,
    suggestion: null as SuggestDraft | null,
    spawnNames: {} as Record<number, string>,
    error: null as string | null,
    lastMessageId: 0,
    pending: false,
    suggestionTaskBrief: null as string | null,
    suggestionOverlaps: null as OverlapInfo | null,
    pendingSpawnMeta: {} as Record<number, { assistant_message_id: number; task_brief: string; run_id?: number }>,
    activitySteps: [] as ToolStep[],
    pendingProposalSpawnId: null as number | null,
    roster: [] as RosterMember[],
    pendingInvite: null as { spawnId: number; reason: string } | null,
    pendingCommand: null as { callId: string; pretty: string; reason: string } | null,
    pendingConnectMcp: null as {
      callId: string;
      key: string;
      label: string;
      transport: string;
      command: string;
      argv: string[];
      url: string | null;
      envKeys: { name: string; description: string; get_it_url: string; paid: boolean }[];
      prerequisites: string;
      requiresPath: boolean;
      pathPlaceholder: string | null;
    } | null,
    pendingStaffing: null as { candidates: { spawnId: number; name: string | null; score: number; why: string }[]; createDraft: SuggestDraft | null } | null,
    pendingUpdate: null as { spawnId: number; spawnName: string; current: SpawnUpdateCurrent; changes: SpawnUpdateChanges; reason?: string } | null,
    thinking: false,
    workStartedAt: null as number | null,
    lastFrameAt: null as number | null,
    stalled: false,
    activeRunId: null as number | null,
  };
}

type SetState = (partial: Partial<ArslanState>) => void;
type GetState = () => ArslanState;

function makeActions(set: SetState, get: GetState) {
  return {
    // Turn start also arms the stall watchdog (lastFrameAt baseline) so a
    // dispatch that never produces a single frame still times out into 「已中断」.
    setThinking: (v: boolean) =>
      set(v ? { thinking: true, workStartedAt: Date.now(), lastFrameAt: Date.now(), stalled: false } : { thinking: false }),

    setSpawnNames: (map: Record<number, string>) =>
      set({ spawnNames: { ...get().spawnNames, ...map } }),

    // attachments = session-only display echo (image thumbnails via object-URL, doc chips);
    // never persisted — history-restored items simply won't carry them.
    addUserMessage: (content: string, attachments?: MessageAttachment[]) =>
      set({
        items: [...get().items, { id: nextClientId(), kind: "message", role: "user", content, ...(attachments?.length ? { attachments } : {}) }],
        pending: true,
        workStartedAt: Date.now(),
        lastFrameAt: Date.now(),
        stalled: false,
      }),

    dismissSuggestion: () => set({ suggestion: null, suggestionTaskBrief: null, suggestionOverlaps: null }),
    dismissUpdate: () => set({ pendingUpdate: null }),
    dismissAllPending: () => set({
      suggestion: null, suggestionTaskBrief: null, suggestionOverlaps: null,
      pendingInvite: null, pendingStaffing: null, pendingUpdate: null,
    }),
    // One-shot confirm (doom-loop guard, frontend half): flipping isProposal off disables the
    // confirm button immediately so a stale re-click can never re-fire execute_confirmed.
    markProposalConfirmed: (spawnId: number) =>
      set({
        items: get().items.map((it) =>
          it.isProposal && Number(it.spawnId) === spawnId ? { ...it, isProposal: false } : it),
      }),
    markClarifyAnswered: (itemId: number) =>
      set({
        items: get().items.map((it) =>
          it.id === itemId && it.clarifyOptions && !it.clarifyOptions.answered
            ? { ...it, clarifyOptions: { ...it.clarifyOptions, answered: true } }
            : it),
      }),
    clearPendingInvite: () => set({ pendingInvite: null }),
    clearPendingCommand: () => set({ pendingCommand: null }),
    clearPendingConnectMcp: () => set({ pendingConnectMcp: null }),
    clearPendingStaffing: () => set({ pendingStaffing: null }),
    clearError: () => set({ error: null }),

    // Clear all conversation state so the incoming `history` frame for the new
    // conversation_id repopulates from scratch with no stale carry-over.
    resetForNewConversation: () => set({ ...initialData() }),

    checkStall: () => {
      const s = get();
      // "Active" = any runtime-frame-driven working flag. Message text NEVER
      // counts (A1 invariant) — an idle store can never stall.
      const active = s.thinking || s.streaming || s.pending || s.pendingRoute != null;
      if (!active) {
        if (s.stalled) set({ stalled: false });
        return;
      }
      if (!s.stalled && s.lastFrameAt != null && Date.now() - s.lastFrameAt > STALL_MS) {
        set({ stalled: true });
      }
    },

    handleFrame: (frame: ArslanServerMessage) => {
      const state = get();
      // Every incoming frame proves the server is alive: refresh the watchdog
      // baseline and un-stall. stream_end/error additionally clear the activity
      // flags below, ending the turn entirely.
      set({ lastFrameAt: Date.now(), stalled: false });
      // Clear thinking on the first frame that signals Arslan is responding with
      // real content or a card. Intermediate dispatch frames ("routing",
      // "roster_event", "spawn_meta") are NOT included here — they fire during
      // the Arslan→spawn handoff before the spawn has streamed anything, so
      // clearing thinking on them creates a dead-air gap. Instead, thinking
      // persists through routing/dispatch and clears in stream_chunk (first real
      // token) or on card frames below.
      // NOTE: "stream_start" is intentionally excluded — it starts streaming but
      // delivers no content yet. Slow models (e.g. Gemini 2.5 Pro) have a long
      // delay between stream_start and the first token, so we keep the thinking
      // indicator alive until stream_chunk (first real content) clears it.
      const RESPONDING_TYPES = new Set(["suggest_create", "message", "error", "fact_saved", "propose_invite", "propose_run_command", "propose_connect_mcp", "propose_staffing", "suggest_update", "spawn_updated", "clarify_options"]);
      if (RESPONDING_TYPES.has(frame.type)) {
        set({ thinking: false });
      }
      // Maps a server row (history row or `message` frame — same field names,
      // `spawn_id` optional) to a renderable thread item, resolving spawn names.
      const rowToItem = (row: {
        message_id: number;
        role: string;
        content: string;
        spawn_id?: number | null;
        run_id?: number | null;
      }): ArslanThreadItem => {
        if (row.role === "spawn_summary") {
          // Resolve the spawn name ONLY from an explicit spawn_id. History rows
          // always carry one; the resume `message` frame does not (server
          // contract), in which case spawnId/spawnName degrade to null and the
          // bubble falls back to the conversation title. Never guess from the
          // roster.
          const spawnId = row.spawn_id ?? null;
          return {
            id: row.message_id,
            kind: "message",
            role: "spawn",
            content: row.content,
            spawnId,
            spawnName: spawnId != null ? state.spawnNames[spawnId] ?? null : null,
            // S3-M2: run linkage from the history row — the RunReplay entry
            // point survives a reload. null/absent degrades to undefined.
            runId: row.run_id ?? undefined,
          };
        }
        return {
          id: row.message_id,
          kind: "message",
          role: row.role === "arslan" ? "arslan" : "user",
          content: row.content,
          runId: row.run_id ?? undefined,
        };
      };
      switch (frame.type) {
        case "history": {
          const items: ArslanThreadItem[] = frame.messages.map(rowToItem);
          const lastId = items.reduce((max, it) => (it.id > max ? it.id : max), 0);
          set({ items, lastMessageId: lastId, activitySteps: [], activeRunId: null });
          break;
        }
        case "message": {
          set({
            items: [...state.items, rowToItem(frame)],
            lastMessageId: Math.max(state.lastMessageId, frame.message_id),
          });
          break;
        }
        case "proposal":
          // Mark the spawn's next deliverable as a proposal. Cleared in stream_end.
          set({ pendingProposalSpawnId: frame.spawn_id });
          break;
        case "routing":
          set({
            pendingRoute: { spawnId: frame.spawn_id, spawnName: frame.spawn_name },
            spawnNames: frame.spawn_name
              ? { ...state.spawnNames, [frame.spawn_id]: frame.spawn_name }
              : state.spawnNames,
            // Routing brief (need restatement + @-mention duty lines): render as its
            // own thread line. Only the first round of a turn carries an announcement.
            ...(frame.announcement
              ? {
                  items: [
                    ...state.items,
                    {
                      id: nextClientId(),
                      kind: "system" as const,
                      role: "arslan" as const,
                      content: frame.announcement,
                      isRouteAnnouncement: true,
                      spawnId: frame.spawn_id,
                      spawnName: frame.spawn_name,
                    },
                  ],
                }
              : {}),
          });
          break;
        case "auto_continue":
          // Bridge frame between an exhausted (digest) round and its automatic
          // follow-up dispatch: keep the thinking indicator alive so the activity
          // pulse continues seamlessly into the next round's frames.
          set({ thinking: true, workStartedAt: state.workStartedAt ?? Date.now() });
          break;
        case "run_in_progress":
          // S3-M2 reattach: the server announces an in-flight run right after the
          // history push, before replaying its journaled frames. Arm the stop
          // button (activeRunId) and revive the thinking pulse; create NO item —
          // the replayed stream_start/chunk frames rebuild the live view through
          // the existing cases below.
          set({
            thinking: true,
            workStartedAt: state.workStartedAt ?? Date.now(),
            activeRunId: frame.run_id,
          });
          break;
        case "stream_start":
          set({
            pending: false,
            streaming: true,
            streamingText: "",
            streamSource: frame.source,
            streamSpawnId:
              frame.source === "spawn"
                ? state.pendingRoute?.spawnId ?? frame.spawn_id ?? null
                : null,
            streamSpawnName: frame.source === "spawn" ? state.pendingRoute?.spawnName ?? null : null,
            // S3-M1: recorded runs carry their run id — the cancel target.
            activeRunId: frame.run_id ?? null,
          });
          break;
        case "stream_chunk":
          if (!state.streaming) break;
          // First real content arrived — clear thinking so the indicator hands
          // off seamlessly to the streaming bubble (no blank gap).
          set({ thinking: false, streamingText: state.streamingText + frame.content });
          break;
        case "stream_end": {
          if (!state.streaming) break;
          // A refused escalation ends the stream without persisting a message:
          // the server sends message_id: null and no reply text. With nothing
          // to show, just reset the streaming state — appending an item would
          // create a ghost entry with a null id (duplicate React keys).
          const hasContent = state.streamingText.length > 0;
          const hasSteps = state.activitySteps.length > 0;
          if (frame.message_id == null && !hasContent && !hasSteps) {
            set({
              thinking: false,
              streaming: false,
              streamingText: "",
              streamSource: null,
              streamSpawnId: null,
              streamSpawnName: null,
              pendingRoute: null,
              activitySteps: [],
              pendingProposalSpawnId: null,
              activeRunId: null,
            });
            break;
          }
          // A spawn_meta for this message may have arrived earlier (production
          // order). Apply it now and drop the stashed entry.
          const meta = frame.message_id != null ? state.pendingSpawnMeta[frame.message_id] : undefined;
          // If a proposal was pending for this spawn, mark the item as a proposal.
          const isProposal =
            state.streamSource === "spawn" &&
            state.pendingProposalSpawnId != null &&
            state.pendingProposalSpawnId === state.streamSpawnId;
          const item: ArslanThreadItem = {
            id: frame.message_id ?? nextClientId(),
            kind: "message",
            role: state.streamSource === "spawn" ? "spawn" : "arslan",
            content: state.streamingText,
            spawnId: state.streamSpawnId,
            spawnName: state.streamSpawnName,
            spawnMessageId: meta?.assistant_message_id ?? null,
            runId: meta?.run_id ?? null,
            taskBrief: meta?.task_brief ?? null,
            toolSteps: state.activitySteps.length > 0 ? state.activitySteps : undefined,
            ...(isProposal ? { isProposal: true } : {}),
            // S3-M3: the turn's usage rides the terminal stream_end frame — land it
            // on the created item so the bubble can render its usage chip.
            // (run_cancelled finalization deliberately never sets this.)
            ...(frame.usage ? { usage: frame.usage } : {}),
            // 🔒 SECURITY: artifactHtml comes ONLY from the backend stream_end frame's
            // artifact (HX-2 HTML deliverable channel — sniffed/stored server-side),
            // NEVER from LLM message text. Same invariant as artifactSvg/Chart/Pptx.
            ...(frame.artifact?.kind === "html" && frame.artifact.content
              ? {
                  artifactHtml: {
                    // Empty title → the rendering HtmlDocCard falls back to its
                    // own i18n generic label (msg.html_doc). The store must not
                    // bake in a display string (stores stay i18n-free).
                    title: frame.artifact.title ?? "",
                    filename: frame.artifact.filename ?? "document.html",
                    content: frame.artifact.content,
                    complete: frame.artifact.complete ?? true,
                    bytes: frame.artifact.bytes ?? frame.artifact.content.length,
                  },
                }
              : {}),
          };
          const nextPendingSpawnMeta = { ...state.pendingSpawnMeta };
          if (frame.message_id != null) delete nextPendingSpawnMeta[frame.message_id];
          set({
            thinking: false,
            items: [...state.items, item],
            streaming: false,
            streamingText: "",
            streamSource: null,
            streamSpawnId: null,
            streamSpawnName: null,
            pendingRoute: null,
            pendingSpawnMeta: nextPendingSpawnMeta,
            lastMessageId:
              frame.message_id != null ? Math.max(state.lastMessageId, frame.message_id) : state.lastMessageId,
            activitySteps: [],
            activeRunId: null,
            // Clear the proposal flag once consumed
            pendingProposalSpawnId: isProposal ? null : state.pendingProposalSpawnId,
          });
          break;
        }
        case "run_cancelled": {
          // S3-M1: the server cancelled this run mid-flight. Finalize the live
          // bubble as an interrupted item — but only when partial text actually
          // streamed. The canonical copy (spawn_summary with the 已中断 marker)
          // was already persisted server-side; this is the live-session echo so
          // the partial text doesn't vanish from under the user.
          const hasPartial = state.streamingText.length > 0;
          const item: ArslanThreadItem | null = hasPartial
            ? {
                id: frame.message_id ?? nextClientId(),
                kind: "message",
                role: state.streamSource === "spawn" ? "spawn" : "arslan",
                content: state.streamingText,
                spawnId: state.streamSpawnId,
                spawnName: state.streamSpawnName,
                toolSteps: state.activitySteps.length > 0 ? state.activitySteps : undefined,
                cancelled: true,
              }
            : null;
          set({
            thinking: false,
            pending: false,
            streaming: false,
            streamingText: "",
            streamSource: null,
            streamSpawnId: null,
            streamSpawnName: null,
            pendingRoute: null,
            activitySteps: [],
            activeRunId: null,
            ...(item
              ? {
                  items: [...state.items, item],
                  lastMessageId:
                    frame.message_id != null
                      ? Math.max(state.lastMessageId, frame.message_id)
                      : state.lastMessageId,
                }
              : {}),
          });
          break;
        }
        case "tool_call":
          set({
            activitySteps: [
              ...state.activitySteps,
              { tool: frame.tool, argsSummary: frame.args_summary, status: "running" },
            ],
          });
          break;
        case "tool_result": {
          // The loop is sequential per tool: resolve the most recent unresolved
          // step with the same tool name.
          const steps = [...state.activitySteps];
          for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].tool === frame.tool && steps[i].status === "running") {
              steps[i] = {
                ...steps[i],
                status: frame.ok ? "ok" : "error",
                resultSummary: frame.summary,
                // 🔒 SECURITY: artifactSvg / artifactChart / artifactPptx come ONLY from the backend
                // render_chart/render_deck tool_result frame's artifact, NEVER from LLM message text.
                ...(frame.artifact?.kind === "svg" ? { artifactSvg: frame.artifact.content } : {}),
                ...(frame.artifact?.kind === "echarts" ? { artifactChart: frame.artifact.spec } : {}),
                ...(frame.artifact?.kind === "pptx" ? { artifactPptx: {
                  filename: frame.artifact.filename ?? "deck.pptx",
                  bytesB64: frame.artifact.bytes_b64 ?? "",
                  slides: frame.artifact.slides ?? 0,
                } } : {}),
              };
              break;
            }
          }
          set({ activitySteps: steps, thinking: true });
          break;
        }
        case "suggest_create":
          set({
            pending: false,
            suggestion: frame.draft,
            suggestionTaskBrief: frame.task_brief ?? null,
            suggestionOverlaps: frame.overlaps ?? null,
          });
          break;
        case "spawn_meta": {
          // Production order is spawn_meta BEFORE stream_end, so the target item
          // usually doesn't exist yet — stash it for stream_end to apply. If the
          // item already exists (defensive / reverse order), attach directly.
          const exists = state.items.some((it) => it.id === frame.arslan_message_id);
          if (exists) {
            set({
              items: state.items.map((it) =>
                it.id === frame.arslan_message_id
                  ? { ...it, spawnMessageId: frame.assistant_message_id, taskBrief: frame.task_brief, runId: frame.run_id ?? null }
                  : it,
              ),
            });
          } else {
            set({
              pendingSpawnMeta: {
                ...state.pendingSpawnMeta,
                [frame.arslan_message_id]: {
                  assistant_message_id: frame.assistant_message_id,
                  task_brief: frame.task_brief,
                  run_id: frame.run_id,
                },
              },
            });
          }
          break;
        }
        case "fact_saved":
          set({
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "fact",
                role: "arslan",
                content: frame.content,
                sensitive: frame.sensitive,
              },
            ],
          });
          break;
        case "suggest_update":
          set({
            pending: false,
            pendingUpdate: {
              spawnId: frame.spawn_id,
              spawnName: frame.spawn_name,
              current: frame.current,
              changes: frame.changes,
              reason: frame.reason,
            },
          });
          break;
        case "spawn_updated":
          set({
            pendingUpdate: null,
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "system",
                role: "arslan",
                content: `__SPAWN_UPDATED__:${frame.spawn_name}`,
                equipment: frame.equipment ?? null,
              },
            ],
          });
          break;
        case "spawn_created":
          set({
            suggestion: null,
            suggestionTaskBrief: null,
            suggestionOverlaps: null,
            spawnNames: { ...state.spawnNames, [frame.spawn_id]: frame.spawn_name },
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "system",
                role: "arslan",
                content: `__SPAWN_CREATED__:${frame.spawn_name}`,
                equipment: frame.equipment ?? null,
                intro: frame.intro ?? null,
              },
            ],
          });
          break;
        case "escalation":
          set({
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "escalation",
                role: "spawn",
                content: "",
                spawnId: frame.spawn_id,
                spawnName: frame.spawn_name,
                escalation: {
                  spawnId: frame.spawn_id,
                  spawnName: frame.spawn_name,
                  kind: frame.kind,
                  need: frame.need,
                  status: "resolving",
                },
              },
            ],
          });
          break;
        case "escalation_resolved":
        case "escalation_refused": {
          // Update the most recent still-resolving escalation for this spawn.
          const items = [...state.items];
          for (let i = items.length - 1; i >= 0; i--) {
            const esc = items[i].escalation;
            if (esc && esc.spawnId === frame.spawn_id && esc.status === "resolving") {
              items[i] = {
                ...items[i],
                escalation:
                  frame.type === "escalation_resolved"
                    ? { ...esc, status: "resolved", how: frame.how, detail: frame.detail }
                    : { ...esc, status: "refused", why: frame.why },
              };
              break;
            }
          }
          set({ items });
          break;
        }
        case "verdict_recorded": {
          // Mark the most recent spawn deliverable (role==='spawn', !isProposal) for
          // this spawn_id with the verdict action so the UI can show confirmed state.
          const items = [...state.items];
          for (let i = items.length - 1; i >= 0; i--) {
            const it = items[i];
            if (it.role === "spawn" && !it.isProposal && it.spawnId === frame.spawn_id) {
              items[i] = { ...it, verdict: frame.action };
              break;
            }
          }
          set({ items });
          break;
        }
        case "deliverable_finalized": {
          // A refined spawn deliverable, posted back from the side chat into the
          // main thread. Append as a spawn item; the verdict_recorded that follows
          // marks it accepted via the existing case.
          const item: ArslanThreadItem = {
            id: frame.message_id ?? nextClientId(),
            kind: "message",
            role: "spawn",
            content: frame.content,
            spawnId: frame.spawn_id,
            spawnName: frame.spawn_name ?? state.spawnNames[frame.spawn_id] ?? null,
            refinedFrom: frame.refined_from ?? null,
          };
          set({
            items: [...state.items, item],
            lastMessageId:
              frame.message_id != null ? Math.max(state.lastMessageId, frame.message_id) : state.lastMessageId,
          });
          break;
        }
        case "roster_update":
          set({
            roster: frame.members.map((m) => ({
              spawnId: m.spawn_id,
              spawnName: m.spawn_name,
              joinedVia: m.joined_via,
              status: m.status,
            })),
          });
          break;
        case "propose_invite":
          set({ pendingInvite: { spawnId: frame.spawn_id, reason: frame.reason } });
          break;
        case "clarify_options":
          // PA-3 structured clarification card: rendered as a thread ITEM (question +
          // one-click option buttons). A pick sends the label as a normal user_message
          // and markClarifyAnswered disables the card. 🔒 question/options come ONLY
          // from the backend clarify_options frame (validated/clamped 2-4 server-side),
          // NEVER from LLM message text — same invariant as propose_invite/suggest_create.
          set({
            pending: false,
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "message",
                role: "arslan",
                content: frame.question,
                clarifyOptions: { question: frame.question, options: frame.options, answered: false },
              },
            ],
          });
          break;
        case "propose_run_command":
          set({ pendingCommand: { callId: frame.call_id, pretty: frame.pretty,
                                  reason: frame.reason || "" } });
          break;
        case "propose_connect_mcp":
          // NEXT BUILD (conversation-driven MCP, Task 5): env_keys carries credential
          // NAMES + metadata only (never a value) — the ConnectMcpCard collects values
          // locally and sends them ONLY over REST (addMcpServer's body).
          set({
            pendingConnectMcp: {
              callId: frame.call_id,
              key: frame.key,
              label: frame.label,
              transport: frame.transport,
              command: frame.command,
              argv: frame.argv,
              url: frame.url,
              envKeys: frame.env_keys,
              prerequisites: frame.prerequisites,
              requiresPath: frame.requires_path,
              pathPlaceholder: frame.path_placeholder,
            },
          });
          break;
        case "mcp_connect_followup":
          // Honest, tier-aware result recomputed server-side from the DB (Task 3) —
          // clears the card and appends a plain chat note, same idiom as
          // attachment_stored below. assignable=false means connected but nothing is
          // safe+wired yet, so the note points at Settings instead of implying it's
          // ready to equip.
          set({
            pendingConnectMcp: null,
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "system",
                role: "arslan",
                content: _mcpConnectFollowupText(frame),
              },
            ],
          });
          break;
        case "propose_staffing":
          set({
            pendingStaffing: {
              candidates: frame.candidates.map((c: StaffingCandidate) => ({
                spawnId: c.spawn_id,
                name: c.name,
                score: c.score,
                why: c.why,
              })),
              createDraft: frame.create_draft,
            },
          });
          break;
        case "roster_event":
          set({
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "system",
                role: "arslan",
                content: "",
                spawnId: frame.spawn_id,
                spawnName: frame.spawn_name,
                rosterAction: frame.action,
              },
            ],
          });
          break;
        case "attachment_stored":
          set({
            items: [
              ...state.items,
              {
                id: nextClientId(),
                kind: "system",
                role: "arslan",
                // Sentinel kept — App translates it at render time
                // (chat.attachment_stored / chat.attachment_stored_generic).
                // Stores stay i18n-free: importing the i18n singleton breaks
                // every test that mocks react-i18next. Same precedent as
                // __SPAWN_UPDATED__.
                content: `__ATTACHMENT_STORED__:${JSON.stringify({ name: frame.spawn_name ?? null, chunks: frame.chunks })}`,
                spawnName: frame.spawn_name,
              },
            ],
          });
          break;
        case "error":
          set({
            error: frame.message,
            pending: false,
            streaming: false,
            streamingText: "",
            streamSource: null,
            streamSpawnId: null,
            streamSpawnName: null,
            pendingRoute: null,
            activitySteps: [],
            activeRunId: null,
          });
          break;
        default:
          break;
      }
    },
  };
}

export const useArslanStore = create<ArslanState>((set, get) => ({
  ...initialData(),
  ...makeActions(set, get),
}));

// Returns a full state object (data + actions) so it can be used with
// `setState(initialArslanState(), true)` without dropping the action methods.
export function initialArslanState(): ArslanState {
  return {
    ...initialData(),
    ...makeActions(
      (partial) => useArslanStore.setState(partial),
      () => useArslanStore.getState(),
    ),
  };
}
