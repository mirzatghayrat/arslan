/**
 * OcrLanguagePicker — which languages the system recogniser should look for.
 *
 * A BOUNDED picker over what THIS machine can do, and both halves of that are
 * deliberate:
 *
 *  - the options come from the host at request time, never from a list in this
 *    file. The set grows with the OS version, so a baked-in list would offer
 *    the user languages their system cannot read.
 *
 *  - there is a ceiling, because recognition gets WORSE as the request widens
 *    and CJK is the first thing lost. Measured: a mixed Chinese/English image
 *    returns both lines for (zh-Hans, en-US) and only the English one when all
 *    thirty supported languages are asked for; Japanese disappears entirely.
 *    Without the cap this control would let someone destroy the capability
 *    they were trying to improve, which is the opposite of what a settings
 *    screen is for.
 *
 * Unset is a real state, not a placeholder: it means "follow the interface
 * language, plus English", which is what most people want and what the app did
 * before this control existed.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api } from '../../api/client';

interface Props {
  /** Comma-separated BCP-47 tags; '' means follow the interface language. */
  value: string;
  onChange: (next: string) => void;
}

interface HostLanguages {
  available: string[];
  max_selectable: number;
  platform_supported: boolean;
}


/**
 * The selection rule, as a pure function.
 *
 * Separate from the button's `disabled` attribute on purpose: that attribute
 * is an AFFORDANCE (it tells you not to), this is the INVARIANT (it makes sure
 * you cannot). Mutation showed why both are needed — with the rule inlined in
 * the click handler, removing the cap from it changed nothing observable,
 * because the disabled button meant no test could ever reach the code.
 *
 * Turning a selected language OFF is always allowed, even at the cap;
 * otherwise the ceiling becomes a trap with no way back out.
 */
export function nextSelection(selected: string[], tag: string, max: number): string[] {
  if (selected.includes(tag)) return selected.filter((s) => s !== tag);
  if (selected.length >= max) return selected;
  return [...selected, tag];
}

export default function OcrLanguagePicker({ value, onChange }: Props) {
  const { t } = useTranslation();
  const [host, setHost] = useState<HostLanguages | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    // Wrapped so a SYNCHRONOUS failure (an old client, a stubbed api in a
    // test, a method that simply is not there) degrades to the honest
    // "no recognition here" state instead of throwing during render and
    // taking the whole Settings screen down with it. One endpoint being
    // unavailable must not cost the user every other setting on the page.
    Promise.resolve()
      .then(() => api.listOcrLanguages())
      .then((h) => { if (alive) setHost(h); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, []);

  const selected = value.split(',').map((s) => s.trim()).filter(Boolean);

  // A host that cannot recognise anything is told plainly rather than shown an
  // empty list of choices — the reverse-honesty rule: say the capability is
  // absent instead of presenting controls that would do nothing.
  if (failed || (host && !host.platform_supported)) {
    return (
      <div className="space-y-2" data-testid="ocr-languages">
        <p className="text-[10px] text-subtle-foreground font-sans leading-relaxed">
          {t('settings.ocrLanguagesUnavailable')}
        </p>
      </div>
    );
  }

  if (!host) return null;

  const atCap = selected.length >= host.max_selectable;

  const toggle = (tag: string) => onChange(
    nextSelection(selected, tag, host.max_selectable).join(','));

  return (
    /* Collapsed by default: the chip grid is the tallest thing on this page and
       most people set it once. `<details>` rather than a popover on purpose —
       it is a long multi-select list, so it needs to push layout rather than
       float over it, and it stays keyboard- and screen-reader-native for free. */
    <details className="space-y-2 group" data-testid="ocr-languages">
      <summary className="flex items-center justify-between cursor-pointer list-none">
        <span className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide">
          {t('settings.ocrLanguagesLabel')}
        </span>
        <span className="text-[10px] font-mono text-subtle-foreground">
          {/* The count is the whole point of collapsing: you can tell what is
              set without opening it. */}
          {selected.length
            ? selected.join(', ')
            : t('settings.ocrLanguagesFollowsUi')}
          <span className="ml-1.5 inline-block transition-transform group-open:rotate-90">›</span>
        </span>
      </summary>
      <div className="flex flex-wrap gap-1.5 pt-2">
        {host.available.map((tag) => {
          const on = selected.includes(tag);
          const blocked = !on && atCap;
          return (
            <button
              key={tag}
              type="button"
              aria-pressed={on}
              disabled={blocked}
              onClick={() => toggle(tag)}
              className={`px-2 py-1 rounded-md text-[10px] font-mono border transition-colors ${
                on
                  ? 'bg-primary/15 border-primary/40 text-foreground'
                  : blocked
                    ? 'border-border text-subtle-foreground opacity-40 cursor-not-allowed'
                    : 'border-border text-muted-foreground hover:text-foreground hover:border-border-strong'
              }`}
            >
              {tag}
            </button>
          );
        })}
      </div>
      {/* The "follows your interface language" line moved to the SUMMARY, where
          it is visible while collapsed — which is when a user needs to know the
          state. Rendering it here too put the same sentence on screen twice. */}
      {selected.length > 0 && (
        <p className="text-[10px] text-subtle-foreground font-sans leading-relaxed">
          {t('settings.ocrLanguagesCapHint', { max: host.max_selectable })}
        </p>
      )}
    </details>
  );
}
