/**
 * FMT1 (0.1.64): a fenced code block, coloured from the tokens the highlight worker sends back, with React's own text
 * nodes. Nothing here builds an HTML string, so code that looks like markup can never become markup.
 * It is plain text until the answer is in, so the code can be read at once and stays whole if no answer ever comes.
 */
import type Prism from 'prismjs';
import React from 'react';
import { answerFor, ask } from '../lib/highlightClient';

function pieces(list: Prism.TokenStream): React.ReactNode {
  if (typeof list === 'string') return list;
  if (Array.isArray(list)) return list.map((piece, i) => <React.Fragment key={i}>{pieces(piece)}</React.Fragment>);
  const alias = list.alias ? ` ${[list.alias].flat().join(' ')}` : '';
  return <span className={`token ${list.type}${alias}`}>{pieces(list.content)}</span>;
}

export default React.memo(function HighlightedCode({ code, lang, className }: { code: string; lang: string; className?: string }) {
  const name = lang.toLowerCase();
  const answer = answerFor(code, name);
  // While a reply streams, the last answer covers all but the newest characters. Colours that went away with every
  // token would flicker, so it stays up, with the rest as plain text, until the next answer.
  const [last, setLast] = React.useState<{ code: string; tokens: Prism.TokenStream } | null>(null);
  React.useEffect(() => {
    if (answerFor(code, name) !== undefined) return undefined;
    return ask(code, name, () => {
      const tokens = answerFor(code, name);
      setLast(tokens ? { code, tokens } : null);
    });
  }, [code, name]);
  if (answer) return <code className={className}>{pieces(answer)}</code>;
  if (last && code.startsWith(last.code)) {
    return <code className={className}>{pieces(last.tokens)}{code.slice(last.code.length)}</code>;
  }
  return <code className={className}>{code}</code>;
});
