import { useState, useEffect, useCallback } from 'react';
import { Trash2, Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import type { KnowledgeSource } from '../api/client.types';

export default function SpawnRailKnowledge({ spawnId }: { spawnId: number }) {
  const { t } = useTranslation();
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [text, setText] = useState('');

  const refresh = useCallback(() => {
    api.getKnowledge(spawnId).then(setSources).catch(() => setSources([]));
  }, [spawnId]);

  useEffect(() => { refresh(); }, [refresh]);

  const add = async () => {
    if (!text.trim()) return;
    await api.ingestKnowledgeText(spawnId, 'note', text);
    setText('');
    refresh();
  };

  const remove = async (source: string) => {
    await api.deleteKnowledge(spawnId, source);
    refresh();
  };

  return (
    <div className="p-5 border-b border-border/50 space-y-3">
      <span className="text-[10px] font-mono text-foreground uppercase tracking-wider font-bold">
        {t('spawn.knowledge_panel', { defaultValue: '知识库' })}
      </span>
      <div className="space-y-1.5">
        {sources.length === 0 ? (
          <p className="text-[9px] font-mono text-subtle-foreground italic">
            {t('spawn.knowledge_empty', { defaultValue: '暂无知识源' })}
          </p>
        ) : sources.map((s) => (
          <div key={s.source} className="flex items-center justify-between text-[10px] font-mono bg-background/60 rounded px-2 py-1">
            <span className="truncate">{s.source}{s.chunks != null ? ` · ${s.chunks}` : ''}</span>
            <button
              onClick={() => remove(s.source)}
              className="text-subtle-foreground hover:text-danger ml-1 flex-shrink-0"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-1">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('spawn.knowledge_placeholder', { defaultValue: '喂一段文本…' })}
          className="flex-1 bg-background border border-border-strong rounded px-2 py-1 text-[10px] focus:outline-none"
        />
        <button
          onClick={add}
          className="px-2 rounded bg-primary/10 text-primary"
        >
          <Plus className="w-3 h-3" />
        </button>
      </div>
    </div>
  );
}
