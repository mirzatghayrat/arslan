import { useState } from 'react';
import { Download, PanelRightOpen } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import type { StoredArtifact } from '../api/client.types';
import { openArtifact } from '../lib/workDock';

export default function ArtifactDownloads({ files, preview = true }: { files?: StoredArtifact[]; preview?: boolean }) {
  const { t } = useTranslation();
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!files?.length) return null;

  async function download(file: StoredArtifact) {
    setPending(file.filename);
    setError(null);
    try {
      // Never fetch the supplied URL: construct an authenticated same-API route
      // from the validated owner and filename, and download without executing it.
      const blob = await api.downloadRunArtifact(file.run_id, file.filename);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = file.title.split('/').pop() || file.filename;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setError(t('files.downloadFailed'));
    } finally {
      setPending(null);
    }
  }

  return <div className="space-y-2" data-testid="artifact-downloads">
    {files.map(file => <div key={file.filename} className="flex gap-2"><button type="button" disabled={pending !== null}
      onClick={() => download(file)}
      className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2 text-left hover:bg-surface disabled:opacity-50"
      title={`${t('files.download')} · SHA-256 ${file.sha256}`}>
      <Download size={14} className="shrink-0" />
      <span className="min-w-0 flex-1 truncate">{file.title}</span>
      <span className="text-muted-foreground">{Math.max(1, Math.ceil(file.bytes / 1024))} KB</span>
    </button>{preview && <button type="button" className="rounded-lg border border-border p-2 hover:bg-surface" aria-label={t('dock.preview')}
      onClick={() => openArtifact(file)}><PanelRightOpen size={16} /></button>}</div>)}
    {error && <p role="alert" className="text-danger">{error}</p>}
  </div>;
}
