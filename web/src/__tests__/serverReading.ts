// LOOP1 d1: the server's reading of a command (card_purpose.summarize, the frame's `summary`), as the card tests give
// it to a card. Taken from the shared vectors, which tests/server/test_smart8_plain_title.py holds the server to, so a
// card test never states a reading the server does not make. A line not in them is a test bug: add it to the vectors.
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { CommandSummary } from "../lib/commandRisk";

const VECTORS: ({ line: string } & CommandSummary)[] = JSON.parse(readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), "../../../tests/fixtures/card_purpose_vectors.json"), "utf8")).vectors;

export function serverSummary(line: string): CommandSummary {
  const v = VECTORS.find(x => x.line === line);
  if (!v) throw new Error(`no shared vector for ${JSON.stringify(line)}`);
  return { purpose: v.purpose, touches: v.touches, more: v.more, unsure: v.unsure };
}
