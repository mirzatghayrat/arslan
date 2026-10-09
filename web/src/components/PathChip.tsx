import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { filesApi, type PathStat } from "../api/files";
import { useWorkbench } from "../stores/workbenchStore";

/** A local path as a reply writes it: ~/… or /… (not a //host URL), one line, not too long. */
const LOCAL_PATH = /^(~\/|\/(?!\/))[^\n\0]{1,400}$/;
export const isLocalPath = (text: string) => LOCAL_PATH.test(text.trim()) && !/\s{2,}|^\/\s/.test(text.trim());

/** Paths stat in batches: one request per message (they render together), cached per window. */
const cache = new Map<string, Promise<PathStat | null>>();
let queue: { path: string; resolve: (s: PathStat | null) => void }[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
function flush() {
  const batch = queue.splice(0, 50);
  timer = queue.length ? setTimeout(flush, 0) : null;
  filesApi.stat(batch.map((b) => b.path))
    .then((r) => batch.forEach((b, i) => b.resolve(r.items[i] ?? null)))
    .catch(() => batch.forEach((b) => b.resolve(null)));
}
export function statPath(path: string): Promise<PathStat | null> {
  let p = cache.get(path);
  if (!p) {
    p = new Promise((resolve) => { queue.push({ path, resolve }); if (!timer) timer = setTimeout(flush, 30); });
    cache.set(path, p);
  }
  return p;
}
export function _resetPathCache() { cache.clear(); queue = []; if (timer) clearTimeout(timer); timer = null; }

/**
 * A path in a reply (0.1.58 §2): inside the folders Arslan may read it opens in the reader (a
 * folder opens in 文件); elsewhere it shows in Finder — Arslan does not read it; a path that does
 * not exist stays plain text.
 */
export default function PathChip({ path, children, fallback }: { path: string; children?: ReactNode; fallback?: ReactNode }) {
  const { t } = useTranslation();
  const [stat, setStat] = useState<PathStat | null>(null);
  const openReader = useWorkbench((s) => s.openReader);
  const browse = useWorkbench((s) => s.browse);
  useEffect(() => {
    let alive = true;
    void statPath(path.trim()).then((s) => { if (alive) setStat(s); });
    return () => { alive = false; };
  }, [path]);
  const label = children ?? path;
  if (!stat?.exists) return <>{fallback ?? <code data-testid="path-plain">{label}</code>}</>;
  const open = () => {
    if (!stat.readable) void filesApi.reveal(path.trim());
    else if (stat.is_dir) browse(path.trim());
    else openReader({ kind: "path", path: path.trim() });
  };
  return (
    <button type="button" onClick={open} data-testid="path-chip" data-readable={stat.readable || undefined}
      title={stat.readable ? t("workbench.read") : t("workbench.reveal")}
      className="inline rounded border border-info/30 bg-info/10 px-1 font-mono text-[0.84em] text-info hover:bg-info/15">
      {label}
    </button>
  );
}
