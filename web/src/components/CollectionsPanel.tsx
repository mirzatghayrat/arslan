import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2, ChevronDown, ChevronRight, Upload } from 'lucide-react';
import { api } from '../api/client';
import type { CollectionOut, KnowledgeSource, SpawnSummary } from '../api/client.types';

/**
 * Shared knowledge collections (layer A) management panel, mounted in the
 * "Second Brain" section alongside the orrery. Create/delete collections,
 * expand one to feed it (text/URL paste or file upload), manage its sources,
 * and toggle which spawns are bound to it.
 */
export default function CollectionsPanel({ onChanged }: { onChanged?: () => void }) {
  const { t } = useTranslation();
  const [collections, setCollections] = useState<CollectionOut[]>([]);
  const [spawns, setSpawns] = useState<SpawnSummary[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [newName, setNewName] = useState('');
  const [feedText, setFeedText] = useState('');
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    setCollections(await api.listCollections().catch(() => []));
    setSpawns(await api.listSpawns().catch(() => []));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const openCollection = async (id: number) => {
    if (id === openId) {
      setOpenId(null);
      return;
    }
    setOpenId(id);
    setSources(await api.getCollectionKnowledge(id).catch(() => []));
  };

  const create = async () => {
    const name = newName.trim();
    if (!name) return;
    await api.createCollection(name);
    setNewName('');
    await reload();
    onChanged?.();
  };

  const remove = async (id: number) => {
    await api.deleteCollection(id);
    if (openId === id) setOpenId(null);
    await reload();
    onChanged?.();
  };

  const feed = async (id: number) => {
    const text = feedText.trim();
    if (!text) return;
    setBusy(true);
    try {
      const isUrl = /^https?:\/\//.test(text);
      await api.ingestCollection(id, isUrl ? { url: text } : { source: 'note', text });
      setFeedText('');
      setSources(await api.getCollectionKnowledge(id));
      await reload();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  };

  const feedFile = async (id: number, file: File) => {
    setBusy(true);
    try {
      await api.ingestCollectionFile(id, file);
      setSources(await api.getCollectionKnowledge(id));
      await reload();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  };

  const removeSource = async (id: number, source: string) => {
    await api.deleteCollectionSource(id, source);
    setSources(await api.getCollectionKnowledge(id));
    await reload();
    onChanged?.();
  };

  const toggleBind = async (c: CollectionOut, spawnId: number) => {
    if (c.spawn_ids.includes(spawnId)) {
      await api.unbindCollection(spawnId, c.id);
    } else {
      await api.bindCollection(spawnId, c.id);
    }
    await reload();
    onChanged?.();
  };

  return (
    <div className="p-5 space-y-3 h-full overflow-y-auto">
      <span className="text-[10px] font-mono text-foreground uppercase tracking-wider font-bold">
        {t('brain.collections.title', { defaultValue: '共享资料库' })}
      </span>

      <div className="flex gap-1.5">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && create()}
          placeholder={t('brain.collections.newPlaceholder', { defaultValue: '新建共享资料库…' })}
          className="flex-1 bg-background border border-border-strong rounded px-2 py-1 text-[10px] focus:outline-none"
        />
        <button
          onClick={create}
          className="px-2 rounded bg-primary/10 text-primary"
          aria-label={t('brain.collections.create', { defaultValue: '建库' })}
        >
          <Plus className="w-3 h-3" />
        </button>
      </div>

      {collections.length === 0 ? (
        <p className="text-[9px] font-mono text-subtle-foreground italic">
          {t('brain.collections.empty', { defaultValue: '还没有共享资料库——建一个，再把合同、手册、链接丢进来。' })}
        </p>
      ) : (
        <div className="space-y-1.5">
          {collections.map((c) => (
            <div key={c.id} className="rounded-xl border border-border/50 bg-background/60 overflow-hidden">
              <button
                onClick={() => openCollection(c.id)}
                className="w-full flex items-center justify-between gap-2 px-2.5 py-2 text-left hover:bg-primary/[0.04] transition-colors"
              >
                <span className="flex items-center gap-1.5 min-w-0">
                  {openId === c.id ? (
                    <ChevronDown className="w-3 h-3 shrink-0 text-subtle-foreground" />
                  ) : (
                    <ChevronRight className="w-3 h-3 shrink-0 text-subtle-foreground" />
                  )}
                  <span className="text-[11px] font-sans text-foreground truncate">{c.name}</span>
                </span>
                <span className="text-[9px] font-mono text-subtle-foreground shrink-0">
                  {t('brain.collections.stats', {
                    defaultValue: '{{sources}} 源 · {{chunks}} 块',
                    sources: c.sources,
                    chunks: c.chunks,
                  })}
                </span>
              </button>

              {openId === c.id && (
                <div className="px-2.5 pb-2.5 space-y-2 border-t border-border/40 pt-2">
                  {/* Feed: text/URL + file upload */}
                  <div className="flex gap-1">
                    <input
                      value={feedText}
                      onChange={(e) => setFeedText(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && feed(c.id)}
                      placeholder={t('brain.collections.feedPlaceholder', { defaultValue: '贴文本或 URL 投喂…' })}
                      className="flex-1 bg-background border border-border-strong rounded px-2 py-1 text-[10px] focus:outline-none"
                    />
                    <button
                      onClick={() => feed(c.id)}
                      disabled={busy}
                      className="px-2 rounded bg-primary/10 text-primary disabled:opacity-50"
                    >
                      <Plus className="w-3 h-3" />
                    </button>
                    <label className="px-2 rounded bg-surface-raised text-muted-foreground cursor-pointer flex items-center">
                      <Upload className="w-3 h-3" />
                      <input
                        type="file"
                        className="hidden"
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) feedFile(c.id, file);
                          e.target.value = '';
                        }}
                      />
                    </label>
                  </div>

                  {/* Source list */}
                  <div className="space-y-1">
                    {sources.length === 0 ? (
                      <p className="text-[9px] font-mono text-subtle-foreground italic">
                        {t('brain.collections.noSources', { defaultValue: '暂无知识源' })}
                      </p>
                    ) : sources.map((s) => (
                      <div
                        key={s.source}
                        className="flex items-center justify-between text-[10px] font-mono bg-surface-raised/60 rounded px-2 py-1"
                      >
                        <span className="truncate">{s.source} · {s.chunks}</span>
                        <button
                          onClick={() => removeSource(c.id, s.source)}
                          className="text-subtle-foreground hover:text-danger ml-1 flex-shrink-0"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>

                  {/* Spawn-binding chips */}
                  <div className="flex flex-wrap gap-1">
                    {spawns.map((sp) => {
                      const bound = c.spawn_ids.includes(sp.id);
                      return (
                        <button
                          key={sp.id}
                          onClick={() => toggleBind(c, sp.id)}
                          className={`rounded-full border px-2 py-0.5 text-[9px] font-mono transition-colors ${
                            bound
                              ? 'border-primary/50 text-primary bg-primary/10'
                              : 'border-border text-subtle-foreground hover:border-border-strong'
                          }`}
                        >
                          {sp.name}{bound ? ' ✓' : ''}
                        </button>
                      );
                    })}
                  </div>

                  <button
                    onClick={() => remove(c.id)}
                    className="text-[9px] font-mono text-danger/80 hover:text-danger"
                  >
                    {t('brain.collections.deleteCollection', { defaultValue: '删除整库' })}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
