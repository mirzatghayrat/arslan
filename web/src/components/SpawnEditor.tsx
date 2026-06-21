import React, { useState } from 'react';
import { Spawn, Tool, Skill } from '../types';
import { TOOLS, SKILLS } from '../data';
import {
  ArrowLeft, Sliders, Wrench, BookOpen, Lock,
  Check, Save, RefreshCw, Sparkles, Volume2, ShieldAlert
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
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
  const { t } = useTranslation();
  const spawn = spawns.find(s => s.id === spawnId);
  if (!spawn) {
    return (
      <div className="p-6 text-foreground text-sans">
        <button onClick={onBack} className="text-xs text-primary hover:underline flex items-center gap-1">
          <ArrowLeft className="w-4 h-4" /> {t('ledger.go_back')}
        </button>
        <p className="mt-4">{t('ledger.spawn_not_found')}</p>
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
    <div className="flex-1 overflow-y-auto bg-background p-8 select-none relative">
      {/* Absolute Ambient lights */}
      <div className="absolute top-1/2 left-1/2 w-[30rem] h-[30rem] bg-primary/[0.02] blur-[120px] rounded-full pointer-events-none -translate-x-1/2 -translate-y-1/2"></div>

      {/* Back button link header */}
      <div className="mb-6">
        <button
          id="editor-back-link"
          onClick={onBack}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1.5 font-sans"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>{t('ledger.back_to_ledger')}</span>
        </button>
      </div>

      {/* Spawn profile details */}
      <div className="bg-gradient-to-r from-surface to-background border border-border rounded-2xl p-6 mb-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative overflow-hidden group">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/30 flex items-center justify-center text-sm shadow-inner shadow-primary/10 select-none">
            <SFSymbol nameOrEmoji={spawn.avatarEmoji} className="w-6 h-6 text-primary" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-foreground font-sans">{spawn.name}</h1>
              <span className="text-[9px] bg-primary/15 text-primary border border-primary/30 px-2 py-0.5 rounded font-bold font-mono uppercase tracking-wider scale-95">
                {t('ledger.active_slot')}
              </span>
            </div>
            <p className="text-xs text-muted-foreground font-mono mt-0.5">{spawn.domain}</p>
            <p className="text-xs text-subtle-foreground font-sans mt-2 max-w-2xl leading-relaxed">
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
                ? 'bg-success hover:bg-success/90 text-primary-foreground'
                : 'bg-primary hover:bg-primary-hover text-primary-foreground shadow-lg shadow-primary/15'
            }`}
          >
            {isSaved ? (
              <>
                <Check className="w-4 h-4 text-primary-foreground" /> {t('ledger.saved_success')}
              </>
            ) : (
              <>
                <Save className="w-4 h-4" /> {t('ledger.commit_settings')}
              </>
            )}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">

        {/* Active Tools column */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold font-mono tracking-widest text-primary uppercase flex items-center gap-1.5">
              <Wrench className="w-4 h-4" />
              <span>{t('ledger.equip_tools')}</span>
            </h3>
            <span className="text-[10px] font-mono text-subtle-foreground uppercase">
              {t('ledger.assigned_count', { count: spawn.tools.length })}
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
                      ? 'bg-background/40 border-border/60 opacity-60 cursor-not-allowed'
                      : isAssigned
                      ? 'bg-gradient-to-r from-primary/10 to-primary/5 border-primary/40 cursor-pointer hover:border-primary/60'
                      : 'bg-surface border-border hover:border-border-strong cursor-pointer'
                  }`}
                >
                  <div className="flex items-start gap-3 flex-1 pr-4">
                    <span className="pt-0.5 select-none flex items-center">
                      {getIcon(tool.id, 'w-5 h-5 text-foreground')}
                    </span>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <h4 className="text-xs font-bold text-foreground font-sans">{tool.name}</h4>
                        <span className={`text-[9px] font-mono px-1.5 py-0.2 rounded ${
                          tool.tier === 'tier-1'
                            ? 'bg-success/15 text-success border border-success/30'
                            : tool.tier === 'tier-2'
                            ? 'bg-info/20 text-info border border-info/40'
                            : 'bg-danger/25 text-danger border border-danger/40'
                        }`}>
                          {tool.tier}
                        </span>
                      </div>
                      <p className="text-[11px] text-muted-foreground font-sans leading-relaxed">
                        {tool.description}
                      </p>
                    </div>
                  </div>

                  {/* Standard locked state representation */}
                  {isLocked ? (
                    <div className="flex flex-col items-center gap-1 shrink-0 bg-danger/10 border border-danger/30 p-2 rounded-lg text-[9px] font-mono text-danger font-bold uppercase">
                      <Lock className="w-3.5 h-3.5 text-danger" />
                      {t('ledger.locked')}
                    </div>
                  ) : (
                    <div className={`w-5 h-5 rounded-md border flex items-center justify-center transition-colors ${
                      isAssigned
                        ? 'bg-primary border-primary text-primary-foreground'
                        : 'border-border-strong bg-background group-hover:border-muted-foreground'
                    }`}>
                      {isAssigned && <Check className="w-3.5 h-3.5 font-bold text-primary-foreground" />}
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
            <h3 className="text-xs font-bold font-mono tracking-widest text-primary uppercase flex items-center gap-1.5">
              <BookOpen className="w-4 h-4" />
              <span>{t('ledger.equip_skills')}</span>
            </h3>
            <span className="text-[10px] font-mono text-subtle-foreground uppercase">
              {t('ledger.assigned_count', { count: spawn.skills.length })}
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
                      ? 'bg-background/40 border-border/60 opacity-60 cursor-not-allowed'
                      : isAssigned
                      ? 'bg-gradient-to-r from-warning/[0.08] to-warning/[0.03] border-warning/40 cursor-pointer hover:border-warning/60'
                      : 'bg-surface border-border hover:border-border-strong cursor-pointer'
                  }`}
                >
                  <div className="flex items-start gap-3 flex-1 pr-4">
                    <span className="pt-0.5 select-none flex items-center">
                      {getIcon(skill.id, 'w-5 h-5 text-warning')}
                    </span>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <h4 className="text-xs font-bold text-foreground font-sans">{skill.name}</h4>
                        {isLocked && (
                          <span className="text-[8px] bg-danger/30 text-danger font-mono px-1 border border-danger/40 uppercase">
                            {t('ledger.restrictive')}
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-muted-foreground font-sans leading-relaxed">
                        {skill.description}
                      </p>
                    </div>
                  </div>

                  {/* Standard locked state representation */}
                  {isLocked ? (
                    <div className="flex flex-col items-center gap-1 shrink-0 bg-danger/10 border border-danger/30 p-2 rounded-lg text-[9px] font-mono text-danger font-bold uppercase">
                      <Lock className="w-3.5 h-3.5 text-danger" />
                      {t('ledger.locked')}
                    </div>
                  ) : (
                    <div className={`w-5 h-5 rounded-md border flex items-center justify-center transition-colors ${
                      isAssigned
                        ? 'bg-warning border-warning text-white'
                        : 'border-border-strong bg-background'
                    }`}>
                      {isAssigned && <Check className="w-3.5 h-3.5 font-bold text-white" />}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Security alert footnote */}
          <div className="bg-danger/10 rounded-xl p-4 border border-danger/30 text-[11px] leading-relaxed text-danger space-y-1 font-sans">
            <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider">
              <ShieldAlert className="w-4 h-4 text-danger" />
              <span>{t('ledger.security_policy_title')}</span>
            </div>
            <p>
              {t('ledger.security_policy_desc')}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
