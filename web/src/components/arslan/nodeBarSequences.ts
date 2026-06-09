// Node on/off patterns ported verbatim from make_arslan_node_bar_gif.py.
// "on" = active (filled ●), "o" = inactive (hollow o). Each frame is [left, hub, right].

export type NodeState = "thinking" | "routing" | "spawn_working" | "waiting_confirmation" | "done";
export type NodeCell = "on" | "o";
export type NodePattern = [NodeCell, NodeCell, NodeCell];

export const NODE_SEQUENCES: Record<NodeState, NodePattern[]> = {
  thinking: [
    ["o", "on", "o"],
    ["o", "o", "o"],
    ["o", "on", "o"],
    ["on", "on", "on"],
    ["o", "on", "o"],
    ["on", "on", "on"],
  ],
  routing: [
    ["on", "on", "o"],
    ["o", "on", "o"],
    ["o", "on", "on"],
    ["o", "on", "o"],
    ["on", "on", "on"],
    ["o", "on", "o"],
  ],
  spawn_working: [
    ["o", "on", "on"],
    ["on", "on", "o"],
    ["o", "on", "on"],
    ["on", "on", "on"],
    ["on", "on", "o"],
    ["o", "on", "o"],
  ],
  waiting_confirmation: [
    ["on", "on", "on"],
    ["on", "o", "on"],
    ["on", "on", "on"],
    ["o", "on", "o"],
  ],
  done: [["on", "on", "on"]],
};

/** Returns the [left, hub, right] pattern for a state at a given frame index (wraps modulo length). */
export function patternFor(state: NodeState, frame: number): NodePattern {
  const seq = NODE_SEQUENCES[state];
  return seq[((frame % seq.length) + seq.length) % seq.length];
}

/** Number of distinct frames for a state (1 for the static `done`). */
export function frameCount(state: NodeState): number {
  return NODE_SEQUENCES[state].length;
}
