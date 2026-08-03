import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Check, X, RefreshCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Spawn } from '../types';
import { useWebSocket } from '../hooks/useWebSocket';
import { SpawnAvatar } from './SpawnAvatar';
import MessageBody from './MessageBody';
import LiveActivity from './LiveActivity';
import { humanizeStep } from '../lib/toolHumanize';
import type { ToolStep } from '../api/client.types';

interface SandboxPanelProps {
  spawn: Spawn;
  sessionId: string;
  seed: string | null;            // deliverable to tune (refine entry), or null
  conversationId: string;         // main thread to merge back into
  onClose: () => void;            // Discard / ✕
  onMerged: (payload: {           // Confirm & Merge succeeded — append to main store
    spawn_id: number; message_id: number; content: string; summary: string; spawn_name: string;
  }) => void;
  hidden?: boolean;               // mounted but not the active pane — keep socket alive
}

type Msg = { id: string; role: 'user' | 'spawn'; text: string; tools?: ToolStep[] };

export default function SandboxPanel({ spawn, sessionId, seed, conversationId, onClose, onMerged, hidden = false }: SandboxPanelProps) {
  const { t } = useTranslation();
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Msg[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const toolsRef = useRef<ToolStep[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const onFrame = useCallback((raw: unknown) => {
    const m = raw as any;
    switch (m.type) {
      case 'stream_start':
        toolsRef.current = [];
        setStreaming(true);
        setStartedAt(Date.now());
        setMessages((p) => [...p, { id: '__s__', role: 'spawn', text: '' }]);
        break;
      case 'stream_chunk':
        setMessages((p) => p.map((x) => (x.id === '__s__' ? { ...x, text: x.text + m.content } : x)));
        break;
      case 'tool_call':
        // Track as a ToolStep (name + args + running) — the same shape the main chat uses —
        // so the sandbox can humanize activity instead of showing a raw `🔧 web_search`.
        toolsRef.current = [...toolsRef.current, { tool: m.tool, argsSummary: m.args_summary, status: 'running' }];
        setMessages((p) => p.map((x) => (x.id === '__s__' ? { ...x, tools: [...toolsRef.current] } : x)));
        break;
      case 'tool_result': {
        // Resolve the most-recent running step with this tool → ok/error + summary (mirrors arslanStore).
        const steps = [...toolsRef.current];
        for (let i = steps.length - 1; i >= 0; i--) {
          if (steps[i].tool === m.tool && steps[i].status === 'running') {
            steps[i] = { ...steps[i], status: m.ok ? 'ok' : 'error', resultSummary: m.summary };
            break;
          }
        }
        toolsRef.current = steps;
        setMessages((p) => p.map((x) => (x.id === '__s__' ? { ...x, tools: [...steps] } : x)));
        break;
      }
      case 'stream_end':
        setMessages((p) => p.map((x) => (x.id === '__s__' ? { ...x, id: `m-${Date.now()}` } : x)));
        setStreaming(false);
        break;
      case 'merged':
        onMerged(m);
        break;
      case 'discarded':
        onClose();
        break;
      case 'error':
        setStreaming(false);
        setMessages((p) => [...p, { id: `e-${Date.now()}`, role: 'spawn', text: `⚠️ ${m.detail ?? m.message ?? 'error'}` }]);
        break;
      default:
        break;
    }
  }, [onClose, onMerged]);

  // No query string here: ws.ts appends `?token=…`, so a `?s=` would collide into a
  // double-`?` and drop the token. The session is isolated by the parent's
  // key={sessionId}, which forces a fresh socket per session anyway.
  void sessionId;
  const { send } = useWebSocket(`/ws/sandbox/${Number(spawn.id)}`, onFrame);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || streaming) return;
    setMessages((p) => [...p, { id: `u-${Date.now()}`, role: 'user', text: input }]);
    send({ type: 'user_message', content: input,
      // The sandbox asks the server for the main thread's last turn as
      // read-only background; the server needs to know WHICH thread.
      conversation_id: conversationId, ...(seed ? { attached_context: seed } : {}) });
    setInput('');
    setStreaming(true);
  };

  const hasContent = messages.some((m) => m.role === 'spawn' && m.text && m.id !== '__s__');
  const confirm = () => send({ type: 'confirm_merge', conversation_id: conversationId });
  const discard = () => {
    if (hasContent && !window.confirm(t('orchestrator.sandbox_discard_confirm'))) return;
    send({ type: 'discard' });
    onClose();
  };

  return (
    <div className={`w-[45%] border-l border-border bg-sidebar flex-col h-full animate-slide-in-right shrink-0 z-20 ${hidden ? 'hidden' : 'flex'}`}>
      <div className="h-[52px] border-b border-border px-4 bg-background/80 backdrop-blur flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2.5">
          <SpawnAvatar seed={spawn.name} size={28} />
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-bold text-foreground">{spawn.name}</span>
            <span className="text-[9px] bg-primary/10 text-primary px-2 py-0.5 rounded font-mono font-bold uppercase">Sandbox</span>
          </div>
        </div>
        <button onClick={discard} className="p-1 text-muted-foreground hover:text-foreground bg-surface border border-border/80 rounded" title="Close"><X className="w-4 h-4" /></button>
      </div>

      {seed && (
        <div className="px-4 py-2 text-[11px] text-muted-foreground bg-surface border-b border-border/80 font-sans">
          <span>↳ </span><span>{t('orchestrator.sandbox_seed_label')}</span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((m) => (
          <div key={m.id} className={m.role === 'user' ? 'flex justify-end' : 'flex items-start gap-3'}>
            {m.role === 'spawn' && <SpawnAvatar seed={spawn.name} size={26} />}
            <div className={m.role === 'user'
              ? 'max-w-[80%] px-3 py-2 text-[12.5px] text-foreground rounded-xl'
              : 'flex-1 text-xs text-foreground'}
              style={m.role === 'user' ? { background: 'rgba(120,140,170,0.10)', border: '1px solid rgba(255,255,255,0.08)' } : undefined}>
              {m.role === 'spawn'
                ? (m.id === '__s__' && !m.text
                    ? <LiveActivity steps={m.tools ?? []} startedAt={startedAt}
                        phrases={[t('working.summon'), t('working.context'), t('working.tools'), t('working.compose')]} />
                    : <MessageBody text={m.text} streaming={m.id === '__s__'} hasMessageActions={false}
                        className="[&>*:first-child]:mt-0 [&>*:last-child]:mb-0" />)
                : m.text}
              {/* Humanized tool summary under the reply (LiveActivity already shows steps live
                  during the empty-text gap, so skip the duplicate there). */}
              {m.tools && m.tools.length > 0 && !(m.id === '__s__' && !m.text) && (
                <div className="mt-2 text-[10px] font-mono text-muted-foreground border-l-2 border-primary pl-2 space-y-0.5">
                  {m.tools.map((s, i) => <div key={i}>{humanizeStep(s, t)}</div>)}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={submit} className="p-3 border-t border-border/80 relative">
        <input value={input} onChange={(e) => setInput(e.target.value)} disabled={streaming}
          placeholder={t('orchestrator.sandbox_input_placeholder', { name: spawn.name })}
          className="w-full bg-background border border-border-strong focus:border-primary/60 rounded-xl pl-3 pr-10 py-2.5 text-xs text-foreground focus:outline-none" />
        <button type="submit" disabled={streaming || !input.trim()}
          className="absolute right-5 top-1/2 -translate-y-1/2 p-1.5 rounded-lg bg-primary text-primary-foreground disabled:bg-foreground/[0.02] disabled:text-subtle-foreground">
          {streaming ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
        </button>
      </form>

      <div className="flex gap-2 px-4 py-2 border-t border-border/80">
        <button onClick={confirm} disabled={!hasContent || streaming}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-[11px] font-mono font-bold uppercase tracking-wider rounded-lg bg-primary text-primary-foreground hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed">
          <Check className="w-3.5 h-3.5" /> {t('orchestrator.sandbox_confirm_merge')}
        </button>
        <button onClick={discard}
          className="px-3 py-2 text-[11px] font-mono uppercase tracking-wider rounded-lg border border-border/80 text-muted-foreground hover:text-foreground">
          {t('orchestrator.sandbox_discard')}
        </button>
      </div>
    </div>
  );
}
