import { create } from "zustand";
import { request } from "../api/client";
import { runtimeErrorTranslations, type RuntimeErrorTranslations } from "../lib/runtimeErrorText";
import { createSpeaker } from "../lib/speech";
import type { ActionKind, ApplyConnectMcpResult, ArslanServerMessage, ArslanThreadItem, JobCard, JobOutcome, ProcessSummary, StoredArtifact, ToolStep, RosterMember } from "../api/client.types";
import type { MessageAttachment } from "../types";

let _cardSeq = 0;
/** Where a card arrived: the clock (its expiry counts from it) and its place in line, exact even for two cards that arrive in
 *  the same millisecond, whatever their kinds (`seq` rises with every card, a card sent again included). */
const _arrived = () => ({ receivedAt: Date.now(), seq: ++_cardSeq });

/** A card waiting on the user in this window, by kind (0.1.61 §A4). Each kind is a list, oldest first, keyed by `callId`: a
 *  second card of a kind (a window's own run-command card and a job's) waits behind the first and never replaces it. */
export type PendingCommand = { callId: string; pretty: string; reason: string; remoteHost: string; fingerprints: string[]; background?: boolean;
  sandbox?: "outside" | "retry"; why?: string; receivedAt?: number; seq?: number } & CardV2;
export type PendingEnrollNode = { callId: string; name: string; host: string; user: string; fingerprints: string[]; receivedAt?: number; seq?: number };
export type PendingWorkspaceWrite = { callId: string; workspace: string; action: string; path: string; background?: boolean; receivedAt?: number; seq?: number } & CardV2;
export type PendingSchedule = { callId: string; name: string; when: string; background?: boolean; receivedAt?: number; seq?: number } & CardV2;
export type PendingCapability = { callId: string; receivedAt?: number; seq?: number } & import("../api/client.types").CapabilityCard;
export type PendingAction = { callId: string; kind: ActionKind | (string & {}); target: string; detail: string; background?: boolean;
  receivedAt?: number; seq?: number } & CardV2;
export type PendingConnectMcp = {
  callId: string;
  key: string;
  label: string;
  labelKey?: string;
  transport: string;
  command: string;
  argv: string[];
  url: string | null;
  envKeys: { name: string; description: string; get_it_url: string; paid: boolean }[];
  prerequisites: string;
  requiresPath: boolean;
  pathPlaceholder: string | null;
  receivedAt?: number; seq?: number;
  /** The server this card connected (set when its apply succeeded): the follow-up frame names the server, not the card. */
  appliedServerId?: number;
};

/** How a card's own apply stands in this window (0.1.61 §A4, fix round 3): a connect and an enrolment call the REST API from the card and
 *  take a while. It is kept here by call id, not in the card, because the card is remounted when the person pages away and back: while
 *  the apply is in flight that card's buttons stay off (never a second apply) though paging and the other cards stay available, and a
 *  card that comes back knows how the apply ended (a connect's result, an enrolment's error). */
export type CardApply = { busy: boolean; result?: ApplyConnectMcpResult; error?: string;
  /** The person hid the card while the apply was in flight (`hideCard`): it goes on with no card, and the chat says how it ended. */
  hidden?: boolean };

