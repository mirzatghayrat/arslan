import React, { useState, useRef, useEffect } from 'react';
import {
  Send, Sparkles, Terminal, Wrench, BookOpen,
  Cpu, CheckCircle2, Clock, Play, User, RefreshCcw, Info
} from 'lucide-react';
import { Message, Spawn } from '../types';
import { TOOLS, SKILLS } from '../data';
import SFSymbol from './SFSymbol';
import { getIcon } from './iconMap';

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
    <div className="flex-grow flex flex-col h-full overflow-hidden bg-[#0d0f15] select-none relative font-sans">
      
      {/* Dynamic Background Grid overlay depending on theme */}
      {currentStyle === 'brutalist' && (
        <div className="absolute inset-0 bg-[radial-gradient(#ff8e24_0.75px,transparent_0.75px)] [background-size:16px_16px] opacity-[0.03] pointer-events-none z-0"></div>
      )}
      {currentStyle === 'linear' && (
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#1f2937_1px,transparent_1px),linear-gradient(to_bottom,#1f2937_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] opacity-[0.1] pointer-events-none z-0"></div>
      )}

      {/* Spawn Header details */}
      <div className={`px-6 py-4 flex items-center justify-between border-b border-[#1e2330]/80 relative z-10 bg-[#0a0c10]/80 backdrop-blur`}>
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-orange-500/10 border border-orange-500/20 flex items-center justify-center text-sm">
            <SFSymbol nameOrEmoji={spawn.avatarEmoji} className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xs font-bold font-mono tracking-widest text-white uppercase">{spawn.name} Direct Channel</h2>
            </div>
            <p className="text-[10px] text-gray-500 mt-0.5 font-sans">
              Specialist assigned to field: <span className="text-gray-300 font-medium">{spawn.domain}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
        </div>
      </div>

      {/* Messages Thread Container */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 relative z-10">
        
        {/* Header Hero card for direct chat */}
        <div className="max-w-3xl mx-auto bg-[#121622]/40 border border-[#1e2330]/80 rounded-2xl p-6 mb-8 text-center space-y-4">
          <span className="inline-block p-4 bg-[#FF8E24]/5 rounded-2xl border border-[#FF8E24]/10">
            <SFSymbol nameOrEmoji={spawn.avatarEmoji} className="w-8 h-8 text-[#FF8E24]" />
          </span>
          <div className="space-y-1">
            <h3 className="text-sm font-bold text-white font-sans flex items-center justify-center gap-2">
              <span>{spawn.name}</span>
            </h3>
            <p className="text-xs text-gray-400 max-w-lg mx-auto font-sans leading-relaxed">
              {spawn.description}
            </p>
          </div>
          
          <div className="h-[1px] bg-[#1e2330]/50 max-w-md mx-auto"></div>

          {/* Capabilities Badges */}
          <div className="flex flex-wrap items-center justify-center gap-2 max-w-xl mx-auto pt-1">
            {spawn.tools.map(tId => {
              const tool = TOOLS.find(t => t.id === tId) || { name: tId };
              return (
                <span key={tId} className="px-2 py-0.8 bg-[#181a28] border border-[#23293e] text-[10px] font-mono text-gray-300 rounded-lg flex items-center gap-1">
                  {getIcon(tId, 'w-3 h-3')}
                  <span>{tool.name}</span>
                </span>
              );
            })}
            {spawn.skills.map(sId => {
              const skill = SKILLS.find(s => s.id === sId) || { name: sId };
              return (
                <span key={sId} className="px-2 py-0.8 bg-[#1f1a14] border border-[#3e2e1e] text-[10px] font-mono text-amber-500 rounded-lg flex items-center gap-1">
                  {getIcon(sId, 'w-3 h-3 text-amber-500')}
                  <span>{skill.name}</span>
                </span>
              );
            })}
          </div>
        </div>

        {/* Individual Messages */}
        <div className="max-w-3xl mx-auto space-y-6">
          {chatHistory.map((msg) => {
            const isUser = msg.sender === 'user';
            
            // Linear Layout Style 
            if (currentStyle === 'linear') {
              return (
                <div key={msg.id} className="border-b border-[#1e2330]/40 pb-5 last:border-0 flex items-start gap-4">
                  <div className="w-7 h-7 rounded-lg bg-[#161924] border border-gray-800 flex items-center justify-center text-xs">
                    <SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5" />
                  </div>
                  <div className="flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-white font-sans">{msg.senderName}</span>
                      <span className="text-[9px] text-gray-500 font-mono">{msg.timestamp}</span>
                    </div>
                    <div className="text-xs text-gray-300 leading-relaxed font-sans whitespace-pre-wrap">
                      {msg.text}
                    </div>

                    {/* Tool execution logs inside direct messages */}
                    {msg.toolActivity && (
                      <div className="mt-3 bg-[#0a0c11] border border-[#1e2330] rounded-xl p-4 font-mono text-[10.5px]">
                        <div className="flex items-center gap-2 text-gray-400 mb-2">
                          <RefreshCcw className="animate-spin w-3.5 h-3.5 text-orange-500" />
                          <span className="flex items-center gap-1">
                            {getIcon(msg.toolActivity.toolName.toLowerCase().replace(/\s+/g, '-') || msg.toolActivity.emoji, 'w-3 h-3')}
                            {msg.toolActivity.toolName} completed:
                          </span>
                        </div>
                        <p className="text-gray-300 text-[10.5px] whitespace-pre-line border-l-2 border-[#FF8E24] pl-3 py-1 bg-white/[0.01]">
                          {msg.toolActivity.outputSummary}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              );
            }

            // Quartz Theme Style
            if (currentStyle === 'quartz') {
              return (
                <div key={msg.id} className={`flex items-start gap-4 ${isUser ? 'justify-end' : ''}`}>
                  {!isUser && (
                    <div className="w-8 h-8 rounded-lg bg-orange-500/10 border border-orange-500/20 flex items-center justify-center text-sm shadow">
                      <SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5" />
                    </div>
                  )}
                  <div className={`max-w-xl p-4 rounded-2xl relative ${
                    isUser 
                      ? 'bg-gradient-to-r from-[#FF8E24] to-amber-500 text-black shadow-lg shadow-orange-500/10' 
                      : 'bg-[#121622]/80 border border-[#23293e]/50 text-gray-100 shadow-xl'
                  }`}>
                    <div className="flex items-center gap-2 mb-1.5 select-none opacity-80">
                      <span className="text-[10px] font-bold font-mono tracking-widest uppercase">{msg.senderName}</span>
                      <span className="text-[9px] font-mono">{msg.timestamp}</span>
                    </div>
                    <p className={`text-xs whitespace-pre-wrap leading-relaxed ${isUser ? 'font-medium' : 'font-sans text-gray-300'}`}>
                      {msg.text}
                    </p>

                    {/* Tool Activities */}
                    {msg.toolActivity && (
                      <div className="mt-3 bg-black/40 border border-white/5 rounded-xl overflow-hidden font-mono text-[10.5px]">
                        <div className="px-3 py-1.5 bg-black/60 border-b border-white/5 text-gray-400 flex items-center gap-1.5">
                          {getIcon(msg.toolActivity.toolName.toLowerCase().replace(/\s+/g, '-') || msg.toolActivity.emoji, 'w-3 h-3')}
                          {msg.toolActivity.toolName}
                        </div>
                        <div className="p-3 text-gray-300 whitespace-pre-line leading-relaxed">
                          {msg.toolActivity.outputSummary}
                        </div>
                      </div>
                    )}
                  </div>
                  {isUser && (
                    <div className="w-8 h-8 rounded-lg bg-[#222736] border border-gray-700 flex items-center justify-center text-sm shadow">
                      <SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5" />
                    </div>
                  )}
                </div>
              );
            }

            // Brutalist Style
            return (
              <div 
                key={msg.id}
                className="border-2 border-orange-500/60 p-4 font-mono text-[12px] bg-[#090b10] shadow-[3px_3px_0px_rgba(255,142,36,0.3)]"
              >
                <div className="flex items-center justify-between pb-1.5 border-b border-dashed border-gray-800 mb-2">
                  <span className="text-[#FF8E24] font-bold flex items-center gap-1">
                    [<SFSymbol nameOrEmoji={msg.senderAvatar} className="w-3.5 h-3.5 inline-block" />] {msg.senderName.toUpperCase()}
                  </span>
                  <span className="text-gray-500 text-[10px]">{msg.timestamp}</span>
                </div>
                <div className="text-gray-200 whitespace-pre-wrap leading-relaxed">{msg.text}</div>

                {msg.toolActivity && (
                  <div className="mt-3 border border-orange-500/40 p-2 text-[11px] bg-[#000]">
                    <div className="text-amber-500 mb-1">STDOUT RESULT &gt; {msg.toolActivity.toolName}</div>
                    <p className="text-gray-300">{msg.toolActivity.outputSummary}</p>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div ref={bottomRef} className="h-4"></div>
      </div>

      {/* Message input bar */}
      <div className="p-4 border-t border-[#1e2330]/80 relative z-10 bg-[#0a0c10]/40 backdrop-blur">
        <form onSubmit={handleSendMessage} className="max-w-3xl mx-auto relative select-none">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            disabled={isSimulating}
            placeholder={isSimulating ? `Specialist ${spawn.name} is working...` : `Task directive direct socket input...`}
            className="w-full bg-[#07090d] border border-[#23293a] focus:border-[#FF8E24]/60 focus:ring-1 focus:ring-[#FF8E24]/20 rounded-xl pl-4 pr-12 py-3.5 text-xs text-white placeholder-gray-600 focus:outline-none transition-all font-sans"
          />
          <button
            type="submit"
            disabled={isSimulating || !inputValue.trim()}
            className={`absolute right-2 top-1/2 -translate-y-1/2 p-2 rounded-lg transition-all ${
              inputValue.trim() && !isSimulating
                ? 'bg-[#FF8E24] text-black hover:bg-[#ff9c3a]'
                : 'bg-white/[0.02] text-gray-600'
            }`}
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </div>

    </div>
  );
}
