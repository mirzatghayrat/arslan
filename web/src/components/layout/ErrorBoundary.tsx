import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
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