interface ArslanState {
  items: ArslanThreadItem[];
  streaming: boolean;
  streamingText: string;
  streamSource: "arslan" | "spawn" | null;
  streamSpawnId: number | null;
  streamSpawnName: string | null;
  pendingRoute: { spawnId: number; spawnName: string | null } | null;
  spawnNames: Record<number, string>;
  error: string | null;
  errorTranslations: RuntimeErrorTranslations | null;
  lastMessageId: number;
  pending: boolean;
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
  // Pending shell commands: one is added when a `propose_run_command` frame arrives (the same call id again replaces
  // it, a new one waits behind); a card leaves once the user confirms (sends confirm_run_command) or cancels. Every
  // kind below is such a list (0.1.61 §A4), oldest first: nothing a second card could hide stays unanswerable.
  pendingCommands: PendingCommand[];
  // 0.1.42 background jobs in this conversation, keyed by job id. Each has a
  // `kind: "job"` item in `items` marking where its live card sits.
  jobs: Record<string, JobCard>;
  // The latest job that finished or began waiting on a card — the chat view turns
  // it into one spoken line while voice conversation is on. `seq` makes repeats distinct.
  jobNotice: { seq: number; jobId: string; kind: "finished" | "needs_approval"; outcome: JobOutcome | null; goal: string } | null;
  // P3c: Arslan asks to enrol a machine. The card WRITES NOTHING over the socket —
  // its button calls the REST endpoint, which is what makes enrolment a human act.
  // 0.1.55: receivedAt drives the asking card's countdown; 0.1.61: a card waits 30 minutes, and counts down
  // to the frame's own expires_at when it has one.
  pendingEnrollNodes: PendingEnrollNode[];
  pendingWorkspaceWrites: PendingWorkspaceWrite[];
  pendingSchedules: PendingSchedule[];
  // 0.1.57: add a capability and retry (only this window answers; the card may carry a key).
  pendingCapabilities: PendingCapability[];
  clearPendingCapability: (callId: string) => void;
  // 0.1.45: a background job asks before it acts in the browser or on the Mac.
  pendingActions: PendingAction[];
  // 0.1.61 §A4: a card here ran out with nobody answering — "waiting for you", never "declined".
  cardExpired: boolean;
  // NEXT BUILD (conversation-driven MCP, Task 5): set when a `propose_connect_mcp`
  // frame arrives. env_keys carries credential NAMES + metadata only — the card
  // collects VALUES locally and sends them only over REST (addMcpServer). A card is cleared
  // once its connect's follow-up (`mcp_connect_followup`, which names the server) lands, or on cancel.
  pendingConnectMcps: PendingConnectMcp[];
  /** The connect / enrol cards' applies, by call id (see CardApply). */
  cardApply: Record<string, CardApply>;
  /** Which conversation this is: it goes up with every `resetForNewConversation`. An apply that settles after it has changed belongs to a
   *  conversation the person has left, and tells nobody in this one. */
  epoch: number;
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
  // 0.1.59: when the turn last moved (any frame but the server's "still working" beat) —
  // drives the live row's "Still working — a long answer can take a few minutes".
  lastStepAt: number | null;
  // 0.1.59: this window's message is waiting for the conversation's current turn to finish.
  queued: boolean;
  // S3-M1 · cancellable runs: the recorded run id of the in-flight stream (from
  // stream_start's run_id — both host and spawn runs). The stop button POSTs
  // /runs/{activeRunId}/cancel. Cleared on stream_end/error/run_cancelled.
  activeRunId: number | null;
  taskState: import("../api/tasks").TaskFrame | null;
  taskSequences: Record<string, number>;
  // The Web Speech speaker owes the engine at least one utterance end. Conversation
  // mode mutes the microphone while this is true.
  speaking: boolean;

