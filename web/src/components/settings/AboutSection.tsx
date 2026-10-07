import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { request } from "../../api/client";
import Markdown from "../Markdown";
import AppIdentityCard from "./AppIdentityCard";
import { Button } from "../kit";
import { SettingsGroup } from "./SettingsGroup";

interface About { version: string; releases: { version: string; notes: string }[] }

/** 0.1.55 §11 About: the version, what changed in it (the notes shipped with the app — D2),
 *  and where to look when something is wrong. */
export default function AboutSection({ onOpenActivity }: { onOpenActivity?: () => void }) {
  const { t } = useTranslation();
  const [about, setAbout] = useState<About | null>(null);
  useEffect(() => {
    let alive = true;
    request<About>("/about").then((a) => { if (alive) setAbout(a); }).catch(() => { /* the version card still shows */ });
    return () => { alive = false; };
  }, []);
  const newest = about?.releases?.[0];
  return (
    <div className="flex flex-col gap-6" data-testid="settings-about">
      <SettingsGroup title={t("settings.grpVersion")}><AppIdentityCard /></SettingsGroup>
      <SettingsGroup title={t("settings.grpWhatsNew")} testId="settings-whats-new">
        {newest ? <div className="text-[13px]"><Markdown>{newest.notes}</Markdown></div>
          : <p className="text-[13px] text-muted-foreground">{t("settings.whatsNewEmpty")}</p>}
      </SettingsGroup>
      {onOpenActivity && <SettingsGroup>
        <div className="flex items-center justify-between gap-4">
          <span className="text-[13px] text-muted-foreground">{t("settings.openActivity")}</span>
          <Button size="sm" onClick={onOpenActivity}>{t("settings.openActivityBtn")}</Button>
        </div>
      </SettingsGroup>}
    </div>
  );
}
