import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { request } from '../../api/client';

type Rule = { rule: string; description: string };

/**
 * The kinds of command the user ticked "don't ask again" for (0.1.48). A
 * standing permission nobody can see is one nobody can take back, so every
 * remembered rule is listed here with a way to undo it.
 */
export default function TerminalRulesPanel() {
  const { t } = useTranslation();
  const [rules, setRules] = useState<Rule[] | null>(null);

  useEffect(() => {
    let alive = true;
    request<{ rules: Rule[] }>('/settings/terminal-rules')
      .then((r) => { if (alive) setRules(r.rules); })
      .catch(() => { if (alive) setRules([]); });
    return () => { alive = false; };
  }, []);

  const forget = async (rule: string) => {
    const r = await request<{ rules: Rule[] }>(
      `/settings/terminal-rules?rule=${encodeURIComponent(rule)}`, { method: 'DELETE' });
    setRules(r.rules);
  };

  if (rules == null) return null;
  return (
    <div className="pl-4 border-l-2 border-primary/20 space-y-1.5" data-testid="terminal-rules">
      <h4 className="text-xs font-bold text-foreground font-sans">{t('settings.terminalRulesTitle')}</h4>
      {rules.length === 0 ? (
        <p className="text-[11px] text-muted-foreground font-sans">{t('settings.terminalRulesEmpty')}</p>
      ) : (
        <ul className="space-y-1">
          {rules.map((r) => (
            <li key={r.rule} className="flex items-center justify-between gap-3 text-[12px]">
              <span className="text-foreground">{r.description}</span>
              <button type="button" data-testid={`terminal-rule-forget-${r.rule}`} onClick={() => void forget(r.rule)}
                className="shrink-0 rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground">
                {t('settings.terminalRulesForget')}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
