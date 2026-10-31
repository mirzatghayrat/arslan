import { request } from "./client";

// ── P3: faithful SKILL.md importer (verbatim; license-gated server-side) ─────────
// scan+import bring standard Agent-Skills SKILL.md files in VERBATIM, with bundled
// scripts/*.py stored for the sandbox. The rest of the discovery centre (search, evaluate,
// saved candidates, skill drafts) went in v0.1.64 CAP1a.

export type ScannedSkill = {
  path: string;
  key?: string;
  name?: string;
  description?: string;
  body_bytes?: number;
  /** UNI1b: how many characters of its text show nothing, and the first runs' labels (shown, never blocking). */
  hidden?: { count: number; runs: string[] };
  scripts: string[];
  importable: boolean;
  reason: string | null;
};

export type SkillScanResult = {
  repo: { full_name: string; html_url: string; license: string | null; stars: number };
  license_ok: boolean;
  license_note: string | null;
  skills: ScannedSkill[];
  /** CAP4a-1: the commit the listing was read at; the import pins to it. */
  commit?: string;
};

export type ImportedSkill = {
  key: string; name: string; description: string; scripts: string[]; license: string | null;
};

export const scanSkills = (ref: string, subpath = "") =>
  request<SkillScanResult>("/discovery/skills/scan", {
    method: "POST", body: JSON.stringify({ ref, subpath }),
  });

export const importSkill = (ref: string, path: string) =>
  request<ImportedSkill>("/discovery/skills/import", {
    method: "POST", body: JSON.stringify({ ref, path }),
  });