  setSpawnNames: (map: Record<number, string>) => void;
  setThinking: (v: boolean) => void;
  addUserMessage: (content: string, attachments?: MessageAttachment[]) => void;
  handleFrame: (frame: ArslanServerMessage) => void;
  markProposalConfirmed: (spawnId: number) => void;
  // PA-3: flip a clarify card to its answered (disabled) state once the user picked
  // an option — a stale re-click can never send a second user_message.
  markClarifyAnswered: (itemId: number) => void;
  clearPendingCommand: (callId: string) => void;
  setVoice: (v: { enabled: boolean; lang: string }) => void;
  /** Say one line aloud (a background job finished, or is waiting on a card).
   *  Never interrupts a reply being read; the line is dropped instead. */
  speakLine: (text: string, lang: string) => void;
  clearPendingEnrollNode: (callId: string) => void;
  clearPendingWorkspaceWrite: (callId: string) => void;
  clearPendingSchedule: (callId: string) => void;
  clearPendingAction: (callId: string) => void;
  clearPendingConnectMcp: (callId: string) => void;
  /** The connect card `callId` connected the server `serverId`: the follow-up that names that server closes it. */
  markConnectApplied: (callId: string, serverId: number) => void;
  /** The card `callId` has started its apply (and forgets how the last one ended). */
  beginCardApply: (callId: string) => void;
  /** Its apply ended, with how: nothing, a connect's result or an enrolment's error. A card that is gone keeps nothing. Returns whether the card had
   *  been hidden (`hideCard`): then there is no card to show how it ended, and whoever ended it says so in the chat (`addCardNote`). */
  endCardApply: (callId: string, outcome?: { result?: ApplyConnectMcpResult; error?: string }) => boolean;
  /** The card `callId`, a connect or an enrolment whose apply is in flight, leaves the slot; the apply goes on. Nothing else can be hidden: a card
   *  that is not busy is answered. */
  hideCard: (callId: string) => void;
  /** A plain note in the chat (the way a hidden apply ends). */
  addCardNote: (text: string) => void;
  /** 0.1.61 §A4: the card `callId` ran out unanswered (the server tells a window nothing for its
   *  own card): it leaves the slot, and the slot says it is waiting for you. */
  expireCard: (callId: string) => void;
  dismissCardExpired: () => void;
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

// When the reply now on screen started, or now if none is streaming.
function runningSince(s: { streaming: boolean; workStartedAt: number | null }): number {
  return s.streaming && s.workStartedAt != null ? s.workStartedAt : Date.now();
}

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
// Voice output (V1). A single module-level speaker: the reply streams, and we
// speak it sentence by sentence. Module-level rather than store state because a
// speech synthesizer is a singleton device, not serializable UI state.
let _speaker: ReturnType<typeof createSpeaker> | null = null;
let _voiceEnabled = false;
let _voiceLang = "en-US";

function _voiceStart() {
  if (_speaker) _speaker.cancel();
  _speaker = _voiceEnabled
    ? createSpeaker(_voiceLang, { onActive: (a) => useArslanStore.setState({ speaking: a }) })
    : null;
}
function _voiceFeed(text: string) { _speaker?.feed(text); }
function _voiceEnd() { _speaker?.end(); }
function _voiceStop() { _speaker?.cancel(); _speaker = null; }


/** 0.1.61 §A4: what a card from the permission layer adds to a pending card. */
type CardV2 = { options?: string[]; alwaysLabel?: string; title?: string; permKind?: string; why?: string; expiresAt?: number };

/** The v2 fields of a card frame (permissions._ask): its choices, its literal "Always" scope, its
 *  question (the server's English title, and the model's own why when it gave one: that is the question,
 *  §A4), its permission kind and the server's own expiry (Unix s → ms). An old frame has none and is
 *  shown and answered exactly as before. */
function _cardV2(frame: { options?: unknown; always_label?: unknown; title?: unknown; perm_kind?: unknown; why?: unknown; expires_at?: unknown }): CardV2 {
  const options = Array.isArray(frame.options) ? frame.options.filter((o): o is string => typeof o === "string") : [];
  return {
    ...(options.length ? { options } : {}),
    ...(typeof frame.always_label === "string" && frame.always_label ? { alwaysLabel: frame.always_label } : {}),
    ...(typeof frame.title === "string" && frame.title.trim() ? { title: frame.title.trim() } : {}),
    ...(typeof frame.perm_kind === "string" && frame.perm_kind ? { permKind: frame.perm_kind } : {}),
    ...(typeof frame.why === "string" && frame.why.trim() ? { why: frame.why.trim() } : {}),
    ...(typeof frame.expires_at === "number" && Number.isFinite(frame.expires_at)
      ? { expiresAt: Math.round(frame.expires_at * 1000) } : {}),
  };
}

/** Every list of cards waiting on the user in this window: a card of any of them runs out, or is resolved elsewhere, by its id. */
const CARD_LISTS = ["pendingCommands", "pendingEnrollNodes", "pendingWorkspaceWrites", "pendingSchedules", "pendingActions",
                    "pendingCapabilities", "pendingConnectMcps"] as const;
type CardLists = Pick<ArslanState, typeof CARD_LISTS[number]>;

/** The list with `card` added at the end — the newest — replacing the card of the same call id if it is sent again. */
function _added<T extends { callId: string }>(list: T[], card: T): T[] {
  return [...list.filter((c) => c.callId !== card.callId), card];
}

/** Whether the card `id` is one of the pending ones here. */
function _shows(state: CardLists, id: string): boolean {
  return !!id && CARD_LISTS.some((k) => state[k].some((c) => c.callId === id));
}

/** The change that lets go of the applies of the cards `ids` — a card that leaves takes its own entry and no other's; nothing to change if none has one. */
function _dropApply(state: { cardApply: Record<string, CardApply> }, ids: string[]): { cardApply?: Record<string, CardApply> } {
  if (!ids.some((id) => id in state.cardApply)) return {};
  return { cardApply: Object.fromEntries(Object.entries(state.cardApply).filter(([id]) => !ids.includes(id))) };
}

/** The lists that hold the card `id`, without it — only that card, never another of its kind — and without its apply entry, if it has one. */
function _withoutCard(state: CardLists & { cardApply: Record<string, CardApply> }, id: string): Partial<CardLists & { cardApply: Record<string, CardApply> }> {
  const out: Record<string, unknown> = {};
  if (!id) return out;                                  // a frame that names no card resolves none
  for (const k of CARD_LISTS) if (state[k].some((c) => c.callId === id)) out[k] = state[k].filter((c) => c.callId !== id);
  return { ...out, ..._dropApply(state, [id]) } as Partial<CardLists & { cardApply: Record<string, CardApply> }>;
}

/** The fallback when the server cannot be asked: how long after a (re)connect's `history` frame the server's replay of the waiting cards is taken to be
 *  over. The replay is sent right behind it (ws/arslan.py: history, the journaled frames, the jobs, then `approvals.pending_cards`), in one burst;
 *  there is no frame that ends it. */
export const REPLAY_SETTLE_MS = 3_000;
/** The cards that are replayed to a socket that connects: the shared ones, which `approvals.pending_cards` lists. A proposal to enrol a machine or to
 *  connect a server is never registered there, and a capability card is the asking window's own. */
const REPLAYED = new Set(["propose_run_command", "propose_workspace_write", "propose_schedule", "propose_action"]);
/** After a `history` frame: the shared cards that were on screen, which the replay has not listed (yet). Nothing is waiting when there were none. */
let _replay: { stale: Set<string>; timer: ReturnType<typeof setTimeout>; due: boolean; failed: boolean } | null = null;
function _stopReplay() {
  if (_replay) clearTimeout(_replay.timer);
  _replay = null;
}
/** A socket has (re)connected: the shared cards on screen are at stake. One whose `card_resolved` went missing while the socket was down is not listed
 *  by the replay and would stay as a dead "1 / 2" entry (an answer to it is swallowed) until its own expiry. But a replay that does not list a card does
 *  not say it is gone: a window's own card is private until the server sees its old socket close, and is never replayed, though the server still waits on
 *  it. So the window asks the server which cards wait (GET /approvals/pending: private and shared, none that is done) and drops the stale ones it does
 *  not list — exactly, and at once. The timer is only the fallback when that request fails: then the cards the replay did not list go when it is up.
 *  Never before: a card the replay does list is never taken away and brought back, and a card it brings after all, late, is added again like any other. */
function _beginReplay(get: GetState, set: SetState) {
  _stopReplay();
  const s = get();
  const stale = new Set([...s.pendingCommands, ...s.pendingWorkspaceWrites, ...s.pendingSchedules, ...s.pendingActions].map((c) => c.callId));
  if (!stale.size) return;
  /** Drop the stale cards that are not in `waiting` (the server's list), from the four lists. */
  const drop = (mine: NonNullable<typeof _replay>, waiting?: Set<string>) => {
    const now = get();
    const gone = (c: { callId: string }) => mine.stale.has(c.callId) && !waiting?.has(c.callId);
    if (![...now.pendingCommands, ...now.pendingWorkspaceWrites, ...now.pendingSchedules, ...now.pendingActions].some(gone)) return;
    const kept = <T extends { callId: string }>(list: T[]) => list.filter((c) => !gone(c));
    set({ pendingCommands: kept(now.pendingCommands), pendingWorkspaceWrites: kept(now.pendingWorkspaceWrites),
          pendingSchedules: kept(now.pendingSchedules), pendingActions: kept(now.pendingActions) });
  };
  const mine: NonNullable<typeof _replay> = {
    stale, due: false, failed: false,
    timer: setTimeout(() => {
      if (_replay !== mine) return;
      mine.due = true;                                  // the replay is over; what it did not list goes if the server cannot say better
      if (mine.failed) { _replay = null; drop(mine); }
    }, REPLAY_SETTLE_MS),
  };
  _replay = mine;
  // (An answer that is no list throws below, and is a failure like any other.)
  void request<{ call_id?: unknown }[]>("/approvals/pending").then((rows) => {
    if (_replay !== mine) return;                       // another reconnect, a new conversation or a new store came first
    const waiting = new Set(rows.flatMap((r) => (typeof r?.call_id === "string" ? [r.call_id] : [])));
    _stopReplay();                                      // exact: no timer left to fire
    drop(mine, waiting);
  }).catch(() => {
    if (_replay !== mine) return;
    mine.failed = true;
    if (mine.due) { _replay = null; drop(mine); }
  });
}

// A background job's card is waiting: which job is not in the frame, so the
// notice names the running one when there is exactly one.
function _approvalNotice(state: { jobs: Record<string, JobCard>; jobNotice: { seq: number } | null }) {
  const running = Object.values(state.jobs).filter((j) => j.phase !== "finished");
  return { jobNotice: { seq: (state.jobNotice?.seq ?? 0) + 1, jobId: running.length === 1 ? running[0].jobId : "",
                        kind: "needs_approval" as const, outcome: null, goal: running.length === 1 ? running[0].goal : "" } };
}

const JOB_TOOLS = new Set(["start_background_work", "background_status", "stop_background_work"]);

function initialData() {
  return {
    items: [] as ArslanThreadItem[],
    streaming: false,
    streamingText: "",
    streamSource: null as "arslan" | "spawn" | null,
    streamSpawnId: null as number | null,
    streamSpawnName: null as string | null,
    pendingRoute: null as { spawnId: number; spawnName: string | null } | null,
    spawnNames: {} as Record<number, string>,
    error: null as string | null,
    errorTranslations: null as RuntimeErrorTranslations | null,
    lastMessageId: 0,
    pending: false,
    pendingSpawnMeta: {} as Record<number, { assistant_message_id: number; task_brief: string; run_id?: number }>,
    activitySteps: [] as ToolStep[],
    pendingProposalSpawnId: null as number | null,
    roster: [] as RosterMember[],
    pendingCommands: [] as PendingCommand[],
    jobs: {} as Record<string, JobCard>,
    jobNotice: null as { seq: number; jobId: string; kind: "finished" | "needs_approval"; outcome: JobOutcome | null; goal: string } | null,
    pendingEnrollNodes: [] as PendingEnrollNode[],
    pendingWorkspaceWrites: [] as PendingWorkspaceWrite[],
    pendingCapabilities: [] as PendingCapability[],
    pendingSchedules: [] as PendingSchedule[],
    pendingActions: [] as PendingAction[],
    pendingConnectMcps: [] as PendingConnectMcp[],
    cardApply: {} as Record<string, CardApply>,
    epoch: 0,
    thinking: false,
    workStartedAt: null as number | null,
    lastFrameAt: null as number | null,
    stalled: false,
    lastStepAt: null as number | null,
    queued: false,
    cardExpired: false,
    activeRunId: null as number | null,
    taskState: null as import("../api/tasks").TaskFrame | null,
    taskSequences: {} as Record<string, number>,
    speaking: false,
  };
}

type SetState = (partial: Partial<ArslanState>) => void;
type GetState = () => ArslanState;

function makeActions(set: SetState, get: GetState) {
  return {
    // Turn start also arms the stall watchdog (lastFrameAt baseline) so a
    // dispatch that never produces a single frame still times out into 「已中断」.
    // A message sent while a reply is still streaming (0.1.59: it waits its turn) keeps that reply's timer.
    setThinking: (v: boolean) =>
      set(v ? { thinking: true, workStartedAt: runningSince(get()), lastFrameAt: Date.now(), lastStepAt: Date.now(),
        stalled: false } : { thinking: false }),

    setSpawnNames: (map: Record<number, string>) =>
      set({ spawnNames: { ...get().spawnNames, ...map } }),

    // attachments = session-only display echo (image thumbnails via object-URL, doc chips);
    // never persisted — history-restored items simply won't carry them.
    addUserMessage: (content: string, attachments?: MessageAttachment[]) =>
      set({
        items: [...get().items, { id: nextClientId(), kind: "message", role: "user", content, ...(attachments?.length ? { attachments } : {}) }],
        pending: true,
        cardExpired: false,               // the user is back: the "waiting for you" line has done its job
        workStartedAt: runningSince(get()),
        lastFrameAt: Date.now(),
        lastStepAt: Date.now(),
        stalled: false,
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
    clearPendingCommand: (callId: string) => set({ pendingCommands: get().pendingCommands.filter((c) => c.callId !== callId) }),
    setVoice: ({ enabled, lang }) => {
      _voiceEnabled = enabled;
      _voiceLang = lang;
      if (!enabled) _voiceStop();     // turning it off mid-reply stops at once
    },
    speakLine: (text, lang) => {
      if (!text || get().speaking || get().streaming) return;
      const speaker = createSpeaker(lang, { onActive: (a) => useArslanStore.setState({ speaking: a }) });
      void speaker.feed(text).then(() => speaker.end());
    },
    clearPendingEnrollNode: (callId: string) => set({ pendingEnrollNodes: get().pendingEnrollNodes.filter((c) => c.callId !== callId), ..._dropApply(get(), [callId]) }),
    clearPendingWorkspaceWrite: (callId: string) => set({ pendingWorkspaceWrites: get().pendingWorkspaceWrites.filter((c) => c.callId !== callId) }),
    clearPendingSchedule: (callId: string) => set({ pendingSchedules: get().pendingSchedules.filter((c) => c.callId !== callId) }),
    clearPendingCapability: (callId: string) => set({ pendingCapabilities: get().pendingCapabilities.filter((c) => c.callId !== callId) }),
    clearPendingAction: (callId: string) => set({ pendingActions: get().pendingActions.filter((c) => c.callId !== callId) }),
    clearPendingConnectMcp: (callId: string) => set({ pendingConnectMcps: get().pendingConnectMcps.filter((c) => c.callId !== callId), ..._dropApply(get(), [callId]) }),
    markConnectApplied: (callId: string, serverId: number) => set({
      pendingConnectMcps: get().pendingConnectMcps.map((c) => (c.callId === callId ? { ...c, appliedServerId: serverId } : c)),
    }),
    beginCardApply: (callId: string) => set({ cardApply: { ...get().cardApply, [callId]: { busy: true } } }),
    endCardApply: (callId: string, outcome = {}) => {
      const entry = get().cardApply[callId];
      if (!entry) return false;                                                        // its card is gone: nothing to keep
      if (entry.hidden) {                                                              // no card to come back to: let go, and tell the caller to say how it ended
        set(_dropApply(get(), [callId]));
        return true;
      }
      set({ cardApply: { ...get().cardApply, [callId]: { busy: false, ...outcome } } });
      return false;
    },
    hideCard: (callId: string) => {
      const s = get();
      const entry = s.cardApply[callId];
      if (!entry?.busy || entry.hidden) return;                                        // only an apply in flight can be hidden
      set({
        pendingConnectMcps: s.pendingConnectMcps.filter((c) => c.callId !== callId),
        pendingEnrollNodes: s.pendingEnrollNodes.filter((c) => c.callId !== callId),
        cardApply: { ...s.cardApply, [callId]: { ...entry, hidden: true } },
      });
    },
    addCardNote: (text: string) => {
      if (text) set({ items: [...get().items, { id: nextClientId(), kind: "system", role: "arslan", content: text }] });
    },
    expireCard: (callId: string) => {
      const s = get();
      if (_shows(s, callId)) set({ ..._withoutCard(s, callId), cardExpired: true });
    },
    dismissCardExpired: () => set({ cardExpired: false }),
    clearError: () => set({ error: null, errorTranslations: null }),

    // Clear all conversation state so the incoming `history` frame for the new
    // conversation_id repopulates from scratch with no stale carry-over.
    resetForNewConversation: () => { _voiceStop(); _stopReplay(); set({ ...initialData(), epoch: get().epoch + 1 }); },

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
      // flags below, ending the turn entirely. 0.1.59: the server's "working" beat
      // (every 15 s of a turn) is alive but not a step — it never resets lastStepAt.
      const now = Date.now();
      // The replay lists a card by proposing it again: it is no longer at stake (see _beginReplay).
      if (_replay && REPLAYED.has(frame.type)) _replay.stale.delete((frame as { call_id?: string }).call_id ?? "");
      set(frame.type === "working" || frame.type === "queued"
        ? { lastFrameAt: now, stalled: false }
        : { lastFrameAt: now, lastStepAt: now, stalled: false });
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
      const RESPONDING_TYPES = new Set(["message", "error", "fact_saved", "propose_run_command", "propose_enroll_node", "propose_workspace_write", "propose_schedule", "propose_capability", "propose_connect_mcp", "spawn_updated", "clarify_options"]);
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
        job_outcome?: JobOutcome | null;
        source?: string | null;
        process?: ProcessSummary;
        files?: StoredArtifact[];
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
            ...(row.process ? { processSummary: row.process } : {}),
          };
        }
        return {
          id: row.message_id,
          kind: "message",
          role: row.role === "arslan" ? "arslan" : "user",
          content: row.content,
          runId: row.run_id ?? undefined,
          ...(row.process && row.role === "arslan" ? { processSummary: row.process } : {}),
          ...(row.files?.length && row.role === "arslan" ? { files: row.files } : {}),
          // 0.1.42: a background job's result keeps its label across reloads.
          ...(row.job_outcome ? { jobId: `message-${row.message_id}`, jobOutcome: row.job_outcome } : {}),
          ...(row.role === "user" && row.source === "phone" ? { fromPhone: true } : {}),
        };
      };
      switch (frame.type) {
        case "task_state":
          if ((state.taskSequences[frame.task_id] ?? -1) >= frame.sequence) break;
          set({ taskState: frame, taskSequences: { ...state.taskSequences, [frame.task_id]: frame.sequence } });
          break;
        case "history": {
          const items: ArslanThreadItem[] = frame.messages.map(rowToItem);
          const lastId = items.reduce((max, it) => (it.id > max ? it.id : max), 0);
          // A reconnect replays history; the live job cards are not in it.
          items.push(...state.items.filter((it) => it.kind === "job"));
          // 0.1.59: history is the truth; a run still in flight is rebuilt by the replay that
          // follows it (run_in_progress + its journal). A live stream left over from before the
          // socket dropped — a replay cut by a second drop — used to survive here as a frozen
          // half copy of the answer plus a "working" row whose timer never stopped.
          if (state.streaming) _voiceStop();
          set({
            items, lastMessageId: lastId, activitySteps: [], activeRunId: null,
            streaming: false, streamingText: "", thinking: false, workStartedAt: null, queued: false,
            streamSource: null, streamSpawnId: null, streamSpawnName: null,
          });
          _beginReplay(get, set);
          break;
        }
        case "message": {
          const item = rowToItem(frame);
          if (frame.job_id) { item.jobId = frame.job_id; item.jobOutcome = frame.outcome ?? null; }
          set({
            items: [...state.items, item],
            lastMessageId: Math.max(state.lastMessageId, frame.message_id),
          });
          break;
        }
        case "job_update": {
          const card: JobCard = {
            jobId: frame.job_id, goal: frame.goal, phase: frame.phase, step: frame.step,
            outcome: frame.outcome, detail: frame.detail, budget: frame.budget ?? null, criteria: frame.criteria,
          };
          const known = state.items.some((it) => it.kind === "job" && it.jobId === frame.job_id);
          set({
            jobs: { ...state.jobs, [frame.job_id]: card },
            items: known ? state.items
              : [...state.items, { id: nextClientId(), kind: "job", role: "arslan", content: "", jobId: frame.job_id }],
          });
          break;
        }
        case "job_spoken":
          set({ jobNotice: { seq: (state.jobNotice?.seq ?? 0) + 1, jobId: frame.job_id,
                             kind: "finished", outcome: frame.outcome, goal: frame.goal } });
          break;
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
          if (frame.temporary) _voiceStop(); else _voiceStart();
          set({
            pending: false,
            streaming: true,
            streamingText: "",
            // 0.1.58 §1: a turn the window did not start (a fire, a reconnect) still gets its length.
            workStartedAt: state.workStartedAt ?? Date.now(),
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
          _voiceFeed(frame.content);
          set({ thinking: false, streamingText: state.streamingText + frame.content });
          break;
        case "stream_end": {
          if (!state.streaming) break;
          _voiceEnd();
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
            runId: frame.temporary ? null : frame.run_id ?? meta?.run_id ?? state.activeRunId ?? null,
            taskBrief: meta?.task_brief ?? null,
            toolSteps: state.activitySteps.length > 0 ? state.activitySteps : undefined,
            ...(state.workStartedAt ? { elapsedMs: Date.now() - state.workStartedAt } : {}),
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
          // 0.1.59: a replayed stream_end for a message already shown adds no second copy.
          const shown = frame.message_id != null
            && state.items.some((it) => it.kind === "message" && it.id === frame.message_id);
          set({
            thinking: false,
            workStartedAt: null,
            items: shown ? state.items : [...state.items, item],
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
              { tool: frame.tool, argsSummary: frame.args_summary, status: "running", startedAt: Date.now() },
            ],
          });
          break;
        case "note": {
          // 0.1.58 §1: Arslan's narration before its next tool call — a line between steps.
          const text = (frame.text ?? "").trim();
          if (text) set({ activitySteps: [...state.activitySteps, { kind: "note", tool: "", argsSummary: "", status: "ok", text }] });
          break;
        }
        case "tool_result": {
          // The loop is sequential per tool: resolve the most recent unresolved
          // step with the same tool name.
          const steps = [...state.activitySteps];
          for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].tool === frame.tool && steps[i].status === "running") {
              steps[i] = {
                ...steps[i],
                ...(steps[i].startedAt ? { ms: Date.now() - steps[i].startedAt! } : {}),
                status: frame.ok ? "ok" : "error",
                resultSummary: frame.summary,
                // 0.1.58 §2: a file the step wrote rides as the singular `artifact` (kind "file",
                // write_file / edit_file); it was dropped here, so written files never showed.
                artifacts: [...(frame.artifacts ?? []), ...(frame.artifact?.kind === "file" ? [frame.artifact as StoredArtifact] : [])],
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
          // 0.1.42: a successful start/status/stop of background work is shown by
          // the job card itself; only a failure stays in the tool trail.
          const shown = JOB_TOOLS.has(frame.tool)
            ? steps.filter((step) => !(step.tool === frame.tool && step.status === "ok")) : steps;
          set({ activitySteps: shown, thinking: true });
          break;
        }
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
        case "plan_proposed":
          set({
            items: [...state.items, { id: nextClientId(), kind: "plan", role: "arslan", content: frame.reason,
              planProposal: { projectId: frame.project_id, id: frame.proposal_id, diff: frame.diff, reason: frame.reason,
                cleared: frame.cleared } }],
          });
          break;
        case "lesson_learned":
          set({
            items: [
              ...state.items,
              { id: nextClientId(), kind: "lesson", role: "arslan", content: frame.lesson.text,
                lesson: { id: frame.lesson.id, status: frame.lesson.status } },
            ],
          });
          break;
        case "fact_saved":
        case "memory_proposed": {
          // D1 (0.1.55): everything remembered after one turn becomes ONE quiet line.
          // Facts arrive after the answer, back to back; a new item starts the next turn.
          const fact = {
            content: frame.content, sensitive: frame.sensitive,
            entryId: frame.entry_id ?? null, version: frame.version ?? null,
            status: frame.type === "memory_proposed" ? "proposed" as const : "active" as const,
          };
          const last = state.items[state.items.length - 1];
          if (last && last.kind === "fact") {
            const facts = [...(last.facts ?? []), fact];
            set({ items: [...state.items.slice(0, -1),
              { ...last, facts, content: facts.map((f) => f.content).join(" · ") }] });
          } else {
            set({ items: [...state.items, { id: nextClientId(), kind: "fact", role: "arslan",
              content: frame.content, sensitive: frame.sensitive, facts: [fact] }] });
          }
          break;
        }
        case "spawn_updated":
          set({
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
        case "clarify_options":
          // PA-3 structured clarification card: rendered as a thread ITEM (question +
          // one-click option buttons). A pick sends the label as a normal user_message
          // and markClarifyAnswered disables the card. 🔒 question/options come ONLY
          // from the backend clarify_options frame (validated/clamped 2-4 server-side),
          // NEVER from LLM message text.
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
          set({ pendingCommands: _added(state.pendingCommands, { callId: frame.call_id, pretty: frame.pretty,
                                  reason: frame.reason || "",
                                  // Present only for P3b: this command runs on ANOTHER
                                  // machine, and the card has to lead with that.
                                  remoteHost: frame.remote_host || "",
                                  fingerprints: frame.fingerprints || [],
                                  background: frame.background === true,
                                  // 0.1.51 P3: the card is about leaving the sandbox.
                                  ...(frame.sandbox === "outside" || frame.sandbox === "retry"
                                    ? { sandbox: frame.sandbox, why: frame.why || "" } : {}),
                                  ..._cardV2(frame),
                                  ..._arrived() }),
               ...(frame.background ? _approvalNotice(state) : {}) });
          break;
        case "propose_enroll_node":
          // A proposal is journaled and replayed to a socket that re-attaches: one whose apply the person hid is not brought back (it would be a card
          // with a live button over an apply that goes on, and a second apply on the next click).
          if (state.cardApply[frame.call_id]?.hidden) break;
          set({ pendingEnrollNodes: _added(state.pendingEnrollNodes, { callId: frame.call_id, name: frame.name,
                                     host: frame.host, user: frame.user,
                                     fingerprints: frame.fingerprints || [], ..._arrived() }) });
          break;
        case "propose_schedule":
          set({ pendingSchedules: _added(state.pendingSchedules, { callId: frame.call_id, name: frame.name,
                                   when: frame.when, background: frame.background === true, ..._cardV2(frame),
                                   ..._arrived() }),
               ...(frame.background ? _approvalNotice(state) : {}) });
          break;
        case "propose_capability": {
          const { type: _t, call_id, ...card } = frame;
          void _t;
          set({ pendingCapabilities: _added(state.pendingCapabilities, { callId: call_id, ...card, ..._arrived() }) });
          break;
        }
        case "capability_result":
          set({
            items: [...state.items, { id: nextClientId(), kind: "capability", role: "arslan", content: frame.name,
              capabilityResult: { state: frame.state, name: frame.name, tools: frame.tools, sourceId: frame.source_id,
                stage: frame.stage, code: frame.code, detail: frame.detail } }],
          });
          break;
        case "propose_action":
          set({ pendingActions: _added(state.pendingActions, { callId: frame.call_id, kind: frame.kind, target: frame.target, detail: frame.detail,
                                 background: frame.background === true, ..._cardV2(frame), ..._arrived() }),
                ..._approvalNotice(state) });
          break;
        case "card_resolved": {
          // Whoever answered first (another window, the phone, the Inbox, the island, a message
          // typed here) decided; a copy still open here closes. Only the card with this call_id —
          // never another of its kind. 0.1.61 §A4: one that ran out says "waiting for you".
          const id = frame.call_id;
          set({ ..._withoutCard(state, id), ...(frame.outcome === "expired" && _shows(state, id) ? { cardExpired: true } : {}) });
          break;
        }
        case "propose_workspace_write":
          set({ pendingWorkspaceWrites: _added(state.pendingWorkspaceWrites, {
            callId: frame.call_id, workspace: frame.workspace,
            action: frame.action, path: frame.path, background: frame.background === true, ..._cardV2(frame),
            ..._arrived() }),
               ...(frame.background ? _approvalNotice(state) : {}) });
          break;
        case "propose_connect_mcp":
          if (state.cardApply[frame.call_id]?.hidden) break;              // as above: a hidden apply's card does not come back
          // NEXT BUILD (conversation-driven MCP, Task 5): env_keys carries credential
          // NAMES + metadata only (never a value) — the ConnectMcpCard collects values
          // locally and sends them ONLY over REST (addMcpServer's body).
          set({
            pendingConnectMcps: _added(state.pendingConnectMcps, {
              callId: frame.call_id,
              key: frame.key,
              label: frame.label,
              ...(frame.label_key ? { labelKey: frame.label_key } : {}),
              transport: frame.transport,
              command: frame.command,
              argv: frame.argv,
              url: frame.url,
              envKeys: frame.env_keys,
              prerequisites: frame.prerequisites,
              requiresPath: frame.requires_path,
              pathPlaceholder: frame.path_placeholder,
              ..._arrived(),
            }),
          });
          break;
        case "mcp_connect_followup": {
          // Honest, tier-aware result recomputed server-side from the DB (Task 3) —
          // appends a plain chat note, same idiom as attachment_stored below.
          // assignable=false means connected but nothing is safe+wired yet, so the note
          // points at Settings instead of implying it's ready to equip.
          //
          // It also closes the card that was connected. The frame is fanned out to every window on the
          // conversation and names the card (the proposal's call_id, echoed by the server), so each window
          // closes its own copy — not only the one that connected it and so marked its card. A follow-up that
          // names no card (an older server) names only the server: the card that recorded connecting it closes.
          const named = typeof frame.call_id === "string" && frame.call_id !== "";
          const closes = (c: PendingConnectMcp) => (named
            ? c.callId === frame.call_id
            : typeof frame.server_id === "number" && c.appliedServerId === frame.server_id);
          set({
            pendingConnectMcps: state.pendingConnectMcps.filter((c) => !closes(c)),
            ..._dropApply(state, state.pendingConnectMcps.filter(closes).map((c) => c.callId)),
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
        }
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
            errorTranslations: runtimeErrorTranslations(frame.message_i18n),
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
        // 0.1.59: a long answer is not "Interrupted" — the beat above kept the watchdog quiet.
        case "working":
          break;
        // 0.1.59: this window's message waits for the conversation's current turn…
        case "queued":
          set({ queued: true });
          break;
        // …and its own turn has started now.
        case "dequeued":
          set({ queued: false, thinking: true, workStartedAt: Date.now(), lastStepAt: Date.now() });
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
  _stopReplay();                       // a reset is a fresh store: no reconnect from before it is still settling
  return {
    ...initialData(),
    ...makeActions(
      (partial) => useArslanStore.setState(partial),
      () => useArslanStore.getState(),
    ),
  };
}
