import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import { uiMessages } from "../locales/ui";
import { connectionMessages } from "../locales/connections";

const sourceRoot = path.resolve(import.meta.dirname, "..");
function sources(directory: string): string[] {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    if (entry.name === "__tests__") return [];
    const filename = path.join(directory, entry.name);
    return entry.isDirectory() ? sources(filename)
      : /\.tsx?$/.test(filename) && !/\.test\./.test(filename) ? [filename] : [];
  });
}
function parse(filename: string) {
  return ts.createSourceFile(filename, fs.readFileSync(filename, "utf8"), ts.ScriptTarget.Latest, true,
    filename.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
}

// Brand names, wire formats, metric units and literal command/URL examples are
// not translated. This list does NOT exempt ordinary product sentences.
const LITERAL_EXCEPTIONS = new Set([
  "Arslan", "App Store Connect", "iOS", "macOS", "tvOS", "visionOS", "OAuth",
  ".pptx", ".html", "tok", "stdio", "http", "npx", "my-method",
  "-y @scope/server", "https://example.com", "https://…/mcp", "http://192.168.1.10:8080",
]);

describe("product language guards", () => {
  it("resolves every statically named product translation in all six languages", () => {
    const missing: string[] = [];
    for (const filename of sources(sourceRoot)) {
      const source = parse(filename);
      function visit(node: ts.Node) {
        if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) &&
          ["t", "tr"].includes(node.expression.text) && node.arguments[0] &&
          ts.isStringLiteral(node.arguments[0])) {
          const key = node.arguments[0].text;
          for (const language of SUPPORTED_LANGUAGES) {
            // Read that language directly: fallbackLng must not mask missing keys.
            const value = i18n.getResource(language, "translation", key) ??
              i18n.getResource(language, "translation", key + "_other");
            if (typeof value !== "string" || !value.trim()) {
              const line = source.getLineAndCharacterOfPosition(node.getStart()).line + 1;
              missing.push(language + " " + path.relative(sourceRoot, filename) + ":" + line + " " + key);
            }
          }
        }
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
    expect(missing).toEqual([]);
  });

  it("does not reintroduce hardcoded English JSX copy or accessible labels", () => {
    const raw: string[] = [];
    for (const filename of sources(sourceRoot)) {
      const source = parse(filename);
      function visit(node: ts.Node) {
        let text: string | undefined;
        if (ts.isJsxText(node)) text = node.text.trim().replace(/\s+/g, " ");
        if (ts.isJsxAttribute(node) && ["title", "aria-label", "placeholder", "alt"].includes(node.name.getText(source)) &&
          node.initializer && ts.isStringLiteral(node.initializer)) text = node.initializer.text;
        if (text && /[A-Za-z]{3}/.test(text) && !LITERAL_EXCEPTIONS.has(text)) {
          raw.push(path.relative(sourceRoot, filename) + ": " + text);
        }
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
    expect(raw).toEqual([]);
  });

  it("preserves interpolation and nonempty values in new UI dictionaries", () => {
    for (const dictionary of [uiMessages, connectionMessages]) {
      const english = dictionary.en as Record<string, string>;
      for (const language of SUPPORTED_LANGUAGES) {
        const messages = dictionary[language] as Record<string, string>;
        expect(Object.keys(messages).sort()).toEqual(Object.keys(english).sort());
        for (const key of Object.keys(english)) {
          expect(messages[key].trim()).not.toBe("");
          expect(messages[key].match(/\{\{[^}]+\}\}/g)?.sort() ?? [])
            .toEqual(english[key].match(/\{\{[^}]+\}\}/g)?.sort() ?? []);
        }
      }
    }
  });
});
