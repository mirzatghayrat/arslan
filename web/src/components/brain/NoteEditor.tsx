import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { ApiError, api } from "../../api/client";
import type { NoteDto, NoteSuggestDto } from "../../api/client.types";
import { activeWikilink, insertWikilink, type WikilinkToken } from "../../lib/wikilinks";

interface Props {
  noteId: number;
  onClose: () => void;
  onChanged: () => void;
  allLabels: string[];
  /** open another note (a backlink click). Routed through BrainSection so the graph and
   * the activity strip re-light with it, instead of swapping ids behind their backs. */
  onOpenNote?: (id: number, title: string) => void;
  onHover?: (id: string | null) => void;
}

/** Hand-written markdown note editor — title + content + tags, [[wikilink]]
 * autocomplete fed by `allLabels` (note titles + every other Second-Brain leaf
 * label), AI 建议关联 (suggest links from the LLM) + backlinks. Mirrors the
 * dark-orange BrainEntryDetail chrome but is fully editable. */
export default function NoteEditor({ noteId, onClose, onChanged, allLabels, onOpenNote, onHover }: Props) {
  const [note, setNote] = useState<NoteDto | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [token, setToken] = useState<WikilinkToken | null>(null);
  const [suggest, setSuggest] = useState<NoteSuggestDto | null>(null);
  const [suggestBusy, setSuggestBusy] = useState(false);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  /** unsaved-edit detector for the backlink guard above. Compared against the LOADED
   * note rather than a boolean flag, so saving (which updates `note`) clears it without
   * anyone having to remember to reset a flag. */
  const dirty =
    note != null &&
    (title !== note.title ||
      content !== note.content ||
      JSON.stringify(tags) !== JSON.stringify(note.tags ?? []));

  useEffect(() => {
    let ok = true;
    setNote(null);
    setSuggest(null);
    setLoadErr(null);
    api.getNote(noteId).then((n) => {
      if (!ok) return;
      setNote(n);
      setTitle(n.title);
      setContent(n.content);
      setTags(n.tags ?? []);
    }).catch((e) => {
      if (!ok) return;
      setNote(null);
      // same reason as BrainEntryDetail: a strip row can outlive its note, and
      // "loading…" forever is a worse answer than saying it is gone.
      setLoadErr(e instanceof ApiError && e.status === 404
        ? "这条笔记已经不存在了(可能已被删除)。" : "读取失败。");
    });
    return () => { ok = false; };
  }, [noteId]);

  const syncWikilink = () => {
    const el = textareaRef.current;
    if (!el) return;
    const tok = activeWikilink(el.value, el.selectionStart ?? el.value.length);
    setToken(tok);
  };

  const onContentChange = (value: string) => {
    setContent(value);
    // caret position is read on the next tick's selectionStart via syncWikilink,
    // but we already have the DOM value here — reuse the textarea's own caret.
    const el = textareaRef.current;
    const caret = el?.selectionStart ?? value.length;
    setToken(activeWikilink(value, caret));
  };

  const pickWikilink = (name: string) => {
    const el = textareaRef.current;
    if (!el || !token) return;
    const caret = el.selectionStart ?? content.length;
    const out = insertWikilink(content, token, caret, name);
    setContent(out.value);
    setToken(null);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(out.caret, out.caret);
    });
  };

  const addTag = () => {
    const t = tagInput.trim();
    if (!t || tags.includes(t)) { setTagInput(""); return; }
    setTags((prev) => [...prev, t]);
    setTagInput("");
  };

  const removeTag = (t: string) => setTags((prev) => prev.filter((x) => x !== t));

  const save = async () => {
    setSaving(true);
    try {
      await api.updateNote(noteId, { title, content, tags });
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    await api.deleteNote(noteId);
    onChanged();
    onClose();
  };

  const runSuggest = async () => {
    setSuggestBusy(true);
    try {
      const out = await api.suggestNoteLinks(noteId);
      setSuggest(out);
    } finally {
      setSuggestBusy(false);
    }
  };

  const insertSuggestedLink = (target: string) => {
    setContent((prev) => `${prev}${prev.endsWith("\n") || !prev ? "" : "\n"}[[${target}]]`);
  };

  const addSuggestedTag = (t: string) => {
    setTags((prev) => (prev.includes(t) ? prev : [...prev, t]));
  };

  const dropdownItems = token
    ? allLabels.filter((l) => l.toLowerCase().includes(token.query.toLowerCase())).slice(0, 8)
    : [];

  return (
    <div className="note-editor absolute top-0 right-0 h-full w-[420px] bg-surface-raised border-l border-border p-4 overflow-auto z-20">
      <div className="note-editor__head">
        <input
          className="note-editor__title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="笔记标题"
        />
        <button onClick={onClose} aria-label="关闭笔记" className="note-editor__close">
          <X className="w-4 h-4" />
        </button>
      </div>

      {loadErr ? (
        <div className="text-[11px] text-warning" role="alert" data-testid="note-load-error">{loadErr}</div>
      ) : note == null ? (
        <div className="text-[11px] text-subtle-foreground">loading…</div>
      ) : (
        <>
          <div className="note-editor__textarea-wrap">
            <textarea
              ref={textareaRef}
              className="note-editor__textarea"
              value={content}
              onChange={(e) => onContentChange(e.target.value)}
              onSelect={syncWikilink}
              onKeyUp={syncWikilink}
              onClick={syncWikilink}
              placeholder="正文(markdown,用 [[笔记名]] 链接)"
              rows={12}
            />
            {token && dropdownItems.length > 0 && (
              <div className="note-editor__wikilink-dropdown">
                {dropdownItems.map((l) => (
                  <button key={l} type="button" className="note-editor__wikilink-item" onClick={() => pickWikilink(l)}>
                    {l}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="note-editor__tags">
            {tags.map((t) => (
              <span key={t} className="note-editor__tag">
                {t}
                <button type="button" aria-label={`移除标签 ${t}`} onClick={() => removeTag(t)}>×</button>
              </span>
            ))}
            <input
              className="note-editor__tag-input"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
              placeholder="＋ 标签"
            />
          </div>

          <div className="note-editor__actions">
            <button className="note-editor__save" disabled={saving} onClick={() => void save()}>
              {saving ? "保存中…" : "保存"}
            </button>
            <button className="note-editor__delete" onClick={() => void remove()}>删除</button>
            <button className="note-editor__ai" disabled={suggestBusy} onClick={() => void runSuggest()}>
              {suggestBusy ? "分析中…" : "AI 建议关联"}
            </button>
          </div>

          {suggest && (
            <div className="note-editor__suggestions">
              {suggest.suggestions.length === 0 && suggest.tags.length === 0 ? (
                <div className="note-editor__empty">没有建议</div>
              ) : (
                <>
                  {suggest.suggestions.map((s, i) => (
                    <div key={`${s.target}-${i}`} className="note-editor__sugg">
                      <div className="note-editor__sugg-head">
                        <span className="note-editor__sugg-target">{s.target}</span>
                        <span className="note-editor__sugg-kind">{s.kind}</span>
                      </div>
                      <div className="note-editor__sugg-reason">{s.reason}</div>
                      <button type="button" className="note-editor__sugg-insert" onClick={() => insertSuggestedLink(s.target)}>
                        插入 [[链接]]
                      </button>
                    </div>
                  ))}
                  {suggest.tags.map((t) => (
                    <button key={t} type="button" className="note-editor__sugg-tag" onClick={() => addSuggestedTag(t)}>
                      加标签 {t}
                    </button>
                  ))}
                </>
              )}
            </div>
          )}

          <div className="note-editor__backlinks">
            <div className="note-editor__backlinks-label">被链接</div>
            {(note.backlinks ?? []).length === 0 ? (
              <div className="note-editor__empty">暂无</div>
            ) : (
              (note.backlinks ?? []).map((b) => (
                <button key={b.id} type="button" className="note-editor__backlink"
                  data-testid="backlink"
                  onMouseEnter={() => onHover?.(`note:${b.id}`)}
                  onMouseLeave={() => onHover?.(null)}
                  onClick={() => {
                    // 🔴 Navigating away would DISCARD unsaved edits with no prompt —
                    // silent data loss, and the edits are the user's own typing. Ask.
                    if (dirty && !window.confirm("这条笔记有未保存的修改,离开会丢失。仍要打开被链接的笔记吗?")) return;
                    onOpenNote?.(b.id, b.title);
                  }}>
                  {b.title}
                </button>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
