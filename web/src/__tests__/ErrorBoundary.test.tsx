import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import ErrorBoundary from "../components/layout/ErrorBoundary";

function Boom(): JSX.Element {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // silence the expected React error log for the thrown child
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders an inline fallback (and not the full-page UI) when given one", () => {
    render(
      <ErrorBoundary fallback={<span>inline-oops</span>}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("inline-oops")).toBeInTheDocument();
    expect(screen.queryByText(/Something went wrong/i)).toBeNull();
  });

  it("falls back to the full-page UI when no fallback is provided (app-level use)", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument();
  });

  it("renders children normally when nothing throws", () => {
    render(
      <ErrorBoundary fallback={<span>inline-oops</span>}>
        <span>healthy</span>
      </ErrorBoundary>,
    );
    expect(screen.getByText("healthy")).toBeInTheDocument();
    expect(screen.queryByText("inline-oops")).toBeNull();
  });
});
