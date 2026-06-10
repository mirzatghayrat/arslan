import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** When provided, a caught error renders this inline fallback instead of the
   *  full-page "Something went wrong" UI — so a single bad subtree (e.g. one
   *  conversation turn) degrades locally without white-screening the whole app. */
  fallback?: ReactNode;
}
interface State {
  hasError: boolean;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Uncaught UI error:", error, info);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback !== undefined) return this.props.fallback;
      return (
        <div className="p-10 text-center text-white/70">
          <p className="text-lg font-medium">Something went wrong.</p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 rounded-lg bg-amber px-4 py-2 font-medium text-black"
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
