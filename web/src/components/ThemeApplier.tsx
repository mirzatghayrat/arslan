import { useEffect } from "react";
import { useThemeStore } from "../stores/themeStore";

export function ThemeApplier() {
  const apply = useThemeStore((s) => s.apply);
  const palette = useThemeStore((s) => s.palette);
  const mode = useThemeStore((s) => s.mode);
  useEffect(() => { apply(); }, [apply, palette, mode]);
  return null;
}
