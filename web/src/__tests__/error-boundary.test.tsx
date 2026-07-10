/**
 * ErrorBoundary — a child that throws must render the fallback panel, NOT a
 * blank screen, and must not crash the test runner.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

import { ErrorBoundary } from "../components/ErrorBoundary";

function Boom(): React.ReactElement {
  throw new Error("kaboom");
}

describe("ErrorBoundary", () => {
  // React logs the caught error to console.error; silence it for clean output.
  let errSpy: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    errSpy.mockRestore();
  });

  it("renders children when there is no error", () => {
    render(
      <ErrorBoundary>
        <div>hello child</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText("hello child")).toBeInTheDocument();
  });

  it("renders the fallback (not a blank screen) when a child throws", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );

    // The fallback panel is present…
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("errorBoundary.title")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /errorBoundary\.reload/i }),
    ).toBeInTheDocument();
    // …and the throwing child's own output is NOT on screen.
    expect(screen.queryByText("hello child")).toBeNull();
  });

  it("shows the error message in dev builds", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    // import.meta.env.DEV is true under vitest → the dev-only detail is shown.
    expect(screen.getByText(/kaboom/)).toBeInTheDocument();
  });
});
