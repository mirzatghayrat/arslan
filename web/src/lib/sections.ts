/**
 * The pages the app can show, in one place.
 *
 * This exists because the union was written out by hand in three files and the
 * header renders `t(\`nav.${activeSection}\`)` — so a section id and a locale key
 * had to agree, and nothing checked that they did. They did not: `nav` held
 * dashboard/spawns/secondBrain/settings while the sections are
 * arslan/spawn/ledger/capabilities/brain/diagnosis/settings, and six of the
 * seven page headers rendered the raw key. In every language. It shipped.
 *
 * Deriving the locale test from THIS list is the actual fix; adding the six
 * missing strings only clears today's instance.
 */
export const SECTIONS = [
  "arslan",
  "inbox",
  "projects",
  "capabilities",
  "brain",
  "activity",
  "settings",
] as const;

export type Section = (typeof SECTIONS)[number];

/** 0.1.55: any component can ask the app to show a page (e.g. "Review in Memory"). */
export const OPEN_SECTION_EVENT = "arslan:open-section";

export function openSection(section: Section, sub?: string): void {
  // `sub` picks a part of the page (a Settings section such as "memory").
  window.dispatchEvent(new CustomEvent(OPEN_SECTION_EVENT, { detail: sub ? { section, sub } : section }));
}

/** What an OPEN_SECTION_EVENT asks for: a known page, and optionally a part of it. */
export function readOpenSection(detail: unknown): { section: Section; sub?: string } | null {
  const section = typeof detail === "string" ? detail
    : detail && typeof detail === "object" ? (detail as { section?: unknown }).section : undefined;
  if (typeof section !== "string" || !(SECTIONS as readonly string[]).includes(section)) return null;
  const sub = detail && typeof detail === "object" ? (detail as { sub?: unknown }).sub : undefined;
  return typeof sub === "string" && sub ? { section: section as Section, sub } : { section: section as Section };
}
