import { useRef, useState } from "react";
import { FileText, Plus, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, type BrainLeaf } from "../../api/client";
import { useBrainTree } from "../../hooks/useBrainTree";
import { feedFile, feedTextOrUrl } from "../../lib/feed";
import BrainEntryDetail from "../brain/BrainEntryDetail";
import NoteEditor from "../brain/NoteEditor";
import { buttonClass, inputClass, primaryClass } from "./CompanionDialog";

export default function Materials() {
  const { t } = useTranslation();
  const { branches, loading, error, refresh } = useBrainTree();
  const [picked, setPicked] = useState<BrainLeaf | null>(null);
  const [query, setQuery] = useState("");
  const [text, setText] = useState("");
  const [noteTitle, setNoteTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const leaves = branches.flatMap(branch => branch.children).filter(leaf => leaf.kind === "material" || leaf.kind === "note");
  async function act(operation: () => Promise<void>) {
    setBusy(true); setFailure(null);
    try { await operation(); await refresh(); }
    catch (cause) { setFailure(cause instanceof Error ? cause.message : t("companion.failure")); }
    finally { setBusy(false); }
  }
  const pickNote = (id: number, title: string) => setPicked({ kind: "note", ref: `note:${id}`, label: title,
    provenance: null, confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 });
  return <section className="relative h-full overflow-hidden" aria-label={t("companion.materials")}>
    <div className="h-full overflow-y-auto px-5 py-6 sm:px-8"><div className="mx-auto max-w-5xl space-y-5">
      <h1 className="text-xl font-semibold">{t("companion.materials")}</h1>
      <div className="grid gap-4 lg:grid-cols-2">
        <form className="space-y-2 rounded-xl border border-border p-4" onSubmit={event => { event.preventDefault(); void act(async () => { await feedTextOrUrl(text, t); setText(""); }); }}>
          <textarea className={inputClass} rows={3} value={text} aria-label={t("brain.feed_ph")} placeholder={t("brain.feed_ph")} onChange={event => setText(event.target.value)} />
          <div className="flex flex-wrap gap-2"><button className={primaryClass} disabled={busy || !text.trim()}><Plus size={14} />{t("brain.feed_btn")}</button>
            <button type="button" className={buttonClass} disabled={busy} onClick={() => fileInput.current?.click()}><Upload size={14} />{t("brain.upload_title")}</button></div>
          <input ref={fileInput} type="file" multiple className="hidden" onChange={event => {
            const files = Array.from(event.target.files ?? []); event.target.value = "";
            void act(async () => { for (const file of files) await feedFile(file, t); });
          }} />
        </form>
        <form className="space-y-2 rounded-xl border border-border p-4" onSubmit={event => { event.preventDefault(); void act(async () => {
          const note = await api.createNote({ title: noteTitle.trim() }); setNoteTitle(""); pickNote(note.id, note.title);
        }); }}><input className={inputClass} value={noteTitle} maxLength={200} aria-label={t("brain.new_note_ph")} placeholder={t("brain.new_note_ph")}
          onChange={event => setNoteTitle(event.target.value)} /><button className={buttonClass} disabled={busy || !noteTitle.trim()}><Plus size={14} />{t("brain.kind_note")}</button></form>
      </div>
      {(failure || error) && <p role="alert" className="text-sm text-destructive">{failure || t("brain.read_failed")}</p>}
      <input type="search" className={inputClass} value={query} aria-label={t("brain.search_ph")} placeholder={t("brain.search_ph")} onChange={event => setQuery(event.target.value)} />
      {loading && <p role="status">{t("companion.loading")}</p>}
      {!loading && !leaves.length && <p className="p-8 text-center text-sm text-muted-foreground">{t("brain.graph_empty_body")}</p>}
      <ul className="space-y-2">{leaves.filter(leaf => leaf.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).map(leaf => <li key={leaf.ref}>
        <button className="flex w-full items-center gap-3 rounded-xl border border-border p-4 text-left hover:bg-foreground/5" onClick={() => setPicked(leaf)}>
          <FileText size={18} className="shrink-0 text-primary" /><span className="min-w-0 flex-1 break-words text-sm">{leaf.label}</span><span className="text-xs text-muted-foreground">{t(`brain.kind_${leaf.kind}`)}</span></button>
      </li>)}</ul>
    </div></div>
    {picked?.kind === "note" ? <NoteEditor noteId={Number(picked.ref.split(":")[1])} onClose={() => setPicked(null)} onChanged={() => void refresh()} allLabels={leaves.map(leaf => leaf.label)} onOpenNote={pickNote} />
      : picked ? <BrainEntryDetail leaf={picked} onClose={() => setPicked(null)} onChanged={() => void refresh()} /> : null}
  </section>;
}
