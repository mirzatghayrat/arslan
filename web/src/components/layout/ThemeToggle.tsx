import { useThemeStore } from "../../stores/themeStore";

export default function ThemeToggle() {
  const { theme, toggle } = useThemeStore();
  return (
    <button
      onClick={toggle}
      aria-label="Toggle theme"
      className="rounded-lg px-3 py-2 text-sm hover:bg-white/10"
    >
      {theme === "dark" ? "☀️" : "🌙"}
    </button>
  );
}
