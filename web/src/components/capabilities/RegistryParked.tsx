import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/client";
import { capabilitiesApi, type CapabilitySource, type RegistryNames } from "../../api/capabilities";
import { Escaped } from "../../lib/outsideText";
import { Button, Notice } from "../kit";

const REGISTRY = { pypi: "PyPI", npm: "npm", oci: "OCI", nuget: "NuGet" } as Record<string, string>;

/** What was installed, or what the entry names now: a package with its version and registry, or a remote's URL. */
function names(value: RegistryNames | null) {
  if (!value) return "";
  if (value.url) return value.url;
  const where = value.registry_type ? REGISTRY[value.registry_type] ?? value.registry_type : "";
  return [value.identifier, value.version].filter(Boolean).join(" ") + (where ? ` (${where})` : "");
}

/**
 * CAP4a-3d's web half (the board the user OK'd, 2026-11-02): a connection its Registry entry stopped, withdrawn or
 * naming something else, and the button that keeps it. The row reads the server's `registry_parked`, so it needs no
 * rule of its own; the keep posts the `seen` it showed, and a newer answer (409) is shown again, never kept blindly.
 * Nothing shows when nothing is parked.
 */
export function RegistryParked({ sourceId, onChanged }: { sourceId: string; onChanged: () => void }) {
  const { t } = useTranslation();
  const [source, setSource] = useState<CapabilitySource | null>(null);
  const [kept, setKept] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    capabilitiesApi.source(sourceId).then(s => { if (live) setSource(s); }).catch(() => undefined);
    return () => { live = false; };
  }, [sourceId]);

  if (kept) return <Notice tone="info" testId="registry-kept">{t("capabilityList.parked_kept")}</Notice>;
  const parked = source?.registry_parked;
  if (!parked) return null;
  const when = parked.checked_at && new Date(parked.checked_at).toDateString() === new Date().toDateString()
    ? t("capabilityList.parked_today")
    : parked.checked_at ? new Date(parked.checked_at).toLocaleDateString() : "—";

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
        <span data-testid="registry-parked-installed" className="font-mono break-all"><Escaped text={names(parked.installed)} /></span>
        <span className="text-muted-foreground">{t("capabilityList.parked_now")}</span>
        <span data-testid="registry-parked-now" className={parked.why === "withdrawn" ? "" : "font-mono break-all"}>
          {parked.why === "withdrawn" ? t("capabilityList.parked_nowWithdrawn") : <Escaped text={names(parked.now)} />}</span>
      </div>
      {parked.looks_same && <p data-testid="registry-parked-looks-same" className="text-[12px] text-warning">
        {t("capabilityList.parked_looksSame")}</p>}
      {parked.hidden.now > 0 && <p data-testid="registry-parked-hidden" className="text-[12px] text-warning">
        {t("capabilityList.parked_hidden", { count: parked.hidden.now })}</p>}
      {parked.why === "changed" && <p className="text-[12px] text-muted-foreground">{t("capabilityList.parked_keepRuns")}</p>}
      {error && <Notice tone="error" role="alert" testId="registry-parked-error">{error}</Notice>}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" tone="primary" disabled={busy} data-testid="registry-keep" onClick={() => void keep()}>
          {t("capabilityList.parked_keep")}</Button>
      </div>
      <p className="text-[11px] text-subtle-foreground">{t("capabilityList.parked_note")}</p>
    </div>
  );
}
