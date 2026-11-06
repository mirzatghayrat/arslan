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
const ALIASES: Record<string, string> = { zsh: 'bash', jsonc: 'json' };

/**
 * The language name comes from the model, so it is only ever a key into Prism's table. A name with no grammar
 * (or one of Prism's own helpers, such as `extend`, or `__proto__`) tokenizes to plain text; the tests pin that.
 */
function grammarFor(lang: string): Prism.Grammar | undefined {
  const name = lang.toLowerCase();
  return Prism.languages[ALIASES[name] ?? name];
}

function pieces(list: Prism.TokenStream): React.ReactNode {
  if (typeof list === 'string') return list;
  if (Array.isArray(list)) return list.map((piece, i) => <React.Fragment key={i}>{pieces(piece)}</React.Fragment>);
  const alias = list.alias ? ` ${[list.alias].flat().join(' ')}` : '';
  return <span className={`token ${list.type}${alias}`}>{pieces(list.content)}</span>;
}

export default function HighlightedCode({ code, lang, className }: { code: string; lang: string; className?: string }) {
  const grammar = grammarFor(lang);
  return <code className={className}>{grammar ? pieces(Prism.tokenize(code, grammar)) : code}</code>;
}
