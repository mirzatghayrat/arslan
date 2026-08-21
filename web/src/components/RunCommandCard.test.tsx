import { render, screen, fireEvent } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";
import RunCommandCard from "./RunCommandCard";
import "../i18n";

describe("RunCommandCard", () => {
  test("shows the full command and fires confirm with remember flag", () => {
    const onConfirm = vi.fn();
    render(
      <RunCommandCard
        callId="c1"
        pretty="git status"
        reason="check repo"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText("git status")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("runcmd-remember"));
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(onConfirm).toHaveBeenCalledWith("c1", true);
  });

  test("cancel fires onCancel", () => {
    const onCancel = vi.fn();
    render(
      <RunCommandCard
        callId="c1"
        pretty="git status"
        reason=""
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByTestId("runcmd-cancel"));
    expect(onCancel).toHaveBeenCalledWith("c1");
  });

  test("a remote command names the machine and shows its fingerprint", () => {
    render(
      <RunCommandCard
        callId="c9"
        pretty="git status"
        reason="risk: HIGH"
        remoteHost="me@192.168.1.8"
        fingerprints={["256 SHA256:abc123 (ED25519)"]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByTestId("runcmd-remote-note")).toBeInTheDocument();
    expect(screen.getByText(/192\.168\.1\.8/)).toBeInTheDocument();
    expect(screen.getByText("256 SHA256:abc123 (ED25519)")).toBeInTheDocument();
  });

  test("a remote command offers no remember checkbox", () => {
    // Not cosmetic: the backend refuses to honour "remember" for a remote
    // command, so showing the box would be a promise broken in a safety dialog.
    const onConfirm = vi.fn();
    render(
      <RunCommandCard
        callId="c9"
        pretty="git status"
        reason="risk: HIGH"
        remoteHost="me@192.168.1.8"
        fingerprints={["fp"]}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("runcmd-remember")).toBeNull();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(onConfirm).toHaveBeenCalledWith("c9", false);
  });

  test("a local command is not dressed up as a remote one", () => {
    render(
      <RunCommandCard
        callId="c1"
        pretty="git status"
        reason=""
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("runcmd-remote-note")).toBeNull();
    expect(screen.queryByTestId("runcmd-fingerprints")).toBeNull();
    expect(screen.getByTestId("runcmd-remember")).toBeInTheDocument();
  });
});
