import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/client";
import { capabilitiesApi, type CapabilitySource, type RegistryNames } from "../../api/capabilities";
import { formatUiDate } from "../../lib/localeFormatting";
import { Button, Notice } from "../kit";

const REGISTRY = { pypi: "PyPI", npm: "npm", oci: "OCI", nuget: "NuGet" } as Record<string, string>;

/** What was installed, or what the entry names now: a package with its version and registry, or a remote's URL. */
function names(value: RegistryNames | null) {
  if (!value) return "";
  if (value.url) return value.url;
  const where = value.registry_type ? REGISTRY[value.registry_type] ?? value.registry_type : "";
  return [value.identifier, value.version].filter(Boolean).join(" ") + (where ? ` (${where})` : "");
}

/** Whitespace as the page draws it (any run, NBSP included, reads as one space). */
const drawn = (text: string) => text.replace(/\s+/g, " ").trim();
const label = (cp: number) => `U+${cp.toString(16).toUpperCase().padStart(4, "0")}`;
/** A value as it reads on the page, each non-ASCII character spelled as its chip: a value that writes another's chip
 *  in plain ASCII (a literal "U+00F6") then reads the same as it, and gets the note (#604 max review of d65f323a). */
const labeled = (text: string) =>
  [...text].map(ch => { const cp = ch.codePointAt(0) ?? 0; return cp >= 0x20 && cp <= 0x7e ? ch : label(cp); }).join("");

/** One value the Registry wrote or that was installed. Names, versions and addresses are ASCII by rule, so every
 *  other character is shown as its code point (U+00A0, U+043E…): a lookalike letter or an odd space cannot pass for
 *  the installed value (#604 max review). An empty value reads "—". Isolated (<bdi>) from the words around it. */
function Value({ text, testId }: { text: string; testId: string }) {
  const { t } = useTranslation();
  if (!drawn(labeled(text))) return <span data-testid={testId}>—</span>;       // an NBSP-only value shows its chip
  const parts: ReactNode[] = [];
  let plain = "";
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0;
    if (cp >= 0x20 && cp <= 0x7e) { plain += ch; continue; }
    if (plain) parts.push(plain);
    plain = "";
    parts.push(<span key={parts.length} data-testid="non-ascii" role="img"
      aria-label={t("capabilityList.parked_char", { code: label(cp) })}
      className="mx-px rounded bg-ask-soft px-1 font-mono text-[10px] text-ask">{label(cp)}</span>);
  }
  if (plain) parts.push(plain);
  return <span data-testid={testId} className="font-mono break-all"><bdi>{parts}</bdi></span>;
}

/**
 * CAP4a-3d's web half (the board the user OK'd, 2026-11-02): a connection its Registry entry stopped, withdrawn or
 * naming something else, and the button that keeps it. The row reads the server's `registry_parked`, so it needs no
 * rule of its own; the keep posts the `seen` it showed, and a newer answer (409) is shown again, never kept blindly.
 * Nothing shows when nothing is parked.
 */
export function RegistryParked({ sourceId, onChanged }: { sourceId: string; onChanged: () => void }) {
  const { t, i18n } = useTranslation();
  const [source, setSource] = useState<CapabilitySource | null>(null);
  const [failed, setFailed] = useState(false);
  const [kept, setKept] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    capabilitiesApi.source(sourceId).then(s => { if (live) setSource(s); })
      .catch(() => { if (live) setFailed(true); });                     // said, as the sheet does (#604 max review)
    return () => { live = false; };
  }, [sourceId]);

  if (kept) return <Notice tone="info" testId="registry-kept">{t("capabilityList.parked_kept")}</Notice>;
  if (failed) return <p role="alert" data-testid="registry-parked-load-failed" className="text-[12px] text-danger-strong">
    {t("capabilityList.loadFailed")}</p>;
  const parked = source?.registry_parked;
  if (!parked) return null;
  const when = parked.checked_at && new Date(parked.checked_at).toDateString() === new Date().toDateString()
    ? t("capabilityList.parked_today")
    : parked.checked_at ? formatUiDate(parked.checked_at, i18n?.language) : "—";
  const installedText = names(parked.installed), nowText = names(parked.now);
  // #604 max review: the note shows whenever the two rows read the same as drawn, whatever looks_same said.
  // Either way of reading counts: as drawn (an NBSP is a space) or with the chips spelled (a literal "U+00F6").
  const readsSame = parked.why === "changed" && (parked.looks_same || drawn(installedText) === drawn(nowText)
    || drawn(labeled(installedText)) === drawn(labeled(nowText)));

  async function keep() {
    if (!parked) return;
    setBusy(true); setError(null);
    try {
      await capabilitiesApi.acceptSource(sourceId, parked.seen);
      setKept(true);
      onChanged();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setError(t("capabilityList.parked_moved"));
        try { setSource(await capabilitiesApi.source(sourceId)); } catch { /* keep the row as it was shown */ }
      } else {
        setError(t("capabilityList.parked_failed"));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="registry-parked" className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4 text-[13px]">
      <div className="flex items-center gap-2">
        <span className="rounded-full border border-warning/40 bg-warning/10 px-2.5 py-0.5 text-[12px] text-warning">
          {t("capabilityList.parked_stopped")}</span>
      </div>
      <p data-testid="registry-parked-why" className="text-muted-foreground">
        {t(parked.why === "withdrawn" ? "capabilityList.parked_withdrawn" : "capabilityList.parked_changed", { when })}</p>
      <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[12px]">
        <span className="text-muted-foreground">{t("capabilityList.parked_installed")}</span>
        <Value text={installedText} testId="registry-parked-installed" />
        <span className="text-muted-foreground">{t("capabilityList.parked_now")}</span>
        {parked.why === "withdrawn" ? <span data-testid="registry-parked-now">{t("capabilityList.parked_nowWithdrawn")}</span>
          : <Value text={nowText} testId="registry-parked-now" />}
      </div>
      {readsSame && <p data-testid="registry-parked-looks-same" className="text-[12px] text-warning">
        {t("capabilityList.parked_looksSame")}</p>}
      {parked.hidden.now > 0 && <p data-testid="registry-parked-hidden" className="text-[12px] text-warning">
        {t("capabilityList.parked_hidden", { count: parked.hidden.now })}</p>}
      {parked.why === "changed" && <p className="text-[12px] text-muted-foreground" data-testid="registry-parked-keep-runs">
        {t(parked.installed?.url ? "capabilityList.parked_keepRunsRemote" : "capabilityList.parked_keepRuns")}</p>}
      {error && <Notice tone="error" role="alert" testId="registry-parked-error">{error}</Notice>}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" tone="primary" disabled={busy} data-testid="registry-keep" onClick={() => void keep()}>
          {t("capabilityList.parked_keep")}</Button>
      </div>
      <p className="text-[11px] text-subtle-foreground">{t("capabilityList.parked_note")}</p>
    </div>
  );
}
