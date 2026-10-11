import { useState } from "react";
import FirstRunWizard from "../../components/FirstRunWizard";
import BrandMark from "../../components/BrandMark";

/**
 * Dev-only preview of the first-run film (0.1.60) over a plain stand-in for the empty conversation,
 * so the head's hand-off has its real target: `npm run dev`, then /#first-run (add `&dark` for the
 * dark stage). Without a backend the model and Hands calls fail quietly (no Hands shot; "Later" moves
 * on). Not reachable in a production build (main.tsx gates it on import.meta.env.DEV).
 */
export default function FirstRunPreview() {
  const [open, setOpen] = useState(true);
  return (
    <div className="h-screen w-screen bg-background text-foreground flex flex-col items-center justify-center gap-4">
      <div className="flex items-center gap-3">
        <BrandMark alt="Arslan" className="w-11 h-11 object-contain" data-brand-anchor="" />
        <h1 className="text-3xl font-medium tracking-tight">Good evening</h1>
      </div>
      <div className="w-full max-w-xl h-28 rounded-2xl border border-border bg-surface" />
      {!open && (
        <button type="button" className="text-xs text-muted-foreground underline" onClick={() => setOpen(true)}>
          Play again
        </button>
      )}
      {open && (
        <FirstRunWizard
          llmProviders={[{ key: "deepseek", label: "DeepSeek", base_url: "", default_model: "deepseek-chat", native: false, models: [] }]}
          onAdded={() => {}}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}
