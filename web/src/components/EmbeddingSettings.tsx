import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { RefreshCw, Download } from 'lucide-react';
import { api } from '../api/client';
import type { EmbeddingStatus, ProviderConfig } from '../api/client.types';
import Select from './Select';

const LOCAL_MODEL_LABEL: Record<string, string> = {
  absent: 'notDownloaded',
  downloading: 'downloading',
  ready: 'ready',
  error: 'error',
};

interface EmbeddingSettingsProps {
  /** Saved multi-model provider configs, for the override select (only embedding-capable ones make sense, but we list all — same as the provider picker elsewhere). */
  providerConfigs: ProviderConfig[];
  /** Current override value ("" = auto). */
  embeddingConfigId: string;
  /** Called when the user changes the override select. */
  onEmbeddingConfigIdChange: (value: string) => void;
}

/**
 * Settings · Embedding subsection: shows the active embedding provider/model
 * (or a hint when none is configured), embedded/pending chunk counts with a
 * reindex trigger, local (offline) model download status, and an override
 * select for which provider config backs embeddings. Polls status every 4s
 * while mounted so reindex/download progress updates live.
 */
export default function EmbeddingSettings({
  providerConfigs,
  embeddingConfigId,
  onEmbeddingConfigIdChange,
}: EmbeddingSettingsProps) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<EmbeddingStatus | null>(null);
  const [reindexBusy, setReindexBusy] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState(false);

  const reload = useCallback(async () => {
    setStatus(await api.embeddingStatus().catch(() => null));
  }, []);

  useEffect(() => {
    reload();
    const timer = setInterval(reload, 4000);
    return () => clearInterval(timer);
  }, [reload]);

  const handleReindex = async () => {
    setReindexBusy(true);
    try {
      await api.reindexEmbeddings();
      await reload();
    } finally {
      setReindexBusy(false);
    }
  };

  const handleDownload = async () => {
    setDownloadBusy(true);
    try {
      await api.downloadEmbeddingModel();
      await reload();
    } finally {
      setDownloadBusy(false);
    }
  };

  const localStatusLabel = (s: EmbeddingStatus['local_model']) => {
    const key = LOCAL_MODEL_LABEL[s.status] ?? s.status;
    if (key === 'error') {
      return t('settings.embeddingLocalError', {
        defaultValue: '失败：{{error}}',
        error: s.error ?? '',
      });
    }
    return t(`settings.embeddingLocal_${key}`, {
      defaultValue: { notDownloaded: '未下载', downloading: '下载中…', ready: '已就绪' }[key] ?? s.status,
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 pb-1">
        <h4 className="text-xs font-bold text-foreground font-sans">
          {t('settings.sectionEmbedding', { defaultValue: '语义检索（Embedding）' })}
        </h4>
      </div>

      {!status ? (
        <p className="text-[11px] text-subtle-foreground font-sans">
          {t('settings.embeddingLoading', { defaultValue: '正在加载…' })}
        </p>
      ) : (
        <>
          <p className="text-[11px] text-muted-foreground font-sans leading-relaxed">
            {status.model
              ? t('settings.embeddingActive', {
                  defaultValue: '当前：{{model}} · 自动选择，可在下方覆盖',
                  model: status.model,
                })
              : t('settings.embeddingNotEnabled', {
                  defaultValue: '未启用——配一把智谱/千问/OpenAI 的 key，或下载本地模型，即可开启语义检索（纯关键词检索仍可用）',
                })}
          </p>

          {/* Backfill counts + reindex trigger */}
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11px] font-mono text-muted-foreground">
              {t('settings.embeddingCounts', {
                defaultValue: '已嵌 {{embedded}} / 待嵌 {{pending}}',
                embedded: status.embedded,
                pending: status.pending,
              })}
            </span>
            <button
              type="button"
              disabled={status.reindex.running || !status.model || reindexBusy}
              onClick={handleReindex}
              className="px-3 py-1.5 text-[10.5px] font-mono font-medium rounded-lg bg-surface-raised text-foreground border border-border hover:border-primary/40 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
            >
              <RefreshCw className={`w-3 h-3 ${status.reindex.running ? 'animate-spin' : ''}`} />
              {status.reindex.running
                ? t('settings.embeddingReindexing', {
                    defaultValue: '重建中 {{done}}/{{total}}',
                    done: status.reindex.done,
                    total: status.reindex.total,
                  })
                : t('settings.embeddingReindex', { defaultValue: '重建索引' })}
            </button>
          </div>
          {status.reindex.error && (
            <p className="text-[10px] text-danger font-mono">{status.reindex.error}</p>
          )}

          {/* Local model download */}
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11px] font-mono text-muted-foreground">
              {t('settings.embeddingLocalLabel', { defaultValue: '本地模型（离线，无需 key）：' })}
              {' '}{localStatusLabel(status.local_model)}
            </span>
            {status.local_model.status !== 'ready' && status.local_model.status !== 'downloading' && (
              <button
                type="button"
                disabled={downloadBusy}
                onClick={handleDownload}
                className="px-3 py-1.5 text-[10.5px] font-mono font-medium rounded-lg bg-surface-raised text-foreground border border-border hover:border-primary/40 disabled:opacity-50 transition-colors flex items-center gap-1.5"
              >
                <Download className="w-3 h-3" />
                {t('settings.embeddingDownload', { defaultValue: '下载（~120MB）' })}
              </button>
            )}
          </div>

          {/* Override select — which provider config backs embeddings (mirrors the synthesis-config-style pattern: auto / local / each saved provider config). */}
          <div className="space-y-1.5 pt-1">
            <label
              htmlFor="settings-embedding-config"
              className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide"
            >
              {t('settings.embeddingOverrideLabel', { defaultValue: 'Embedding 供应商覆盖' })}
            </label>
            <Select
              id="settings-embedding-config"
              value={embeddingConfigId}
              onChange={onEmbeddingConfigIdChange}
              options={[
                { value: '', label: t('settings.embeddingAuto', { defaultValue: '自动（推荐）' }) },
                { value: 'local', label: t('settings.embeddingLocalOption', { defaultValue: '本地模型' }) },
                ...providerConfigs.map((c) => ({
                  value: String(c.id),
                  label: `${c.label || c.provider} (${c.model})`,
                })),
              ]}
              className="max-w-sm"
              ariaLabel={t('settings.embeddingOverrideLabel', { defaultValue: 'Embedding 供应商覆盖' })}
            />
          </div>
        </>
      )}
    </div>
  );
}
