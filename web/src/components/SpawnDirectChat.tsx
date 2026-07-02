import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Send, RefreshCcw, Check
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Message, Spawn } from '../types';
import { TOOLS, SKILLS } from '../data';
import SFSymbol from './SFSymbol';
import MessageBody from './MessageBody';
import EChart from './EChart';
import DeckDownloadCard from './DeckDownloadCard';
import LiveActivity from './LiveActivity';
import { getIcon } from './iconMap';
import { SandboxBackdrop } from './SandboxBackdrop';
import { SpawnAvatar } from './SpawnAvatar';
import { useWebSocket } from '../hooks/useWebSocket';
import { useComposerAttach, AttachChips, AttachControl, type Attachment } from './ComposerAttach';

interface SpawnDirectChatProps {
  spawn: Spawn;
  currentStyle: 'quartz' | 'brutalist' | 'linear';
  refineDeliverable?: string | null;
  onFinalize?: (content: string) => void;
}

interface BackendMessage {
  message_id: number;
  role: string;
  content: string;
}

interface ToolStep {
  tool: string;
  argsSummary: string;
  status: 'running' | 'ok' | 'error';
  resultSummary?: string;
  artifactSvg?: string;
  artifactChart?: Record<string, unknown>;
  artifactPptx?: { filename: string; bytesB64: string; slides: number };
}

