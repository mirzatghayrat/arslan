import React, { useState, useRef, useEffect } from 'react';
import {
  Send, Sparkles, Terminal, Wrench, BookOpen,
  Cpu, CheckCircle2, Clock, Play, User, RefreshCcw, Info
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Message, Spawn } from '../types';
import { TOOLS, SKILLS } from '../data';
import SFSymbol from './SFSymbol';
import Markdown from './Markdown';
import { getIcon } from './iconMap';
import { SandboxBackdrop } from './SandboxBackdrop';

interface SpawnDirectChatProps {
  spawn: Spawn;
  chatHistory: Message[];
  setChatHistory: (valueOrFn: React.SetStateAction<Message[]>) => void;
  currentStyle: 'quartz' | 'brutalist' | 'linear';
}

export default function SpawnDirectChat({
  spawn,
  chatHistory,
  setChatHistory,
  currentStyle
}: SpawnDirectChatProps) {
  const { t } = useTranslation();
  const [inputValue, setInputValue] = useState('');
  const [isSimulating, setIsSimulating] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim() || isSimulating) return;

    const userMsg: Message = {
      id: `msg-direct-user-${Date.now()}`,
      sender: 'user',
      senderName: 'Mirzat',
      senderAvatar: '🦁',
      text: inputValue,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setChatHistory(prev => [...prev, userMsg]);
    setInputValue('');
    setIsSimulating(true);

    // Dynamic responses tailored to spawn specialized domain & tools!
    setTimeout(() => {
      // 1. Tool execution log message
      const toolUsed = spawn.tools[0] || 'web-search';
      const toolMeta = TOOLS.find(t => t.id === toolUsed) || TOOLS[0];
      
      const toolActMsg: Message = {
        id: `msg-direct-tool-${Date.now()}`,
        sender: 'spawn',
        senderName: spawn.name,
        senderAvatar: spawn.avatarEmoji,
        text: `Invoking equipped capability: **${toolMeta.name}** in sandbox environment.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        toolActivity: {
          id: `direct-tool-act-${Date.now()}`,
          toolName: toolMeta.name,
          emoji: toolMeta.emoji,
          status: 'completed',
          action: `Executing custom local query sequence on domain: "${spawn.domain}"`,
          outputSummary: `Sandbox task executed successfully. Extracted state mappings and calculated optimized directives for query: "${userMsg.text}".`,
          collapsed: false
        }
      };
      
      setChatHistory(prev => [...prev, toolActMsg]);

      setTimeout(() => {
        // 2. Specialized response from the spawn itself
        const replyText = `**[${spawn.name} Direct Reply]** Direct specialist analysis completed for your query of *"${userMsg.text}"*.\n\n` + 
          `Applying my specialized training in **${spawn.domain}**. Based on my local model parameters, we should prioritize structured validation across our active equipment pipelines. Let me know what specific sub-parameters to recalibrate next!`;

        const replyMsg: Message = {
          id: `msg-direct-reply-${Date.now()}`,
          sender: 'spawn',
          senderName: spawn.name,
          senderAvatar: spawn.avatarEmoji,
          text: replyText,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        };

        setChatHistory(prev => [...prev, replyMsg]);
        setIsSimulating(false);
      }, 1500);

    }, 1000);
  };

  return (
    <div className="flex-grow flex flex-col h-full overflow-hidden bg-background select-none relative font-sans">
      

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
        </div>
      </div>

      {/* Messages Thread Container */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 relative z-10">
        
        {/* Header Hero card for direct chat — prism halo behind it in the empty state */}
        <div className="relative max-w-3xl mx-auto mb-8">
          {chatHistory.length === 0 && <SandboxBackdrop />}
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
          {chatHistory.map((msg) => {
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
                      <Markdown className="[&>*:first-child]:mt-0 [&>*:last-child]:mb-0">{msg.text}</Markdown>
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
                    <Markdown className="text-xs text-foreground font-sans leading-relaxed [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">{msg.text}</Markdown>

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
                  <Markdown className="text-foreground [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">{msg.text}</Markdown>
                </div>

                {msg.toolActivity && (
                  <div className="mt-3 border border-primary/40 p-2 text-[11px] bg-background">
                    <div className="text-warning mb-1">STDOUT RESULT &gt; {msg.toolActivity.toolName}</div>
                    <p className="text-foreground">{msg.toolActivity.outputSummary}</p>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div ref={bottomRef} className="h-4"></div>
      </div>

      {/* Message input bar */}
      <div className="p-4 border-t border-border/80 relative z-10 bg-background/40 backdrop-blur">
        <form onSubmit={handleSendMessage} className="max-w-3xl mx-auto relative select-none">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            disabled={isSimulating}
            placeholder={isSimulating ? t('spawn_chat.placeholder_working', { name: spawn.name }) : t('spawn_chat.placeholder_input')}
            className="w-full bg-background border border-border-strong focus:border-primary/60 focus:ring-1 focus:ring-ring rounded-xl pl-4 pr-12 py-3.5 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-sans"
          />
          <button
            type="submit"
            disabled={isSimulating || !inputValue.trim()}
            className={`absolute right-2 top-1/2 -translate-y-1/2 p-2 rounded-lg transition-all ${
              inputValue.trim() && !isSimulating
                ? 'bg-primary text-primary-foreground hover:bg-primary-hover'
                : 'bg-foreground/[0.02] text-subtle-foreground'
            }`}
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>

    </div>
  );
}
