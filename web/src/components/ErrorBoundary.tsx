/**
 * ErrorBoundary — a top-level render guard. Without it, any exception thrown
 * during render white-screens the entire app (a blank <div id="root"> with the
 * error only in the console). This catches the error and shows a friendly,
 * on-theme "Something went wrong" panel with a Reload button, so an OSS user is
 * never stranded on a blank page.
 *
 * Class component (the only way to implement componentDidCatch /
 * getDerivedStateFromError). The fallback itself is a function component so it
 * can use i18n via useTranslation.
 */

import React from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, RotateCcw } from "lucide-react";

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/** Presentational fallback — token-only styling, respects reduced motion. */
function ErrorFallback({ error }: { error: Error | null }) {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      className="min-h-screen w-screen flex items-center justify-center bg-background text-foreground p-6 select-none font-sans antialiased"
    >
      <div className="w-full max-w-md bg-surface border border-border rounded-2xl p-8 space-y-5 text-center shadow-2xl shadow-primary/5">
        <div className="mx-auto w-12 h-12 rounded-full bg-danger/10 border border-danger/30 flex items-center justify-center">
          <AlertTriangle className="w-6 h-6 text-danger" />
        </div>

        <div className="space-y-2">
          <h1 className="text-lg font-bold text-foreground tracking-tight">
            {t("errorBoundary.title")}
          </h1>
          <p className="text-xs text-muted-foreground leading-relaxed">
            {t("errorBoundary.description")}
          </p>
        </div>

        {/* Dev-only technical detail — hidden in production builds. */}
        {import.meta.env.DEV && error && (
          <pre className="text-left text-[10px] font-mono text-danger/80 bg-background border border-border/60 rounded-lg p-3 max-h-40 overflow-auto whitespace-pre-wrap break-words">
            {error.message}
            {error.stack ? `\n\n${error.stack}` : ""}
          </pre>
        )}

        <button
          type="button"
          onClick={() => window.location.reload()}
          className="inline-flex items-center gap-2 px-4 py-2.5 bg-primary hover:bg-primary-hover text-primary-foreground text-xs font-bold uppercase tracking-wider rounded-lg transition-colors shadow-lg shadow-primary/10 motion-safe:transition-transform motion-safe:hover:scale-[1.02]"
        >
          <RotateCcw className="w-4 h-4" />
          {t("errorBoundary.reload")}
        </button>
      </div>
    </div>
  );
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Surface the crash for diagnostics rather than swallowing it silently.
    console.error("[ErrorBoundary] caught render error", error, info);
  }

  render(): React.ReactNode {
    if (this.state.error) {
      return <ErrorFallback error={this.state.error} />;
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
