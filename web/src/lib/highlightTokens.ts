/**
 * FMT1 (0.1.64): a fence's text and language name in, Prism's tokens out. Only highlight.worker.ts loads this,
 * so the window never runs a grammar (see highlightClient).
 * Prism, not Shiki: Shiki's regex grammars and a theme cost several times more to ship (numbers in the PR).
 */
import './prismManual';
import Prism from 'prismjs';
// Order matters: each language needs the ones before it (prismjs itself brings clike, markup, css, javascript).
import 'prismjs/components/prism-bash';
import 'prismjs/components/prism-c';
import 'prismjs/components/prism-cpp';
import 'prismjs/components/prism-diff';
import 'prismjs/components/prism-go';
import 'prismjs/components/prism-java';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-jsx';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-rust';
import 'prismjs/components/prism-sql';
import 'prismjs/components/prism-swift';
import 'prismjs/components/prism-toml';
import 'prismjs/components/prism-typescript';
import 'prismjs/components/prism-tsx';
import 'prismjs/components/prism-yaml';

/** null: show the fence as plain text. */
export type Tokens = Prism.TokenStream | null;

/** Names the models use that Prism does not define itself. */
const ALIASES: Record<string, string> = { zsh: 'bash', jsonc: 'json', rs: 'rust', golang: 'go', 'c++': 'cpp' };

/** Each token is a span the window has to render, however quickly the worker found it: 15,000 took 0.7 s on a busy Mac. */
const MAX_TOKENS = 10_000;

function count(list: Prism.TokenStream): number {
  if (typeof list === 'string') return 0;
  if (Array.isArray(list)) return list.reduce((n, piece) => n + count(piece), 0);
  return 1 + count(list.content);
}

export function tokenize(code: string, lang: string): Tokens {
  // The language name comes from the model, so it is only ever a key into Prism's table. A name with no grammar
  // (or one of Prism's own helpers, such as `extend`, or `__proto__`) shows plain text; the tests pin that.
  const language = ALIASES[lang] ?? lang;
  const grammar = Prism.languages[language];
  if (!grammar) return null;
  // What Prism.highlight does around tokenize; JSX's hook (it fixes the text between tags) lives in after-tokenize.
  const env = { code, grammar, language, tokens: Prism.tokenize(code, grammar) };
  Prism.hooks.run('after-tokenize', env);
  return count(env.tokens) > MAX_TOKENS ? null : env.tokens;
}
