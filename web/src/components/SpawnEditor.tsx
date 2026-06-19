import React, { useState } from 'react';
import { Spawn, Tool, Skill } from '../types';
import { TOOLS, SKILLS } from '../data';
import {
  ArrowLeft, Sliders, Wrench, BookOpen, Lock,
  Check, Save, RefreshCw, Sparkles, Volume2, ShieldAlert
} from 'lucide-react';
import SFSymbol from './SFSymbol';
import { getIcon } from './iconMap';

interface SpawnEditorProps {
  spawnId: string;
  spawns: Spawn[];
  setSpawns: React.Dispatch<React.SetStateAction<Spawn[]>>;
  onBack: () => void;
}

export default function SpawnEditor({
  spawnId,
  spawns,
  setSpawns,
  onBack
}: SpawnEditorProps) {
  const spawn = spawns.find(s => s.id === spawnId);
  if (!spawn) {
    return (
      <div className="p-6 text-white text-sans">
        <button onClick={onBack} className="text-xs text-[#FF8E24] hover:underline flex items-center gap-1">
          <ArrowLeft className="w-4 h-4" /> Go back
        </button>
        <p className="mt-4">Spawn not found.</p>
      </div>
    );
  }

  // Local state for active selections
  const [selectedTools, setSelectedTools] = useState<string[]>(spawn.tools);
  const [selectedSkills, setSelectedSkills] = useState<string[]>(spawn.skills);
  const [isSaved, setIsSaved] = useState(false);

  const handleToggleTool = (toolId: string, isLocked: boolean) => {
    if (isLocked) return; // Locked tools cannot be assigned

    setSelectedTools(prev => {
      if (prev.includes(toolId)) {
        return prev.filter(id => id !== toolId);
      } else {
        return [...prev, toolId];
      }
    });
  };

  const handleToggleSkill = (skillId: string, isLocked: boolean) => {
    if (isLocked) return; // Locked skills cannot be assigned

    setSelectedSkills(prev => {
      if (prev.includes(skillId)) {
        return prev.filter(id => id !== skillId);
      } else {
        return [...prev, skillId];
      }
    });
  };

  const handleSave = () => {
    setSpawns(prevSpawns => {
      return prevSpawns.map(s => {
        if (s.id === spawnId) {
          return {
            ...s,
            tools: selectedTools,
            skills: selectedSkills
          };
        }
        return s;
      });
    });

    setIsSaved(true);
    setTimeout(() => {
      setIsSaved(false);
    }, 2000);
  };

  return (
    <div className="flex-1 overflow-y-auto bg-[#0d0f15] p-8 select-none relative">
      {/* Absolute Ambient lights */}
      <div className="absolute top-1/2 left-1/2 w-[30rem] h-[30rem] bg-[#FF8E24]/[0.02] blur-[120px] rounded-full pointer-events-none -translate-x-1/2 -translate-y-1/2"></div>

      {/* Back button link header */}
      <div className="mb-6">
        <button
          id="editor-back-link"
          onClick={onBack}
          className="text-xs text-gray-400 hover:text-white transition-colors flex items-center gap-1.5 font-sans"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to active spawns ledger</span>
        </button>
      </div>

      {/* Spawn profile details */}
      <div className="bg-gradient-to-r from-[#121622] to-[#0a0c10] border border-[#1e2330] rounded-2xl p-6 mb-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative overflow-hidden group">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-orange-950/20 border border-[#FF8E24]/30 flex items-center justify-center text-sm shadow-inner shadow-[#FF8E24]/10 select-none">
            <SFSymbol nameOrEmoji={spawn.avatarEmoji} className="w-6 h-6 text-[#FF8E24]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-white font-sans">{spawn.name}</h1>
              <span className="text-[9px] bg-[#FF8E24]/15 text-[#FF8E24] border border-[#FF8E24]/30 px-2 py-0.5 rounded font-bold font-mono uppercase tracking-wider scale-95">
                Active Slot
              </span>
            </div>
            <p className="text-xs text-gray-400 font-mono mt-0.5">{spawn.domain}</p>
            <p className="text-xs text-gray-500 font-sans mt-2 max-w-2xl leading-relaxed">
              {spawn.description}
            </p>
          </div>
        </div>

        {/* Action controls */}
        <div className="flex items-center gap-3 shrink-0 self-end md:self-center">
          <button
            id="editor-save-trigger"
            onClick={handleSave}
            className={`px-4 py-2 text-xs font-bold font-sans uppercase rounded-lg transition-all flex items-center gap-1.5 ${
              isSaved
                ? 'bg-emerald-600 hover:bg-emerald-700 text-white'
                : 'bg-[#FF8E24] hover:bg-[#ff9c3a] text-black shadow-lg shadow-[#FF8E24]/15'
            }`}
          >
            {isSaved ? (
              <>
                <Check className="w-4 h-4 text-white" /> Saved successfully!
              </>
            ) : (
              <>
                <Save className="w-4 h-4" /> Commit settings
              </>
            )}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        
        {/* Active Tools column */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold font-mono tracking-widest text-[#FF8E24] uppercase flex items-center gap-1.5">
              <Wrench className="w-4 h-4" /> 
              <span>Equip Tools Library</span>
            </h3>
            <span className="text-[10px] font-mono text-gray-500 uppercase">
              {spawn.tools.length} assigned
            </span>
          </div>

          <div className="space-y-3">
            {TOOLS.map(tool => {
              const isAssigned = selectedTools.includes(tool.id);
              const isLocked = tool.category === 'advanced_locked';

              return (
                <div
                  key={tool.id}
                  onClick={() => handleToggleTool(tool.id, isLocked)}
                  className={`border rounded-xl p-4 transition-all flex items-center justify-between relative ${
                    isLocked
                      ? 'bg-gray-950/40 border-gray-900/60 opacity-60 cursor-not-allowed'
                      : isAssigned
                      ? 'bg-gradient-to-r from-[#FF8E24]/10 to-[#FF8E24]/5 border-[#FF8E24]/40 cursor-pointer hover:border-[#FF8E24]/60'
                      : 'bg-[#0f121d] border-[#1e2330] hover:border-[#2d344a] cursor-pointer'
                  }`}
                >
                  <div className="flex items-start gap-3 flex-1 pr-4">
                    <span className="pt-0.5 select-none flex items-center">
                      {getIcon(tool.id, 'w-5 h-5 text-gray-300')}
                    </span>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <h4 className="text-xs font-bold text-white font-sans">{tool.name}</h4>
                        <span className={`text-[9px] font-mono px-1.5 py-0.2 rounded ${
                          tool.tier === 'tier-1' 
                            ? 'bg-emerald-950/15 text-emerald-400 border border-emerald-950/30'
                            : tool.tier === 'tier-2'
                            ? 'bg-blue-950/20 text-blue-400 border border-blue-950/40'
                            : 'bg-red-950/25 text-red-400 border border-red-950/40'
                        }`}>
                          {tool.tier}
                        </span>
                      </div>
                      <p className="text-[11px] text-gray-400 font-sans leading-relaxed">
                        {tool.description}
                      </p>
                    </div>
                  </div>

                  {/* Standard locked state representation */}
                  {isLocked ? (
                    <div className="flex flex-col items-center gap-1 shrink-0 bg-red-950/10 border border-red-900/30 p-2 rounded-lg text-[9px] font-mono text-red-500 font-bold uppercase">
                      <Lock className="w-3.5 h-3.5 text-red-500" />
                      Locked
                    </div>
                  ) : (
                    <div className={`w-5 h-5 rounded-md border flex items-center justify-center transition-colors ${
                      isAssigned 
                        ? 'bg-[#FF8E24] border-[#FF8E24] text-black' 
                        : 'border-gray-700 bg-black/40 group-hover:border-gray-500'
                    }`}>
                      {isAssigned && <Check className="w-3.5 h-3.5 font-bold text-black" />}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Active Skills column */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold font-mono tracking-widest text-[#FF8E24] uppercase flex items-center gap-1.5">
              <BookOpen className="w-4 h-4" /> 
              <span>Equip Cognitive Skills</span>
            </h3>
            <span className="text-[10px] font-mono text-gray-500 uppercase">
              {spawn.skills.length} assigned
            </span>
          </div>

          <div className="space-y-3">
            {SKILLS.map(skill => {
              const isAssigned = selectedSkills.includes(skill.id);
              const isLocked = skill.category === 'advanced_locked';

              return (
                <div
                  key={skill.id}
                  onClick={() => handleToggleSkill(skill.id, isLocked)}
                  className={`border rounded-xl p-4 transition-all flex items-center justify-between relative ${
                    isLocked
                      ? 'bg-gray-950/40 border-gray-900/60 opacity-60 cursor-not-allowed'
                      : isAssigned
                      ? 'bg-gradient-to-r from-amber-600/[0.08] to-amber-600/[0.03] border-amber-500/40 cursor-pointer hover:border-amber-500/60'
                      : 'bg-[#0f121d] border-[#1e2330] hover:border-[#2d344a] cursor-pointer'
                  }`}
                >
                  <div className="flex items-start gap-3 flex-1 pr-4">
                    <span className="pt-0.5 select-none flex items-center">
                      {getIcon(skill.id, 'w-5 h-5 text-amber-400')}
                    </span>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <h4 className="text-xs font-bold text-white font-sans">{skill.name}</h4>
                        {isLocked && (
                          <span className="text-[8px] bg-red-950/30 text-red-500 font-mono px-1 border border-red-900/40 uppercase">
                            Restrictive
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-gray-400 font-sans leading-relaxed">
                        {skill.description}
                      </p>
                    </div>
                  </div>

                  {/* Standard locked state representation */}
                  {isLocked ? (
                    <div className="flex flex-col items-center gap-1 shrink-0 bg-red-950/10 border border-red-900/30 p-2 rounded-lg text-[9px] font-mono text-red-500 font-bold uppercase">
                      <Lock className="w-3.5 h-3.5 text-red-500" />
                      Locked
                    </div>
                  ) : (
                    <div className={`w-5 h-5 rounded-md border flex items-center justify-center transition-colors ${
                      isAssigned 
                        ? 'bg-amber-600 border-amber-600 text-white' 
                        : 'border-gray-700 bg-black/40'
                    }`}>
                      {isAssigned && <Check className="w-3.5 h-3.5 font-bold text-white" />}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Security alert footnote */}
          <div className="bg-red-950/10 rounded-xl p-4 border border-red-900/30 text-[11px] leading-relaxed text-red-400 space-y-1 font-sans">
            <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider">
              <ShieldAlert className="w-4 h-4 text-red-400" />
              <span>Daemon Security Policy Restricted Scope</span>
            </div>
            <p>
              Under self-hosted client credentials, Tier-3 advanced tools (🔒) are locked behind standard security sandboxing bounds. Host directory integrations are restricted to local virtual directories to prevent malicious root execution commands from remote nodes.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
