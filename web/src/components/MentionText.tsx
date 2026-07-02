import React from 'react';

/**
 * MentionText — renders text whose `@SpawnName` tokens (for KNOWN spawn names only)
 * become subtle accent-tinted inline chips. Unknown `@whatever` stays plain text:
 * mentions are grounded in the real roster, never guessed. No new deps — a tiny
 * regex tokenizer built from the known-name list (longest names first so
 * "@Deck Master" wins over a hypothetical "@Deck").
 */
function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function renderMentions(text: string, knownNames: string[]): React.ReactNode[] {
  const names = [...new Set(knownNames.filter(Boolean))].sort((a, b) => b.length - a.length);
  if (names.length === 0 || !text) return [text];
  const re = new RegExp(`@(${names.map(escapeRegExp).join('|')})`, 'g');
  const out: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(
      <span
        key={`mention-${key++}`}
        data-testid="mention-chip"
        className="inline-block align-baseline bg-primary/10 text-primary rounded px-1 font-semibold"
      >
        @{m[1]}
      </span>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function MentionText({
  text,
  knownNames,
  className,
}: {
  text: string;
  knownNames: string[];
  className?: string;
}) {
  return (
    <span className={className} style={{ whiteSpace: 'pre-line' }}>
      {renderMentions(text, knownNames)}
    </span>
  );
}
