import type { FallbackReason, PermissionMode } from "../../api/permissionMode";

/** S5a: the four modes in the demo's order, each with its dot and i18n keys. The pill, the strip and Settings read
 *  this one table. */
export const MODES: { mode: PermissionMode; name: string; line: string; dot: string }[] = [
  { mode: "ask_risky", name: "modes.askRisky", line: "modes.askRiskyLine", dot: "bg-success" },
  { mode: "ask", name: "modes.ask", line: "modes.askLine", dot: "bg-primary" },
  { mode: "plan", name: "modes.plan", line: "modes.planLine", dot: "bg-subtle-foreground" },
  { mode: "full_access", name: "modes.fullAccess", line: "modes.fullAccessLine", dot: "bg-warning" },
];

export const modeInfo = (mode: PermissionMode) => MODES.find((m) => m.mode === mode) ?? MODES[1];

export const REASON: Record<Exclude<FallbackReason, "">, string> = {
  sandbox_off: "modes.reasonSandboxOff",
  home_folder: "modes.reasonHomeFolder",
  no_checkpoint: "modes.reasonNoCheckpoint",
};

/** A mode as the server sent it; anything else is "ask", the strict one (the server's own rule). */
export function asMode(value: unknown): PermissionMode {
  return MODES.some((m) => m.mode === value) ? value as PermissionMode : "ask";
}
