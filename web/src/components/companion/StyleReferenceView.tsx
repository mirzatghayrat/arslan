import { useTranslation } from "react-i18next";
import type { StyleReference } from "../../api/companion";

export default function StyleReferenceView({ reference }: { reference?: StyleReference | null }) {
  const { t } = useTranslation();
  if (!reference) return null;
  return <div className="my-3 space-y-2 rounded-lg border border-border p-3 text-sm" data-testid="style-reference">
    <h3 className="font-medium">{t("design.reference")}</h3>
    <p>{t(reference.polarity === "positive" ? "design.positive" : "design.negative")} · {t(reference.interpretation === "confirmed" ? "design.confirmed" : "design.tentative")}</p>
    <p className="break-all text-muted-foreground">{reference.source_ref}</p>
    <p className="whitespace-pre-wrap break-words">{reference.rationale}</p>
    <p className="text-xs text-muted-foreground">{t("design.referenceHint")}</p>
  </div>;
}
