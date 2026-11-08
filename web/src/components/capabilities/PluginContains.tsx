import { useTranslation } from "react-i18next";
import type { CapabilityCard, PluginConnection } from "../../api/client.types";
import { Escaped, isolate } from "../../lib/outsideText";

const host = (url: string | null) => {
  try { return url ? new URL(url).host : ""; } catch { return url ?? ""; }
};

function Tag({ children }: { children: React.ReactNode }) {
  return <span className="rounded-md bg-fill px-1.5 py-px text-[11px] text-muted-foreground">{children}</span>;
}

/** A connection's settings, as the server sends them (a fixed credential already masked): one line each. */
function Started({ c }: { c: PluginConnection }) {
  const { t } = useTranslation();
  const pairs = (map: Record<string, string>, join: string) => Object.entries(map).map(([k, v]) => `${k}${join}${v}`).join(", ");
  const lines = [
    c.arguments.length > 0 && ["card_partArguments", c.arguments.join(" ")],
    Object.keys(c.env).length > 0 && ["card_partEnv", pairs(c.env, "=")],
    Object.keys(c.headers).length > 0 && ["card_partHeaders", pairs(c.headers, ": ")],
    c.keys.length > 0 && ["card_partKeys", c.keys.join(", ")],
  ].filter(Boolean) as [string, string][];
  return <>{lines.map(([key, value]) => <span key={key} className="text-[12px] text-muted-foreground">
    {t(`discover.${key}`)} <span className="font-mono text-[11.5px] text-foreground"><Escaped text={value} /></span></span>)}</>;
}

/**
 * CAP7b's "Contains" row (board Main): each skill, with what it has, and each connection, with how it runs and what it
 * is started with. The parts go in, switch and go as one group, so nothing here is a choice.
 */
export function PluginContains({ card }: { card: CapabilityCard }) {
  const { t } = useTranslation();
  return <span className="flex flex-col gap-2.5">
    {(card.skills ?? []).map(s => <span key={s.key} className="flex flex-col gap-px" data-testid="plugin-part" data-kind="skill">
      <span><Tag>{t("discover.card_partSkill")}</Tag> <Escaped text={s.name} /></span>
      <span className="text-[12px] text-muted-foreground">
        {s.scripts.length ? t("discover.card_partSkillScripts", { count: s.scripts.length }) : t("discover.card_partSkillText")}</span>
      {(s.hidden?.count ?? 0) > 0 && <span className="text-[12px] text-ask">
        {t("discover.card_hiddenText", { count: s.hidden!.count, runs: s.hidden!.runs.join(", ") })}</span>}
    </span>)}
    {(card.connections ?? []).map(c => <span key={c.name} className="flex flex-col gap-px" data-testid="plugin-part" data-kind="connection">
      <span><Tag>{t("discover.card_partConnection")}</Tag> <Escaped text={c.name} /></span>
      <span className="text-[12px] text-muted-foreground">
        {c.runtime === "remote" ? t("discover.card_runRemote", { host: host(c.remote_host) })
          : t(c.network ? "discover.card_partPackageNet" : "discover.card_partPackage", {
            registry: c.runtime === "uv" ? "PyPI" : "npm",
            package: isolate(`${c.package?.identifier ?? c.name} ${c.package?.version ?? ""}`.trim()) })}</span>
      <Started c={c} />
    </span>)}
  </span>;
}
