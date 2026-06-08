import { useTranslation } from "react-i18next";

export default function NotFound() {
  const { t } = useTranslation();
  return (
    <div className="p-10 text-center text-white/70">
      <p className="text-lg font-medium">{t("errors.page_not_found")}</p>
    </div>
  );
}
