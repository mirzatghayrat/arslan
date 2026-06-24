import { useState } from "react";
import { Paperclip, X } from "lucide-react";
import { api } from "../api/client";

export interface Attachment { name: string; text: string; chars: number; truncated: boolean; }
interface Props { onChange: (items: Attachment[]) => void; compress?: boolean; }

export default function AttachBar({ onChange, compress = false }: Props) {
  const [items, setItems] = useState<Attachment[]>([]);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function commit(next: Attachment[]) { setItems(next); onChange(next); }

  async function addUrl() {
    if (!url.trim() || busy) return;
    setBusy(true); setError(null);
    try {
      const r = await api.extractAttachmentUrl(url.trim(), compress);
      commit([...items, { name: url.trim(), text: r.text, chars: r.chars, truncated: r.truncated }]);
      setUrl("");
    } catch (e) { setError(String((e as Error).message ?? e)); } finally { setBusy(false); }
  }
  async function addFile(file: File) {
    setBusy(true); setError(null);
    try {
      const r = await api.extractAttachmentFile(file, compress);
      commit([...items, { name: file.name, text: r.text, chars: r.chars, truncated: r.truncated }]);
    } catch (e) { setError(String((e as Error).message ?? e)); } finally { setBusy(false); }
  }

  return (
    <div className="attach-bar">
      {items.length > 0 && (
        <div className="attach-chips">
          {items.map((a, i) => (
            <span key={i} className="attach-chip">
              <Paperclip className="w-3 h-3" />
              <span className="attach-chip__name">{a.name}</span>
              <span className="attach-chip__meta">· {a.chars}字{a.truncated ? "(截断)" : ""}</span>
              <button type="button" aria-label="remove-attachment"
                      onClick={() => commit(items.filter((_, idx) => idx !== i))}>
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="attach-controls">
        <label className="attach-file" title="附加文件">
          <Paperclip className="w-4 h-4" />
          <input type="file" accept=".pdf,.docx,.txt,.md" style={{ display: "none" }}
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) addFile(f); e.target.value = ""; }} />
        </label>
        <input className="attach-url" placeholder="网址 (https://…)" value={url}
               onChange={(e) => setUrl(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addUrl(); } }} />
        <button type="button" className="attach-read" disabled={busy} onClick={addUrl}>读取</button>
      </div>
      {error && <div className="attach-error" role="alert">{error}</div>}
    </div>
  );
}
