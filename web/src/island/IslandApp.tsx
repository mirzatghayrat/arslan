import { useEffect, useReducer, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import {
  answerBorrow, answerCard, continueTakeover, endTakeover, fetchFeed, fetchPending, stopHands, stopJob,
  type Activity, type Feed, type PendingCard,
} from './feed';
import { askKind, askLine, mmss, secondsLeft } from './islandAsk';
import IslandMascot from './IslandMascot';
import {
  applyFeed, bodyTop, countdown, dismiss, focused, handsKey, hitRect, hoverEnter, hoverLeave, initialState, interact, isSearchTool, mood, open,
  setFocus, setFullscreen, setMainFocused, setPresence, shape, tick, waitingActivity,
  type IslandState, type Mood, type StepLine,
} from './islandMachine';
import { initialGeometry, inShell, isGeometry, listenShell, openConversation, reportShape } from './islandShell';
import { askText, pickLang, stepText, t, type Lang } from '../locales/island';

type Action =
  | { type: 'feed'; feed: Feed } | { type: 'enter' } | { type: 'leave' } | { type: 'move' } | { type: 'open' }
  | { type: 'dismiss' } | { type: 'presence'; away: boolean } | { type: 'mainFocus'; focused: boolean }
  | { type: 'focus'; id: number } | { type: 'tick' } | { type: 'fullscreen'; on: boolean };

function reducer(s: IslandState, a: Action): IslandState {
  const now = Date.now();
  switch (a.type) {
    case 'feed': return applyFeed(s, a.feed, now);
    case 'enter': return hoverEnter(s, now);
    case 'leave': return hoverLeave(s, now);
    case 'move': return interact(s, now);
    case 'open': return open(s, now);
    case 'dismiss': return dismiss(s, now);
    case 'presence': return setPresence(s, a.away, now);
    case 'mainFocus': return setMainFocused(s, a.focused);
    case 'focus': return setFocus(s, a.id, now);
    case 'tick': return tick(s, now);
    case 'fullscreen': return setFullscreen(s, a.on, now);
  }
}

const LANG_KEY = 'i18nextLng';
const readLang = (): Lang => {
  let stored: string | null = null;
  try { stored = localStorage.getItem(LANG_KEY); } catch { /* storage blocked */ }
  return pickLang(stored, navigator.language);
};

/** How often the island asks for news: brisk while something is happening. */
export function pollDelay(s: IslandState, failed: boolean): number {
  if (failed) return 3000;
  if (!s.enabled) return 5000;
  return s.active.length || s.awaiting || s.mode !== 'hidden' ? 1000 : 2500;
}

export default function IslandApp() {
  const [s, dispatch] = useReducer(reducer, undefined, initialState);
  const [geo, setGeo] = useState(initialGeometry);
  const [lang, setLang] = useState(readLang);
  const [cd, setCd] = useState(0);
  const [clock, setClock] = useState(() => Math.floor(Date.now() / 1000));
  // 0.1.55: the cards themselves, so the island can answer them (only while some wait).
  const [pending, setPending] = useState<PendingCard[]>([]);
  const stateRef = useRef(s);
  stateRef.current = s;

  // Feed polling.
  useEffect(() => {
    const ctl = new AbortController();
    let timer = 0;
    const poll = async () => {
      let failed = false;
      try {
        const feed = await fetchFeed(stateRef.current.cursor, ctl.signal);
        dispatch({ type: 'feed', feed });
        if (feed.awaiting > 0) setPending(await fetchPending(ctl.signal).catch(() => []));
        else setPending((old) => (old.length ? [] : old));
      } catch {
        if (ctl.signal.aborted) return;
        failed = true;
      }
      timer = window.setTimeout(poll, pollDelay(stateRef.current, failed));
    };
    void poll();
    return () => { ctl.abort(); clearTimeout(timer); };
  }, []);

  // Timers live in the machine; this only reminds it what time it is.
  useEffect(() => {
    const id = window.setInterval(() => {
      dispatch({ type: 'tick' });
      const now = Date.now();
      setCd(Math.round(countdown(stateRef.current, now) * 100) / 100);
      if (stateRef.current.mode !== 'hidden') setClock(Math.floor(now / 1000));
    }, 250);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const offGeo = listenShell<typeof geo>('island-geometry', (g) => {
      if (isGeometry(g)) { setGeo(g); dispatch({ type: 'fullscreen', on: g.fullscreen === true }); }
    });
    dispatch({ type: 'fullscreen', on: initialGeometry().fullscreen === true });
    // In the shell the window is never key, so the page gets no reliable hover
    // of its own: the shell's pointer poll says when the pointer arrives and leaves.
    const offPointer = listenShell<{ inside: boolean }>('island-pointer', (p) => dispatch({ type: p?.inside ? 'enter' : 'leave' }));
    const offAway = listenShell<{ away: boolean }>('island-presence', (p) => dispatch({ type: 'presence', away: !!p?.away }));
    const offFocus = listenShell<{ focused: boolean }>('island-main-focus', (p) => dispatch({ type: 'mainFocus', focused: !!p?.focused }));
    const onStorage = (e: StorageEvent) => { if (e.key === LANG_KEY) setLang(readLang()); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') dispatch({ type: 'dismiss' }); };
    window.addEventListener('storage', onStorage);
    window.addEventListener('keydown', onKey);
    return () => { offGeo(); offPointer(); offAway(); offFocus(); window.removeEventListener('storage', onStorage); window.removeEventListener('keydown', onKey); };
  }, []);

  // Tell the shell where the island is, so everything else clicks through.
  const rect = hitRect(s, geo, window.innerWidth);
  const rectKey = `${rect.x},${rect.y},${rect.w},${rect.h}`;
  useEffect(() => { reportShape(rect); }, [rectKey]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Shrinking uses the quicker closing curve.
  const sh = shape(s, geo);
  const prevArea = useRef(sh.w * sh.h);
  const closing = sh.w * sh.h < prevArea.current;
  useEffect(() => { prevArea.current = sh.w * sh.h; });

  useEffect(() => { document.documentElement.lang = lang; }, [lang]);

  if (!s.enabled) return null;
  const m = mood(s);
  const domHover = !inShell();   // a plain browser (dev) has real hover events
  const style = {
    '--w': `${sh.w}px`, '--h': `${sh.h}px`, '--r': `${sh.r}px`, '--cd': cd, '--body-top': `${bodyTop(geo)}px`,
  } as CSSProperties;

  return (
    <>
      {!inShell() && <DevBackdrop />}
      <div className={`island${geo.notch ? '' : ' flat'}${closing ? ' closing' : ''}`} data-mode={s.mode} style={style}
        role="region" aria-label={t(lang, 'region')}
        onMouseEnter={domHover ? () => dispatch({ type: 'enter' }) : undefined}
        onMouseLeave={domHover ? () => dispatch({ type: 'leave' }) : undefined}
        onMouseMove={() => dispatch({ type: 'move' })}>
        <button type="button" className="slot-left" onClick={() => dispatch({ type: 'open' })} aria-label={t(lang, 'openArslan')}>
          <IslandMascot mood={m} size={geo.notch ? 22 : 16} small paused={s.mode === 'hidden' && geo.notch} />
        </button>
        <div className="slot-right">{s.mode === 'compact' && <CompactRight s={s} clock={clock} />}
          {s.mode === 'tab' && <TabRight lang={lang} card={pending[0]} clock={clock} />}</div>
        <div className="expanded" aria-hidden={s.mode !== 'expanded'}>
          <div className="ihead">
            <span className="count">
              {(s.view === 'overview' || s.view === 'empty') && (s.active.length ? t(lang, 'running', { n: s.active.length }) : t(lang, 'idle'))}
              {(s.view === 'overview' || s.view === 'empty') && s.learned > 0 && <span className="learned" data-testid="island-learned"> · {t(lang, 'learned', { n: s.learned })}</span>}
            </span>
            <button type="button" className="x" onClick={() => dispatch({ type: 'dismiss' })} aria-label={t(lang, 'close')}>
              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
            </button>
          </div>
          <div className="ibody">{s.mode === 'expanded' && <View s={s} m={m} lang={lang} dispatch={dispatch} pending={pending}
            clock={clock} onAnswered={(callId) => setPending((old) => old.filter((c) => c.call_id !== callId))} />}</div>
          <div className="countdown" />
        </div>
      </div>
    </>
  );
}

/** Over a full-screen app (decision 4): "needs you" and the time left, still — no pulse. */
function TabRight({ lang, card, clock }: { lang: Lang; card: PendingCard | undefined; clock: number }) {
  return (
    <span className="tab-right" data-testid="island-tab">
      <span className="still-dot" aria-hidden="true" />{t(lang, 'needsYou')}
      {card && <span className="mono">{mmss(secondsLeft(card, clock * 1000))}</span>}
    </span>
  );
}

function CompactRight({ s, clock }: { s: IslandState; clock: number }) {
  if (s.awaiting > 0) return <><span className="pulse-dot" /><span>{s.awaiting}</span></>;
  const a = focused(s);
  if (!a) return null;
  if (a.plan && a.plan.total > 0) {
    const p = a.plan.done / a.plan.total;
    const c = 2 * Math.PI * 6;
    return (
      <>
        <svg className="ring" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="8" cy="8" r="6" fill="none" stroke="rgba(255,255,255,.15)" strokeWidth="2.4" />
          <circle cx="8" cy="8" r="6" fill="none" stroke="var(--c-working)" strokeWidth="2.4" strokeLinecap="round"
            strokeDasharray={`${(p * c).toFixed(1)} ${c.toFixed(1)}`} transform="rotate(-90 8 8)" />
        </svg>
        <span>{a.plan.done}/{a.plan.total}</span>
      </>
    );
  }
  if (s.active.length > 1) return <span>{s.active.length}</span>;
  return <span>{elapsed(clock - a.started_at)}</span>;
}

export function elapsed(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return h ? `${h}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}` : `${mm}:${String(ss).padStart(2, '0')}`;
}

const VEIL: Partial<Record<Mood, string>> = {
  approval: 'rgba(245,165,36,.42)', finished: 'rgba(52,211,153,.45)', stopped: 'rgba(255,107,87,.42)',
  working: 'rgba(59,158,255,.22)', searching: 'rgba(124,131,255,.26)',
};
const STATE_COLOR: Record<string, string> = {
  working: 'var(--c-working)', searching: 'var(--c-searching)', approval: 'var(--c-approval)',
  finished: 'var(--c-finished)', stopped: 'var(--c-stopped)', idle: 'var(--c-idle)', sleeping: 'var(--c-sleeping)',
};

const titleOf = (lang: Lang, title: string | null, kind: Activity['kind']) => title || t(lang, kind);

function Card({ m, size, children, onClick }: { m: Mood; size: number; children: ReactNode; onClick?: () => void }) {
  return (
    <div className={`card${onClick ? ' clickable' : ''}`} style={{ '--veil': VEIL[m] ?? 'transparent' } as CSSProperties}
      onClick={onClick}>
      <IslandMascot mood={m} size={size} />
      <div className="cmain">{children}</div>
    </div>
  );
}

function Who({ color, title, label, elapsed: time }: { color: string; title: string; label: string; elapsed?: string }) {
  return <div className="who"><span className="dot" style={{ '--sc': color } as CSSProperties} /><b>{title}</b><span>{label}</span>
    {time && <span className="mono" data-testid="island-elapsed">{time}</span>}</div>;
}

/**
 * One waiting card, answerable here (0.1.55 decision 3) — unless the server says it is
 * risky (`island_ok` false): then it says why and offers "Open in Arslan". Declining is
 * always offered: saying no is never the risky answer.
 */
function AskView({ card, total, m, lang, clock, onAnswered }: {
  card: PendingCard; total: number; m: Mood; lang: Lang; clock: number; onAnswered: (callId: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [card.call_id]);
  const answer = async (approve: boolean) => {
    setBusy(true); setFailed(false);
    const ok = await answerCard(card.call_id, approve).catch(() => false);
    setBusy(false);
    if (ok) onAnswered(card.call_id); else setFailed(true);
  };
  const line = askLine(card);
  return (
    <>
      {total > 1 && <span className="queue" data-testid="island-queue">1 / {total}</span>}
      <Card m={m} size={58}>
        <Who color={STATE_COLOR.approval} title={askText(lang, askKind(card))} label={t(lang, 'needsYou')}
          elapsed={mmss(secondsLeft(card, clock * 1000))} />
        {line && <div className="code" data-testid="island-ask-line" title={line}>{line}</div>}
        {!card.island_ok && <div className="itext risky" data-testid="island-risky">{t(lang, 'riskyNote')}</div>}
        {failed && <div className="itext" role="alert">{t(lang, 'answerFailed')}</div>}
        <div className="btns">
          <button type="button" className="btn" disabled={busy} data-testid="island-decline" onClick={() => void answer(false)}>{t(lang, 'decline')}</button>
          {card.island_ok
            ? <button type="button" className="btn primary" disabled={busy} data-testid="island-allow" onClick={() => void answer(true)}>{t(lang, 'allow')}</button>
            : <button type="button" className="btn primary" data-testid="island-open-in-arslan" onClick={() => openConversation(card.conversation_id)}>{t(lang, 'openInArslan')}</button>}
        </div>
      </Card>
    </>
  );
}

/** Stop the background job this card shows. */
function StopJob({ jobId, lang }: { jobId: string; lang: Lang }) {
  const [stopping, setStopping] = useState(false);
  return (
    <button type="button" className="btn" data-testid="island-stop-job" disabled={stopping}
      onClick={(e) => { e.stopPropagation(); setStopping(true); stopJob(jobId).then((ok) => { if (!ok) setStopping(false); }).catch(() => setStopping(false)); }}>
      {t(lang, stopping ? 'stoppingJob' : 'stopJob')}
    </button>
  );
}

function View({ s, m, lang, dispatch, pending, clock, onAnswered }: {
  s: IslandState; m: Mood; lang: Lang; dispatch: (a: Action) => void;
  pending: PendingCard[]; clock: number; onAnswered: (callId: string) => void;
}) {
  const close = <button type="button" className="btn" onClick={() => dispatch({ type: 'dismiss' })}>{t(lang, 'close')}</button>;
  if (s.view === 'hands' && s.hands) return <HandsView s={s} m={m} lang={lang} dispatch={dispatch} />;
  if (s.view === 'needsYou' && pending.length) {
    return <AskView card={pending[0]} total={pending.length} m={m} lang={lang} clock={clock} onAnswered={onAnswered} />;
  }
  if (s.view === 'needsYou') {
    const a = waitingActivity(s);
    const cid = s.awaitingConversations[0] ?? null;
    return (
      <>
        {s.awaiting > 1 && <span className="queue">1 / {s.awaiting}</span>}
        <Card m={m} size={58}>
          <Who color={STATE_COLOR.approval} title={a ? titleOf(lang, a.title, a.kind) : t(lang, 'turn')} label={t(lang, 'needsYou')} />
          <div className="ititle">{t(lang, 'needsYouText')}</div>
          {a?.step && <div className="code" title={stepText(lang, a.step.tool, a.step.target)}>{stepText(lang, a.step.tool, a.step.target)}</div>}
          <div className="btns">
            <button type="button" className="btn primary" onClick={() => openConversation(cid)}>{t(lang, 'openToApprove')}</button>
          </div>
        </Card>
      </>
    );
  }
  if ((s.view === 'finished' || s.view === 'stopped') && s.current) {
    const c = s.current;
    const done = c.kind === 'finished';
    const label = done ? t(lang, 'finished')
      : t(lang, c.reason === 'paused' ? 'stoppedPaused' : c.reason === 'error' ? 'stoppedError' : 'stoppedNeedsReview');
    const fallback = done ? t(lang, 'finishedNoSummary')
      : t(lang, c.reason === 'paused' ? 'stoppedPausedText' : c.reason === 'error' ? 'stoppedErrorText' : 'stoppedNeedsReviewText');
    return (
      <Card m={m} size={60}>
        <Who color={STATE_COLOR[done ? 'finished' : 'stopped']} title={titleOf(lang, c.title, c.work)} label={label} />
        <div className="itext">{c.summary || fallback}</div>
        <div className="btns">
          <button type="button" className="btn primary" onClick={() => { openConversation(c.conversationId); dispatch({ type: 'dismiss' }); }}>
            {t(lang, 'openConversation')}
          </button>
          {close}
        </div>
      </Card>
    );
  }
  const a = focused(s);
  if (s.view === 'overview' && a) {
    const others = s.active.filter((o) => o.id !== a.id);
    return (
      <>
        <Card m={m} size={70}>
          <Who color={STATE_COLOR[m] ?? STATE_COLOR.working} title={titleOf(lang, a.title, a.kind)} label={t(lang, a.kind)}
            elapsed={elapsed(clock - a.started_at)} />
          {a.plan && a.plan.items.length > 0 && <Plan items={a.plan.items} />}
          {a.thumb
            ? <div className="hands-row"><img className="thumb" data-testid="island-thumb" alt={t(lang, 'thumbAlt')}
              src={`data:image/jpeg;base64,${a.thumb}`} /><Ticker steps={s.steps[a.id] ?? []} lang={lang} /></div>
            : <Ticker steps={s.steps[a.id] ?? []} lang={lang} />}
          <div className="btns">
            {a.job_id && <StopJob jobId={a.job_id} lang={lang} />}
            {usingHands(s.active) && <StopHands lang={lang} />}
            <button type="button" className="btn primary" data-testid="island-open" onClick={() => openConversation(a.conversation_id)}>
              {t(lang, 'openArslan')}</button>
          </div>
        </Card>
        {others.length > 0 && (
          <div className="card side">
            {others.slice(0, 3).map((o) => (
              <button type="button" key={o.id} className="pill" onClick={() => dispatch({ type: 'focus', id: o.id })}
                style={{ '--pc': 'var(--c-working)' } as CSSProperties}>
                <IslandMascot mood={isSearchTool(o.step?.tool) ? 'searching' : 'working'} size={24} small />
                <span className="ptitle">{titleOf(lang, o.title, o.kind)}</span><small>{t(lang, o.kind)}</small>
              </button>
            ))}
          </div>
        )}
      </>
    );
  }
  return (
    <Card m={m} size={60}>
      <div className="ititle">{t(lang, 'emptyTitle')}</div>
      <div className="btns"><button type="button" className="btn primary" onClick={() => openConversation(null)}>{t(lang, 'openArslan')}</button></div>
    </Card>
  );
}

/**
 * Hands v2 (§6.3-6.4, the mock's round 5): a borrow waiting for your pause (now / not this
 * time), the front borrowed, the screen taken over (time left, Stop), or a takeover paused
 * because you moved (Stop / I'll do it / Continue).
 */
function HandsView({ s, m, lang, dispatch }: { s: IslandState; m: Mood; lang: Lang; dispatch: (a: Action) => void }) {
  const [busy, setBusy] = useState(false);
  const a = focused(s);
  const what = a?.step ? stepText(lang, a.step.tool, a.step.target) : '';
  const run = (p: Promise<boolean>) => { setBusy(true); p.catch(() => false).finally(() => setBusy(false)); };
  const key = handsKey(s.hands);
  const left = s.hands?.takeover?.remaining_s ?? 0;
  if (key === 'paused') {
    return (
      <Card m={m} size={58}>
        <Who color={STATE_COLOR.approval} title={t(lang, 'pausedTitle')} label={t(lang, 'takeover')} />
        <div className="itext">{t(lang, 'pausedText')}</div>
        <div className="btns">
          <button type="button" className="btn danger" disabled={busy} data-testid="island-takeover-stop"
            onClick={() => run(endTakeover())}>{t(lang, 'stopHands')}</button>
          <button type="button" className="btn" data-testid="island-takeover-me"
            onClick={() => dispatch({ type: 'dismiss' })}>{t(lang, 'pausedMe')}</button>
          <button type="button" className="btn primary" disabled={busy} data-testid="island-takeover-continue"
            onClick={() => run(continueTakeover())}>{t(lang, 'pausedContinue')}</button>
        </div>
        <div className="itext small">{t(lang, 'pausedMeNote')}</div>
      </Card>
    );
  }
  if (key === 'takeover') {
    return (
      <Card m={m} size={58}>
        <Who color={STATE_COLOR.working} title={t(lang, 'takeoverRunning')} label={what} elapsed={mmss(left)} />
        <div className="itext">{t(lang, 'takeoverText')}</div>
        <div className="btns">
          <button type="button" className="btn danger" disabled={busy} data-testid="island-takeover-stop"
            onClick={() => run(endTakeover())}>{t(lang, 'stopHands')}</button>
        </div>
      </Card>
    );
  }
  if (key === 'waiting') {
    return (
      <Card m={m} size={58}>
        <Who color={STATE_COLOR.working} title={t(lang, 'borrowWaiting')} label={what} />
        <div className="itext">{t(lang, 'borrowWaitingText')}</div>
        <div className="btns">
          <button type="button" className="btn" disabled={busy} data-testid="island-borrow-skip"
            onClick={() => run(answerBorrow('skip'))}>{t(lang, 'borrowSkip')}</button>
          <button type="button" className="btn primary" disabled={busy} data-testid="island-borrow-now"
            onClick={() => run(answerBorrow('now'))}>{t(lang, 'borrowNow')}</button>
        </div>
      </Card>
    );
  }
  return (
    <Card m={m} size={58}>
      <Who color={STATE_COLOR.working} title={t(lang, 'borrowing')} label={what} />
      <div className="itext">{t(lang, 'borrowingText')}</div>
    </Card>
  );
}

/** Arslan Hands is working in a Mac app right now (0.1.53). */
export function usingHands(active: { step: { tool: string } | null }[]): boolean {
  return active.some((a) => a.step?.tool?.startsWith('desktop_') === true);
}

/** One click stops every Hands action (the menu bar has the same). */
function StopHands({ lang }: { lang: Lang }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="btn" data-testid="island-stop-hands" disabled={done}
      onClick={(e) => { e.stopPropagation(); stopHands().then((ok) => setDone(ok)).catch(() => {}); }}>
      {t(lang, done ? 'stoppedHands' : 'stopHands')}
    </button>
  );
}

function Plan({ items }: { items: { text: string | null; status: string }[] }) {
  const shown = items.slice(0, 4);
  return (
    <div className="plan">
      {shown.map((i, k) => (
        <span key={k} className={i.status === 'done' ? 'done' : i.status === 'in_progress' ? 'now' : ''}>
          {i.status === 'done' ? '✓ ' : i.status === 'in_progress' ? '› ' : ''}{i.text}
        </span>
      ))}
      {items.length > shown.length && <span>+{items.length - shown.length}</span>}
    </div>
  );
}

const ICON: Record<string, string> = { web_search: '⌕', web_extract: '↗', recall: '⌕', write_file: '✎', edit_file: '✎', run_command: '›_' };

function Ticker({ steps, lang }: { steps: StepLine[]; lang: Lang }) {
  if (!steps.length) return null;
  const shown = steps.slice(-3);
  return (
    <ul className="ticker">
      {shown.map((st, i) => (
        <li key={`${st.at}-${st.tool}-${i}`} className={i === shown.length - 1 ? 'now' : ''}>
          <span className="ic">{ICON[st.tool] ?? (st.tool.startsWith('browser_') ? '◫' : '·')}</span>
          <span className="tx">{stepText(lang, st.tool, st.target)}</span>
        </li>
      ))}
    </ul>
  );
}

/** In a plain browser (dev), a dark desktop behind the island so it can be seen. */
function DevBackdrop() {
  return <div className="dev-backdrop" aria-hidden="true"><div className="dev-menubar" /></div>;
}
