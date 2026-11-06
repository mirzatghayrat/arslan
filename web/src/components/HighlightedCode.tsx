/**
 * FMT1 (0.1.64): syntax highlighting for a fenced code block, with Prism's tokenizer and React's own text nodes.
 * Nothing here builds an HTML string, so code that looks like markup can never become markup.
 * Prism, not Shiki: Shiki's regex grammars and a theme cost several times more to ship (numbers in the PR).
 */
import '../lib/prismManual';
import React from 'react';
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

/** Names the models use that Prism does not define itself. */
const ALIASES: Record<string, string> = { zsh: 'bash', jsonc: 'json', rs: 'rust', golang: 'go', 'c++': 'cpp' };

/**
 * Prism's grammars backtrack: some inputs of a few kB take tens of seconds, and a reply can carry text from outside
 * content, so one fence could freeze the window. Two bounds, neither exact (a worker that can be terminated is the
 * exact one, left for PR 3 if the frame-time measurement asks for it):
 * - a fence over 8 KiB is shown as plain text;
 * - once any tokenize takes over 200 ms, nothing is highlighted for the rest of this window's session.
 */
const MAX_CHARS = 8 * 1024;
const SLOW_MS = 200;
let tooSlow = false;

function pieces(list: Prism.TokenStream): React.ReactNode {
  if (typeof list === 'string') return list;
  if (Array.isArray(list)) return list.map((piece, i) => <React.Fragment key={i}>{pieces(piece)}</React.Fragment>);
  const alias = list.alias ? ` ${[list.alias].flat().join(' ')}` : '';
  return <span className={`token ${list.type}${alias}`}>{pieces(list.content)}</span>;
}

export default function HighlightedCode({ code, lang, className }: { code: string; lang: string; className?: string }) {
  // The language name comes from the model, so it is only ever a key into Prism's table. A name with no grammar
  // (or one of Prism's own helpers, such as `extend`, or `__proto__`) shows plain text; the tests pin that.
  const name = lang.toLowerCase();
  const language = ALIASES[name] ?? name;
  const grammar = tooSlow || code.length > MAX_CHARS ? undefined : Prism.languages[language];
  if (!grammar) return <code className={className}>{code}</code>;
  const started = performance.now();
  // What Prism.highlight does around tokenize; JSX's hook (it fixes the text between tags) lives in after-tokenize.
  const env = { code, grammar, language, tokens: Prism.tokenize(code, grammar) };
  Prism.hooks.run('after-tokenize', env);
  if (performance.now() - started > SLOW_MS) tooSlow = true;
  return <code className={className}>{pieces(env.tokens)}</code>;
}
