import { useState, useEffect, useCallback } from 'react';
import { Trash2, Plus, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import type { KnowledgeSource, CollectionOut } from '../api/client.types';

export default function SpawnRailKnowledge({ spawnId }: { spawnId: number }) {
  const { t } = useTranslation();
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [text, setText] = useState('');
  const [collections, setCollections] = useState<CollectionOut[]>([]);
  const [bindTarget, setBindTarget] = useState('');

  const refresh = useCallback(() => {
    api.getKnowledge(spawnId).then(setSources).catch(() => setSources([]));
  }, [spawnId]);

  const refreshCollections = useCallback(() => {
    api.listCollections().then(setCollections).catch(() => setCollections([]));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { refreshCollections(); }, [refreshCollections]);

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

  const bound = collections.filter((c) => c.spawn_ids.includes(spawnId));
  const unbound = collections.filter((c) => !c.spawn_ids.includes(spawnId));

  const bind = async (cid: number) => {
    if (!cid) return;
    await api.bindCollection(spawnId, cid);
    setBindTarget('');
    refreshCollections();
  };

  const unbind = async (cid: number) => {
    await api.unbindCollection(spawnId, cid);
    refreshCollections();
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

      {/* Bound shared collections — small entry into the Second Brain layer. */}
      <div className="pt-2 border-t border-border/40 space-y-1.5">
        <span className="text-[10px] font-mono text-foreground uppercase tracking-wider font-bold">
          {t('spawn.shared_collections', { defaultValue: '共享库' })}
        </span>
        <div className="flex flex-wrap gap-1">
          {bound.length === 0 ? (
            <p className="text-[9px] font-mono text-subtle-foreground italic">
              {t('spawn.shared_collections_empty', { defaultValue: '未绑定共享库' })}
            </p>
          ) : bound.map((c) => (
            <span
              key={c.id}
              className="flex items-center gap-1 rounded-full border border-primary/40 bg-primary/10 text-primary px-2 py-0.5 text-[9px] font-mono"
            >
              {c.name}
              <button onClick={() => unbind(c.id)} className="hover:text-danger">
                <X className="w-2.5 h-2.5" />
              </button>
            </span>
          ))}
        </div>
        {unbound.length > 0 && (
          <select
            value={bindTarget}
            onChange={(e) => bind(Number(e.target.value))}
            className="w-full bg-background border border-border-strong rounded px-2 py-1 text-[10px] focus:outline-none"
          >
            <option value="">{t('spawn.shared_collections_bind', { defaultValue: '绑定共享库…' })}</option>
            {unbound.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}
