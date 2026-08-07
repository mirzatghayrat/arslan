/**
 * Every factual claim any film is allowed to put on screen, with the place in
 * the repository each one comes from.
 *
 * This module exists because four finished films shipped with invented facts in
 * them: the wrong licence in every call to action, a fixed roster of six spawns
 * that the product does not have, exam dimensions that do not exist, and a
 * hero statistic that was made up. None of it was malicious — it was copy
 * written early, carried forward through four rewrites, and never checked
 * against the thing it was describing.
 *
 * So the rule is now: a film may not contain a number, a name or a claim that
 * is not in here, and nothing goes in here without a source comment. If a claim
 * is illustrative rather than measured it has to say so on screen.
 */

/* ------------------------------------------------------------------ */
/* Identity                                                            */

export const PRODUCT = {
  name: 'Arslan',
  /** README masthead. */
  what: 'a local-first personal AI orchestrator',
  /** web/src/locales/en.json → sidebar.brand_subtitle. The product's own line. */
  tagline: 'One Becomes Many',
  repo: 'github.com/mirzatghayrat/arslan',
  /** README install link. */
  download: 'Arslan-macos-arm64.dmg',
  /** LICENSE + README badge + docs/marketing/copy.md. NOT MIT. */
  license: 'Apache-2.0',
  /** desktop/src-tauri/tauri.conf.json → minimumSystemVersion 11.0; arm64 build. */
  platform: 'macOS 11+ · Apple Silicon',
  /** README: "signed, notarized, and it keeps itself up to date". */
  signing: 'signed & notarized',
  /** README "Status — honest about what's proven". The honesty is the brand:
      docs/marketing/copy.md says pre-v1 and macOS-first are never hidden. */
  status: 'pre-v1 · macOS-first · open source',
} as const;

/**
 * The three hooks, from docs/marketing/copy.md. Each film carries ONE — four
 * films all making the same four points is one film shown four times.
 */
export const HOOKS = {
  machine: 'a machine, not a chat box',
  exam: 'self-evolution that must pass an exam',
  local: 'all local, your keys',
} as const;

/** README masthead, verbatim. */
export const MASTHEAD = {
  a: 'You talk to one host agent.',
  b: 'It routes work to persona spawns you raised yourself.',
  c: 'Their prompts improve on their own — but every change passes a held-out exam,',
  d: 'and nothing ships until you press Promote.',
} as const;

/* ------------------------------------------------------------------ */
/* Spawns — NOT a fixed roster                                         */

export const SPAWNS = {
  /**
   * The correction that started this pass. README: "behind it you build a
   * roster of specialist spawns". They are drafted from a persona seed library
   * (`server/services/persona_seed_service.py`) and the router can itself
   * return `suggest_create` for work nothing on the roster covers
   * (`server/orchestrator/router.py`). There is no shipped set of six — the
   * six in the README is six languages and six theme palettes.
   */
  howMany: 'as many as you raise',
  equip: 'tools · SKILL.md skill packs · MCP servers',
  /**
   * The CREATE dialog offers a searchable persona-seed library to draft from.
   * `server/services/persona_seed_service.py` IMPORTS those seeds from the
   * agency-agents repository at runtime, so the count on screen is whatever a
   * given install has pulled — it is not a shipped constant. F6 shows the
   * dialog, seed count and all, because a screenshot of the real client is
   * allowed to show one machine's state; no caption anywhere may quote the
   * number as if the product shipped with it.
   */
  seeds: 'drafted from a persona seed library, imported not bundled',
  /** ARCHITECTURE.md: the router's bias. */
  doerFirst: 'if Arslan can do it itself, it does — routing is not the default',
} as const;

/* ------------------------------------------------------------------ */
/* The promotion gate — a paired win-rate gate, not a scorecard        */

