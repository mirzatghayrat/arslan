/**
 * What an AppleScript CHANGES, read from the code itself (0.1.55, user decision 1).
 *
 * The card's summary is the model's own words ("Arslan 说：…") and never decides
 * safety; this line is derived from the script text. It is a display aid, not a
 * permission check: every script is still asked, every time. Strings and comments
 * are blanked first, so a note NAMED "delete me" does not count as deleting.
 */
export type ScriptEffect = "delete" | "move" | "send" | "shell" | "create" | "save" | "modify" | "quit";

export interface ScriptRisk {
  effects: ScriptEffect[];
  /** 1-based line numbers of the matches, in order. */
  lines: number[];
  /** The words that matched, as written in the script. */
  words: string[];
  /** The script uses something this reader cannot see through (run script, raw events, JavaScript). */
  unknown: boolean;
}

const RULES: { effect: ScriptEffect; re: RegExp }[] = [
  { effect: "shell", re: /\bdo\s+shell\s+script\b/i },
  { effect: "delete", re: /\bdelete\b/i },
  { effect: "send", re: /\bsend\b/i },
  { effect: "move", re: /\bmove\b/i },
  { effect: "create", re: /\bmake\s+new\b|\bduplicate\b/i },
  { effect: "save", re: /\bsave\b/i },
  { effect: "quit", re: /\bquit\b/i },
  { effect: "modify", re: /\bset\s+(?:the\s+)?(?:body|name|text|content|subject|contents|title|completed|due date|value)\b[^\n]*\bto\b/i },
];
const OPAQUE = /\brun\s+script\b|«event|\bstore\s+script\b|\bload\s+script\b|-l\s+JavaScript/i;

/** Blank string literals and comments, keeping line breaks so line numbers stay true. */
export function blankLiterals(code: string): string {
  let out = "";
  let i = 0;
  while (i < code.length) {
    const two = code.slice(i, i + 2);
    if (two === "(*") {
      const end = code.indexOf("*)", i + 2);
      const stop = end < 0 ? code.length : end + 2;
      out += code.slice(i, stop).replace(/[^\n]/g, " ");
      i = stop;
    } else if (two === "--" || code[i] === "#") {
      const end = code.indexOf("\n", i);
      const stop = end < 0 ? code.length : end;
      out += " ".repeat(stop - i);
      i = stop;
    } else if (code[i] === '"') {
      let j = i + 1;
      while (j < code.length && code[j] !== '"') j += code[j] === "\\" ? 2 : 1;
      const stop = Math.min(code.length, j + 1);
      out += code.slice(i, stop).replace(/[^\n]/g, " ");
      i = stop;
    } else {
      out += code[i];
      i += 1;
    }
  }
  return out;
}

export function appleScriptRisk(code: string): ScriptRisk | null {
  const bare = blankLiterals(code || "");
  const effects: ScriptEffect[] = [];
  const lines: number[] = [];
  const words: string[] = [];
  bare.split("\n").forEach((line, n) => {
    for (const { effect, re } of RULES) {
      const m = line.match(re);
      if (!m) continue;
      if (!effects.includes(effect)) effects.push(effect);
      if (!lines.includes(n + 1)) lines.push(n + 1);
      const word = m[0].split(/\s+/).slice(0, effect === "modify" ? 2 : 3).join(" ");
      if (!words.includes(word)) words.push(word);
    }
  });
  const unknown = OPAQUE.test(bare);
  return effects.length || unknown ? { effects, lines, words, unknown } : null;
}
