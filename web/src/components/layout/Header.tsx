import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import LanguageSwitcher from "./LanguageSwitcher";
import ThemeToggle from "./ThemeToggle";

export default function Header() {
  const { t } = useTranslation();
  return (
    <header className="flex items-center gap-3 border-b border-white/10 px-6 py-4">
      <Link to="/" className="flex items-center gap-2 text-lg font-semibold text-white">
        <span aria-hidden>🐆</span>
        <span>{t("app.name")}</span>
      </Link>
      <div className="ml-auto flex items-center gap-2">
        <Link to="/spawns" className="rounded-lg px-3 py-2 text-sm hover:bg-white/10">
          {t("nav.spawns")}
        </Link>
        <Link to="/settings" className="rounded-lg px-3 py-2 text-sm hover:bg-white/10">
          {t("nav.settings")}
        </Link>
        <LanguageSwitcher />
        <ThemeToggle />
      </div>
    </header>
  );
}