export const GATE = {
  /** server/services/replay_gate.py → DIMENSIONS. */
  dimensions: ['fabrication', 'identity', 'completion'] as const,
  /** replay_gate.py → MIN_HOLDOUT_N. */
  minHoldout: 10,
  /** replay_gate.py → WIN_RATE_MIN. */
  winRate: 0.6,
  /** replay_gate.py module docstring. */
  method: 'both prompts replayed on the same tasks, judged with the positions swapped',
  /**
   * The single most under-sold thing in the codebase. Asking for a user-facing
   * win-rate from the propose split raises `HoldoutViolation` — replay_gate.py
   * says "enforced in code, not merely by convention".
   */
  holdoutEnforced: 'holdout is enforced in code, not by convention',
  /** replay_gate.py: real and synthetic deltas are never merged into one number. */
  neverMerged: 'real and synthetic win-rates are never merged into one number',
  /** replay_gate.py → TIER_STRONG_P / TIER_MEDIUM_P on the holdout p-value. */
  evidence: 'evidence graded on the holdout p-value',
  /** replay_gate.py → LENGTH_MULT 1.25 + HEADROOM_CHARS 2000. */
  lengthGuard: 'a candidate cannot win by getting longer',
  /** README: "No dimension is allowed to score worse than the incumbent." */
  noRegression: 'no dimension may score worse than the incumbent',
  /** README: fail is discarded and never surfaces; you never see it. */
  onFail: 'discarded — you never see it',
  onPass: 'a readable diff, in your inbox, until you press Promote',
} as const;

/* ------------------------------------------------------------------ */
/* The promise guard — the most visceral thing here                    */

export const PROMISE_GUARD = {
  /**
   * server/orchestrator/promise_guard.py. Its docstring records the live
   * incident verbatim: the router said route→spawn, the doer-first gate
   * diverted, and the answer LLM fabricated a handoff that never happened.
   * A second incident ran five turns claiming a handoff with zero dispatches.
   */
  lie: 'I have handed that to Deck Master — generating now, one moment.',
  truth: '0 dispatches. Nothing was handed to anything.',
  how: 'a deterministic interceptor, not another model call',
  bound: 'at most one re-synthesis; if that also promises, an honest template',
  claim: 'Arslan cannot tell you it did something it did not do.',
} as const;

/* ------------------------------------------------------------------ */
/* Safety                                                              */

export const SAFETY = {
  /** SECURITY.md: kernel-enforced seatbelt profile, network denied. */
  sandbox: 'generated code runs network-denied under the macOS kernel sandbox',
  /** SECURITY.md: the raw secret lives only in the parent process. */
  proxy: 'a local proxy injects git credentials — raw tokens never enter the sandbox',
  /** README + SECURITY.md, both emphatic. */
  failsClosed: 'no kernel sandbox available? it fails closed, not open',
  /** README: model-proposed deletes/overwrites land in an inbox. */
  memoryInbox: 'memory the model wants to delete goes to an inbox, never applies silently',
  /** README: your machine, your keys, zero third-party servers in the middle. */
  local: 'your machine · your keys · zero third-party servers in the middle',
  /**
   * System Settings → Automation, verbatim from the shipped page: "They are all
   * off by default and none of them changes anything without you", and for
   * background tidying, "Proposals land in the second brain's inbox for you to
   * accept or dismiss — nothing is written on its own". The same page warns, in
   * amber, that auto-evolution spends API credits and currently has no cap.
   * That a product ships the warning against itself is the claim; F6 closes on
   * the page rather than paraphrasing it.
   */
  automationOff: 'everything that can spend or write is off by default',
  /**
   * arslan/llm/catalog.py — thirteen provider keys: openai, deepseek, qwen,
   * kimi, zhipu, minimax, groq, together, mistral, openrouter, ollama,
   * anthropic, gemini. Registered here because `docs/assets/safety.jpg` bakes
   * the number into a raster, where no reader and no test can re-check it.
   */
  providers: 13,
} as const;

/* ------------------------------------------------------------------ */
/* Second brain                                                        */

export const BRAIN = {
  /** README: hybrid FTS5 + embedding retrieval. */
  retrieval: 'hybrid FTS5 + embedding retrieval',
  /** README: beliefs carry time — took effect, superseded. */
  time: 'every belief records when it took effect and what superseded it',
  scrub: 'scrub the graph back to any past instant',
  links: '[[wiki-link]] notes, as a force-directed graph',
} as const;

/* ------------------------------------------------------------------ */
/* The real client                                                     */

/** web/src/locales/en.json — sidebar.* and nav.*, so the UI in shot is real. */
export const NAV = [
  'New Orchestrator Session',
  'Spawns Ledger',
  'Active Spawns',
  'Second Brain',
  'Capabilities',
  'System Settings',
] as const;

/** README: ships with 6-language i18n and 6 theme palettes. */
export const SHIPS_WITH = '6 languages · 6 theme palettes · light + dark';

/**
 * Anything shown as a concrete value that is not measured. Every film that puts
 * one on screen has to label it, which is why this is a constant rather than a
 * habit.
 */
export const SAMPLE = 'illustrative — not measured';
