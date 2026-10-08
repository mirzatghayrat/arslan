import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonTone = "primary" | "secondary" | "destructive" | "plain";

const TONE: Record<ButtonTone, string> = {
  // The label colour, not the palette's orange: --primary stays a brand accent.
  primary: "bg-foreground text-background hover:opacity-90",
  secondary: "bg-fill text-foreground hover:bg-fill-strong",
  destructive: "bg-danger-soft text-danger-strong hover:bg-danger-soft/80",
  plain: "bg-transparent text-muted-foreground hover:text-foreground",
};

/** A keyboard hint inside a button: ⌘⏎, esc. */
export function Kbd({ children, onPrimary = false }: { children: ReactNode; onPrimary?: boolean }) {
  return (
    <span aria-hidden="true" className={`rounded-[5px] px-1.5 py-px font-mono text-[11px] font-medium ${
      onPrimary ? "bg-background/20 text-background/70" : "bg-fill text-subtle-foreground"}`}>
      {children}
    </span>
  );
}

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: ButtonTone;
  size?: "md" | "sm";
  kbd?: string;
  grow?: number;
};

/** The one button of the surface kit (0.1.55): sentence case, system font, no uppercase mono. */
export function Button({ tone = "secondary", size = "md", kbd, grow, className = "", children, style, ...rest }: Props) {
  const sizing = size === "sm" ? "h-[26px] px-2.5 text-[12px] rounded-lg" : "h-10 px-4 text-[14px] rounded-[10px]";
  return (
    <button type="button" {...rest}
      style={grow ? { flex: grow, ...style } : style}
      className={`inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap font-sans font-semibold transition-opacity disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-foreground/25 ${sizing} ${TONE[tone]} ${className}`}>
      {children}
      {kbd ? <Kbd onPrimary={tone === "primary"}>{kbd}</Kbd> : null}
    </button>
  );
}
