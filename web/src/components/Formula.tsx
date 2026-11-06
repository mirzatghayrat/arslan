/**
 * FMT1 PR 2 (0.1.64): one formula, typeset by KaTeX into nodes it builds itself, so a reply's text never becomes an HTML
 * string here, and only when its text changes, so a finished formula costs nothing while a reply streams. KaTeX and its
 * stylesheet are their own chunk, loaded by the first formula.
 *
 * It shows its source as plain text until KaTeX is here, and when KaTeX can't typeset it: half-streamed TeX isn't an error
 * worth a flash of red. KaTeX runs on the main thread and can't be stopped, so a reply's text reaches it under three limits:
 * no macro definitions, a size cap for one formula (the worst that fits took about 0.4 s, measured in WKWebView), and a budget
 * for many of them (25 of those would freeze the window for 10 s). An ordinary formula takes 1 to 3 ms and never counts against
 * the budget.
 *
 * Definitions, because each call of a macro counts as one expansion however long its body, so maxExpand never trips: 1.8 kB took
 * 100 s, which no budget can stop, and a reload would do again from the stored reply. \\longrightarrow isn't one of them.
 */
import type Katex from 'katex';
import React from 'react';

const DEFINES_MACROS = /\\(?:[gex]?def|let|futurelet|(?:re)?newcommand|providecommand|global|long)(?![a-zA-Z])/;
const MAX_CHARS = 4096;
const SLOW_MS = 50;
const SLOW_BUDGET_MS = 1000;
let slowSoFar = 0;

let katex: typeof Katex | null = null;
let loading: Promise<void> | null = null;

function load() {
  // A chunk that won't load leaves the source showing, which is all a reply can do about it. copy-tex: selecting a formula copies its TeX.
  loading ??= Promise.all([import('katex'), import('katex/dist/katex.min.css'), import('katex/contrib/copy-tex')])
    .then(([module]) => { katex = module.default; }, () => {});
  return loading;
}

export default function Formula({ tex, display = false }: { tex: string; display?: boolean }) {
  const box = React.useRef<HTMLSpanElement>(null);
  const [ready, setReady] = React.useState(katex !== null);
  React.useEffect(() => { if (!ready) void load().then(() => setReady(true)); }, [ready]);
  React.useLayoutEffect(() => {
    const element = box.current!;
    element.textContent = tex;
    if (!katex || tex.length > MAX_CHARS || DEFINES_MACROS.test(tex) || slowSoFar >= SLOW_BUDGET_MS) return;
    const started = performance.now();
    try {
      // trust: no \href or \includegraphics. errorColor: what trust refuses isn't an alarm. .md-root clips what a formula moves or
      // widens; maxSize is for height, which stays in flow, where one \rule pushes the chat after it 33 million pixels away (measured).
      katex.render(tex, element, { displayMode: display, throwOnError: true, trust: false, strict: 'ignore', maxSize: 50, errorColor: 'currentColor' });
    } catch {
      element.textContent = tex;
    }
    const took = performance.now() - started;
    if (took >= SLOW_MS) slowSoFar += took;
  }, [tex, display, ready]);
  return <span ref={box} className={display ? 'md-math md-math-display' : 'md-math'} />;
}
