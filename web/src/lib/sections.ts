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
  "spawn",
  "ledger",
  "capabilities",
  "brain",
  "diagnosis",
  "settings",
] as const;

export type Section = (typeof SECTIONS)[number];