export default function SpawnDirectChat({
  spawn,
  currentStyle,
  refineDeliverable,
  onFinalize,
}: SpawnDirectChatProps) {
  const { t } = useTranslation();
  const refineAttachName = t('spawn_chat.refine_attach_name');
  const [inputValue, setInputValue] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  // Tool frames mutate toolStepsRef (a ref) — bump forces a re-render so LiveActivity shows
  // each step the moment it happens instead of waiting for stream_end.
  const [, bumpLive] = useState(0);
  const [workStartedAt, setWorkStartedAt] = useState<number | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const attach = useComposerAttach(setAttachments);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  // Per-stream tool steps accumulated from tool_call/tool_result frames, attached on stream_end.
  const toolStepsRef = useRef<ToolStep[]>([]);

  // When user scrolls up, release the stick. When they scroll back near the bottom, re-engage.
  const handleScrollContainerScroll = () => {
    const el = scrollContainerRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  const scrollToBottom = () => {
    const el = scrollContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  // Observe content size so streaming tokens trigger instant scroll.
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      if (stickToBottomRef.current) scrollToBottom();
    });
    const target = el.firstElementChild ?? el;
    ro.observe(target);
    return () => ro.disconnect();
  }, []);

  // When messages gain a new user message (just sent), force stick to bottom.
  useEffect(() => {
    const last = messages[messages.length - 1];
    if (last?.sender === 'user') {
      stickToBottomRef.current = true;
      scrollToBottom();
    } else if (stickToBottomRef.current) {
      scrollToBottom();
    }
  }, [messages]);

  // Reset messages when spawn changes (before new history frame arrives)
  useEffect(() => {
    setMessages([]);
    setStreaming(false);
  }, [spawn.id]);

  const toMessage = useCallback((m: BackendMessage): Message => {
    const isUser = m.role === 'user';
    return {
      id: String(m.message_id),
      messageId: m.message_id,
      sender: isUser ? 'user' : 'spawn',
      senderName: isUser ? 'Mirzat' : spawn.name,
      senderAvatar: isUser ? '🦁' : spawn.avatarEmoji,
      text: m.content,
      timestamp: '',
    };
  }, [spawn.name, spawn.avatarEmoji]);

  const onFrame = useCallback((raw: unknown) => {
    const m = raw as any;
    switch (m.type) {
      case 'history': {
        const msgs: Message[] = (m.messages as BackendMessage[]).map(toMessage);
        setMessages(msgs);
        const maxId = msgs.reduce((acc, msg) => Math.max(acc, msg.messageId ?? 0), 0);
        setLastMessageId(maxId);
        break;
      }
      case 'message': {
        const newMsg = toMessage(m as BackendMessage);
        setMessages(prev => {
          if (prev.some(p => p.messageId === newMsg.messageId)) return prev;
          return [...prev, newMsg];
        });
        break;
      }
      case 'stream_start': {
        setStreaming(true);
        toolStepsRef.current = [];
        const placeholder: Message = {
          id: '__streaming__',
          sender: 'spawn',
          senderName: spawn.name,
          senderAvatar: spawn.avatarEmoji,
          text: '',
          timestamp: '',
        };
        setMessages(prev => [...prev.filter(p => p.id !== '__streaming__'), placeholder]);
        break;
      }
      case 'stream_chunk': {
        setMessages(prev => prev.map(p =>
          p.id === '__streaming__' ? { ...p, text: p.text + (m.content as string) } : p
        ));
        break;
      }
      case 'tool_call': {
        toolStepsRef.current.push({
          tool: m.tool as string,
          argsSummary: (m.args_summary as string) ?? '',
          status: 'running',
        });
        bumpLive((v) => v + 1);
        break;
      }
      case 'tool_result': {
        // Find the LAST running step with the same tool and finalize it.
        const steps = toolStepsRef.current;
        for (let i = steps.length - 1; i >= 0; i--) {
          if (steps[i].tool === m.tool && steps[i].status === 'running') {
            steps[i].status = m.ok ? 'ok' : 'error';
            steps[i].resultSummary = (m.summary as string) ?? '';
            steps[i].artifactSvg =
              m.artifact?.kind === 'svg' ? (m.artifact.content as string) : undefined;
            steps[i].artifactChart =
              m.artifact?.kind === 'echarts' ? (m.artifact.spec as Record<string, unknown>) : undefined;
            steps[i].artifactPptx =
              m.artifact?.kind === 'pptx'
                ? { filename: (m.artifact.filename as string) ?? 'deck.pptx',
                    bytesB64: (m.artifact.bytes_b64 as string) ?? '',
                    slides: (m.artifact.slides as number) ?? 0 }
                : undefined;
            break;
          }
        }
        bumpLive((v) => v + 1);
        break;
      }
      case 'stream_end': {
        const steps = toolStepsRef.current;
        const toolActivity = steps.length > 0 ? {
          id: String(m.message_id),
          toolName: steps[0].tool,
          emoji: '🔧',
          status: 'completed' as const,
          action: steps[0].argsSummary,
          outputSummary: steps.map(s => s.resultSummary).filter(Boolean).join('\n'),
          collapsed: false,
          artifactSvg: steps.find(s => s.artifactSvg)?.artifactSvg,
          artifactChart: steps.find(s => s.artifactChart)?.artifactChart,
          artifactPptx: steps.find(s => s.artifactPptx)?.artifactPptx,
        } : undefined;
        setMessages(prev => prev.map(p =>
          p.id === '__streaming__'
            ? { ...p, id: String(m.message_id), messageId: m.message_id as number, ...(toolActivity ? { toolActivity } : {}) }
            : p
        ));
        toolStepsRef.current = [];
        setStreaming(false);
        setLastMessageId(m.message_id as number);
        break;
      }
      case 'error': {
        setStreaming(false);
        const errMsg: Message = {
          id: `err-${Date.now()}`,
          sender: 'spawn',
          senderName: spawn.name,
          senderAvatar: spawn.avatarEmoji,
          text: `⚠️ ${m.detail ?? m.message ?? 'An error occurred.'}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        };
        setMessages(prev => [...prev, errMsg]);
        break;
      }
      case 'attachment_stored': {
        setStreaming(false);
        setMessages(prev => [...prev, {
          id: `stored-${prev.length}-${m.chunks}`,
          sender: 'spawn',
          senderName: spawn.name ?? '知识库',
          senderAvatar: spawn.avatarEmoji ?? '📎',
          text: `📎 已记入 ${m.spawn_name ?? '知识库'} 的知识库 · ${m.chunks} 块`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        }]);
        break;
      }
      default:
        break;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spawn.name, spawn.avatarEmoji, toMessage]);

  const { send, setLastMessageId } = useWebSocket(`/ws/chat/${Number(spawn.id)}`, onFrame);

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim() || streaming) return;
    setStreaming(true);  // no dead air: pulse shows from SEND, not from stream_start
    setWorkStartedAt(Date.now());

    const userMsg: Message = {
      id: `msg-direct-user-${Date.now()}`,
      sender: 'user',
      senderName: 'Mirzat',
      senderAvatar: '🦁',
      text: inputValue,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    // In refine mode, the deliverable being refined must reach the spawn reliably
    // via attached_context — independent of the (user-mutable) attachments array.
    // Image chips carry OCR'd text when found; otherwise empty → no context.
    const textAttachments = attachments.filter((a) => a.text);
    const parts = textAttachments.map((a) => a.text);
    if (refineDeliverable && !parts.includes(refineDeliverable)) parts.unshift(refineDeliverable);
    const attached_context = parts.join('\n\n---\n\n');
    const attached_names = [
      ...(refineDeliverable && !textAttachments.some((a) => a.name === refineAttachName)
        ? [refineAttachName]
        : []),
      ...textAttachments.map((a) => a.name),
    ];

    setMessages(prev => [...prev, userMsg]);
    send({
      type: 'user_message',
      content: inputValue,
      ...(attached_context ? { attached_context, attached_names } : {}),
    });
    setInputValue('');
    attach.clear();
    setStreaming(true);
  };

  return (
    <div className="flex-grow flex flex-col h-full overflow-hidden bg-background relative font-sans">

      {/* Spawn Header details */}
      <div className={`px-6 py-4 flex items-center justify-between border-b border-border/80 relative z-10 bg-background/80 backdrop-blur`}>
        <div className="flex items-center gap-3">
          <SpawnAvatar seed={spawn.name} size={36} />
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xs font-bold font-mono tracking-widest text-foreground uppercase">{spawn.name} {t('spawn_chat.direct_channel_suffix')}</h2>
            </div>
            <p className="text-[10px] text-subtle-foreground mt-0.5 font-sans">
              {t('spawn_chat.specialist_field')} <span className="text-foreground font-medium">{spawn.domain}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {refineDeliverable && (
            <button
              type="button"
              disabled={streaming}
              onClick={() => {
                if (streaming) return;
                const latestAssistant = [...messages].reverse().find((m) => m.sender !== 'user');
                if (latestAssistant?.text) onFinalize?.(latestAssistant.text);
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-mono uppercase tracking-wider rounded-lg bg-primary text-primary-foreground hover:bg-primary-hover transition-all select-none disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Check className="w-3.5 h-3.5" />
              <span>{t('spawn.finalize_to_main')}</span>
            </button>
          )}
        </div>
      </div>

      {/* Refine banner — shown when this spawn chat was opened to refine a deliverable */}
      {refineDeliverable && (
        <div className="px-6 py-2 text-[11px] text-muted-foreground bg-surface border-b border-border/80 relative z-10 font-sans">
          {t('spawn_chat.refine_banner', { name: spawn.name })}
        </div>
      )}

      {/* Messages Thread Container */}
      <div ref={scrollContainerRef} onScroll={handleScrollContainerScroll} className="flex-1 overflow-y-auto p-6 space-y-6 relative z-10">

        {/* Header Hero card for direct chat — prism halo behind it in the empty state */}
        <div className="relative max-w-3xl mx-auto mb-8">
          {messages.length === 0 && <SandboxBackdrop />}
          <div className="relative z-10 bg-surface/30 border border-border/80 rounded-2xl p-6 text-center space-y-4">
          <SpawnAvatar seed={spawn.name} size={64} className="mx-auto" />
          <div className="space-y-1">
            <h3 className="text-sm font-bold text-foreground font-sans flex items-center justify-center gap-2">
              <span>{spawn.name}</span>
            </h3>
            <p className="text-xs text-muted-foreground max-w-lg mx-auto font-sans leading-relaxed">
              {spawn.description}
            </p>
          </div>

          <div className="h-[1px] bg-border/50 max-w-md mx-auto"></div>

          {/* Capabilities Badges */}
          <div className="flex flex-wrap items-center justify-center gap-2 max-w-xl mx-auto pt-1">
            {spawn.tools.map(tId => {
              const tool = TOOLS.find(t => t.id === tId) || { name: tId };
              return (
                <span key={tId} className="px-2 py-0.5 bg-surface text-[10px] font-mono text-foreground rounded-lg flex items-center gap-1">
                  {getIcon(tId, 'w-3 h-3')}
                  <span>{tool.name}</span>
                </span>
              );
            })}
            {spawn.skills.map(sId => {
              const skill = SKILLS.find(s => s.id === sId) || { name: sId };
              return (
                <span key={sId} className="px-2 py-0.5 bg-warning/10 text-[10px] font-mono text-warning rounded-lg flex items-center gap-1">
                  {getIcon(sId, 'w-3 h-3 text-warning')}
                  <span>{skill.name}</span>
                </span>
              );
            })}
          </div>
          </div>
        </div>

        {/* Individual Messages */}
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((msg) => {
            const isUser = msg.sender === 'user';

            // Shared user bubble (all themes use right-aligned cool/neutral bubble)
            if (isUser) {
              // Brutalist user bubble keeps mono font feel
              if (currentStyle === 'brutalist') {
                return (
                  <div key={msg.id} className="flex justify-end">
                    <div className="max-w-[68%] border border-[rgba(255,255,255,0.08)] bg-[rgba(120,140,170,0.10)] p-3 font-mono text-[12px] text-foreground" style={{ borderRadius: '12px 12px 4px 12px' }}>
                      <p className="whitespace-pre-line leading-relaxed">{msg.text}</p>
                      <div className="text-[9px] text-subtle-foreground mt-2 text-right">{msg.timestamp}</div>
                    </div>
                  </div>
                );
              }
              // Quartz + Linear: same premium subtle bubble
              return (
                <div key={msg.id} className="flex justify-end">
                  <div className="max-w-[68%]">
                    <div
                      className="px-4 py-2.5 text-foreground text-[12.5px] leading-relaxed font-sans whitespace-pre-line"
                      style={{
                        background: 'rgba(120,140,170,0.10)',
                        border: '1px solid rgba(255,255,255,0.08)',
                        borderRadius: '12px 12px 4px 12px',
                      }}
                    >
                      {msg.text}
                    </div>
                    <div className="text-[9px] text-subtle-foreground font-mono mt-1 text-right select-none">{msg.timestamp}</div>
                  </div>
                </div>
              );
            }

            // Linear Layout Style (non-user)
            if (currentStyle === 'linear') {
              return (
                <div key={msg.id} className="flex items-start gap-4">
                  <SpawnAvatar seed={msg.senderName} size={28} />
                  <div className="flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-foreground font-sans">{msg.senderName}</span>
                      <span className="text-[9px] text-subtle-foreground font-mono">{msg.timestamp}</span>
                    </div>
                    <div className="text-xs text-foreground leading-relaxed font-sans">
                      <MessageBody text={msg.text} streaming={msg.id === '__streaming__'} hasMessageActions={false} className="[&>*:first-child]:mt-0 [&>*:last-child]:mb-0" />
                    </div>

                    {/* Tool execution logs inside direct messages */}
                    {msg.toolActivity && (
                      <div className="mt-3 bg-surface border border-border rounded-xl p-4 font-mono text-[10.5px]">
                        <div className="flex items-center gap-2 text-muted-foreground mb-2">
                          <RefreshCcw className="animate-spin w-3.5 h-3.5 text-primary" />
                          <span className="flex items-center gap-1">
                            {getIcon(msg.toolActivity.toolName.toLowerCase().replace(/\s+/g, '-') || msg.toolActivity.emoji, 'w-3 h-3')}
                            {msg.toolActivity.toolName} completed:
                          </span>
                        </div>
                        <p className="text-foreground text-[10.5px] whitespace-pre-line border-l-2 border-primary pl-3 py-1 bg-foreground/[0.01]">
                          {msg.toolActivity.outputSummary}
                        </p>
                        {/* 🔒 SECURITY: artifactChart/artifactSvg are populated ONLY from the backend render_chart tool_result frame — never LLM text. */}
                        {msg.toolActivity?.artifactChart && (
                          <EChart option={msg.toolActivity.artifactChart} className="tool-chart" />
                        )}
                        {msg.toolActivity?.artifactSvg && (
                          <div className="tool-chart" dangerouslySetInnerHTML={{ __html: msg.toolActivity.artifactSvg }} />
                        )}
                        {msg.toolActivity?.artifactPptx && (
                          <DeckDownloadCard {...msg.toolActivity.artifactPptx} />
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            }

            // Quartz Theme Style (non-user)
            if (currentStyle === 'quartz') {
              return (
                <div key={msg.id} className="flex items-start gap-4">
                  <SpawnAvatar seed={msg.senderName} size={32} className="shadow" />
                  <div className="max-w-xl p-4 rounded-2xl bg-surface/80 border border-border-strong/50 text-foreground shadow-xl relative">
                    <div className="flex items-center gap-2 mb-1.5 select-none opacity-80">
                      <span className="text-[10px] font-bold font-mono tracking-widest uppercase">{msg.senderName}</span>
                      <span className="text-[9px] font-mono">{msg.timestamp}</span>
                    </div>
                    <MessageBody text={msg.text} streaming={msg.id === '__streaming__'} hasMessageActions={false} className="text-xs text-foreground font-sans leading-relaxed [&>*:first-child]:mt-0 [&>*:last-child]:mb-0" />

                    {/* Tool Activities */}
                    {msg.toolActivity && (
                      <div className="mt-3 bg-surface border border-border rounded-xl overflow-hidden font-mono text-[10.5px]">
                        <div className="px-3 py-1.5 bg-background border-b border-border text-muted-foreground flex items-center gap-1.5">
                          {getIcon(msg.toolActivity.toolName.toLowerCase().replace(/\s+/g, '-') || msg.toolActivity.emoji, 'w-3 h-3')}
                          {msg.toolActivity.toolName}
                        </div>
                        <div className="p-3 text-foreground whitespace-pre-line leading-relaxed">
                          {msg.toolActivity.outputSummary}
                        </div>
                        {/* 🔒 SECURITY: artifactChart/artifactSvg are populated ONLY from the backend render_chart tool_result frame — never LLM text. */}
                        {msg.toolActivity?.artifactChart && (
                          <EChart option={msg.toolActivity.artifactChart} className="tool-chart" />
                        )}
                        {msg.toolActivity?.artifactSvg && (
                          <div className="tool-chart" dangerouslySetInnerHTML={{ __html: msg.toolActivity.artifactSvg }} />
                        )}
                        {msg.toolActivity?.artifactPptx && (
                          <DeckDownloadCard {...msg.toolActivity.artifactPptx} />
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            }

            // Brutalist Style (non-user)
            return (
              <div
                key={msg.id}
                className="border-2 border-primary/60 p-4 font-mono text-[12px] bg-background shadow-[3px_3px_0px_rgba(255,142,36,0.3)]"
              >
                <div className="flex items-center justify-between pb-1.5 border-b border-dashed border-border mb-2">
                  <span className="text-primary font-bold flex items-center gap-1">
                    [<SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5 inline-block" />] {msg.senderName.toUpperCase()}
                  </span>
                  <span className="text-subtle-foreground text-[10px]">{msg.timestamp}</span>
                </div>
                <div className="leading-relaxed">
                  <MessageBody text={msg.text} streaming={msg.id === '__streaming__'} hasMessageActions={false} className="text-foreground [&>*:first-child]:mt-0 [&>*:last-child]:mb-0" />
                </div>

                {msg.toolActivity && (
                  <div className="mt-3 border border-primary/40 p-2 text-[11px] bg-background">
                    <div className="text-warning mb-1">STDOUT RESULT &gt; {msg.toolActivity.toolName}</div>
                    <p className="text-foreground">{msg.toolActivity.outputSummary}</p>
                    {/* 🔒 SECURITY: artifactChart/artifactSvg are populated ONLY from the backend render_chart tool_result frame — never LLM text. */}
                    {msg.toolActivity?.artifactChart && (
                      <EChart option={msg.toolActivity.artifactChart} className="tool-chart" />
                    )}
                    {msg.toolActivity?.artifactSvg && (
                      <div className="tool-chart" dangerouslySetInnerHTML={{ __html: msg.toolActivity.artifactSvg }} />
                    )}
                    {msg.toolActivity?.artifactPptx && (
                      <DeckDownloadCard {...msg.toolActivity.artifactPptx} />
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {/* No dead air: live progress from SEND to stream_end — tool steps as they
              happen + scramble phase line + elapsed timer (Claude-Code-style). */}
          {streaming && (
            <div className="flex items-start gap-3 pl-1 py-1">
              <SpawnAvatar seed={spawn.name} size={24} />
              <LiveActivity
                steps={toolStepsRef.current}
                startedAt={workStartedAt}
                phrases={[t('working.summon'), t('working.context'), t('working.tools'), t('working.compose')]}
              />
            </div>
          )}
        </div>

      </div>

      {/* Message input bar */}
      <div className="p-4 border-t border-border/80 relative z-10 bg-background/40 backdrop-blur">
        <form onSubmit={handleSendMessage} className="max-w-3xl mx-auto select-none">
          <div
            className={`composer-box${attach.dragActive ? ' composer-box--drop' : ''}`}
            {...attach.dndHandlers}
          >
            <AttachChips attachments={attachments} onRemove={attach.removeAt} />
            <input
              type="text"
              value={inputValue}
              onChange={(e) => { setInputValue(e.target.value); attach.onInputChange(e.target.value); }}
              onPaste={attach.onPaste}
              disabled={streaming}
              placeholder={streaming ? t('spawn_chat.placeholder_working', { name: spawn.name }) : t('spawn_chat.placeholder_input')}
              className="w-full bg-transparent text-xs text-foreground placeholder-subtle-foreground focus:outline-none font-sans px-1 py-1.5 disabled:opacity-60"
            />
            <div className="composer-row">
              <AttachControl busy={attach.busy} onPickFiles={attach.addFiles} />
              <button
                type="submit"
                disabled={streaming || !inputValue.trim()}
                className={`p-2 rounded-lg transition-all ${
                  inputValue.trim() && !streaming
                    ? 'bg-primary text-primary-foreground hover:bg-primary-hover'
                    : 'bg-foreground/[0.02] text-subtle-foreground'
                }`}
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
            {attach.dragActive && <div className="composer-drop-hint">{t('attach.drop_hint')}</div>}
          </div>
          {attach.error && <div className="attach-error mt-1.5" role="alert">{attach.error}</div>}
        </form>
      </div>

    </div>
  );
}
