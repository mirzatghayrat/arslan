/**
 * Whether the selected provider can call tools at all.
 *
 * WHAT IS ACTUALLY BROKEN, measured rather than assumed: both production paths
 * — Arslan's answer path (server/orchestrator/arslan.py) and the spawn path
 * (server/orchestrator/spawn_loop.py) — go through `tool_loop.run_native`,
 * which passes tool schemas to the adapter. `openai_provider` serializes them
 * (`if tools: payload["tools"] = tools`), and since G1 the Anthropic adapter
 * does too (`_translate_tools` -> tools[].input_schema, `tool_use` parsed back).
 * The GEMINI adapter still accepts the argument and never puts it on the wire.
 * So on that one, every equipped tool and every MCP tool is inert, the model is
 * never told the tool exists, and nothing anywhere says so.
 *
 * This comment said "the Anthropic and Gemini adapters" until G1 landed. It is
 * updated here in the same change as the verdict, because a stale explanation
 * outlives the table it explains: someone debugging a live Anthropic tool call
 * would read this and go looking for a bug that was fixed.
 *
 * WHY THIS TABLE IS DUPLICATED IN THE FRONTEND rather than fetched:
 * server/services/capability_fitness.py already publishes the same verdict on
 * the registry endpoint. But a warning that arrives over the network is a
 * warning that disappears when the network doesn't — offline, still booting,
 * 401 — and the whole point here is that a silent degradation is the bug. A
 * safety notice must not fail open. So the state is known locally and instantly,
 * and `tool-transport-agrees-with-backend.test.ts` parses the Python table and
 * fails if the two ever disagree.
 *
 * WHAT THIS DOES NOT CLAIM: skills are not affected by transport. Equipped
 * skills never enter `_native_tool_schemas` (tool_loop.py builds it purely from
 * resolve_tools()' wired tools), so they are not carried by the mechanism that
 * is broken here. A skill whose STEPS depend on calling a tool still cannot
 * complete — which the warning says — but "skills do not work" would be
 * overstating, and overstating in the cautious direction is still saying
 * something untrue.
 */

export type ToolTransport = "supported" | "unsupported" | "unverified";

/**
 * Keys are the provider identifiers used by the model catalog, lower-cased.
 *
 * Must stay identical to `NATIVE_TOOL_CALLS` in
 * server/services/capability_fitness.py. A provider missing from both is
 * `unverified` — deliberately not "probably fine", because assuming an
 * unmeasured path worked is the exact mistake this whole area exists to correct.
 */
export const TOOL_TRANSPORT: Readonly<Record<string, ToolTransport>> = {
  openai: "supported",
  custom: "supported", // OpenAI-compatible endpoints use the same payload
  ollama: "supported", // ditto
  deepseek: "supported", // ditto
  // G1 (2026-08-01): the Anthropic adapter now builds a real `tools` payload —
  // `_translate_tools` emits tools[].input_schema and `tool_use` blocks are parsed
  // back. Flipped here in the same change as the Python table, because these two
  // disagreeing is a warning that contradicts the app it is warning about.
  anthropic: "supported",
  gemini: "unsupported", // arslan/llm/providers/gemini_provider.py builds no `tools`
  // Tier-0 presets: the dropdown stores the PRESET KEY, and expand_preset maps
  // every one of these to provider "openai", so tools are sent. Omitting them
  // made the notice claim "nobody has measured this" on eight of the eleven
  // dropdown options — untrue, and untrue in the cautious direction is still
  // untrue.
  qwen: "supported",
  kimi: "supported",
  zhipu: "supported",
  minimax: "supported",
  groq: "supported",
  together: "supported",
  mistral: "supported",
  openrouter: "supported",
};

/** Tool-transport verdict for a provider id. Unknown or empty ⇒ `unverified`. */
export function toolTransportState(provider: string | null | undefined): ToolTransport {
  if (!provider) return "unverified";
  return TOOL_TRANSPORT[provider.trim().toLowerCase()] ?? "unverified";
}

/**
 * True when the user needs to be told something about this provider.
 *
 * Both non-supported states qualify. `unverified` gets a quieter notice rather
 * than nothing: rendering an unmeasured provider exactly like a measured-good
 * one is how "equipped" came to mean "will run" in the first place.
 */
export function needsToolTransportNotice(provider: string | null | undefined): boolean {
  return toolTransportState(provider) !== "supported";
}
