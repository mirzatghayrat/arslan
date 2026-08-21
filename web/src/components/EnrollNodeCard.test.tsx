import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach } from "vitest";
import EnrollNodeCard from "./EnrollNodeCard";
import { api } from "../api/client";
import "../i18n";

vi.mock("../api/client", () => ({
  api: { enrollSshNode: vi.fn(async () => ({ id: 1 })) },
}));

const props = {
  callId: "c1",
  name: "studio",
  host: "192.168.1.8",
  user: "someone",
  fingerprints: ["256 SHA256:abc123 (ED25519)"],
};

describe("EnrollNodeCard", () => {
  beforeEach(() => vi.clearAllMocks());

  test("shows the fingerprint the user has to check", () => {
    render(<EnrollNodeCard {...props} onDone={vi.fn()} />);
    expect(screen.getByText("256 SHA256:abc123 (ED25519)")).toBeInTheDocument();
    // The address appears twice by design — in the title and in the user@host
    // line — so this pins that BOTH carry it rather than accidentally matching one.
    expect(screen.getAllByText(/192\.168\.1\.8/).length).toBeGreaterThanOrEqual(2);
  });

  test("says out loud that enrolling does not stop the asking", () => {
    // The user's C4 ruling, on the surface where it can actually be misread. A
    // card that only said "remember this machine" would leave every reader to
    // assume the obvious-but-wrong thing.
    render(<EnrollNodeCard {...props} onDone={vi.fn()} />);
    expect(screen.getByText(/every time/i)).toBeInTheDocument();
  });

  test("enrolling goes over REST, carrying the fingerprint that was shown", async () => {
    const onDone = vi.fn();
    render(<EnrollNodeCard {...props} onDone={onDone} />);
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    await waitFor(() => expect(api.enrollSshNode).toHaveBeenCalledWith({
      name: "studio", host: "192.168.1.8", user: "someone",
      fingerprints: ["256 SHA256:abc123 (ED25519)"],
    }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  test("declining enrols nothing", () => {
    const onDone = vi.fn();
    render(<EnrollNodeCard {...props} onDone={onDone} />);
    fireEvent.click(screen.getByTestId("enroll-cancel"));
    expect(api.enrollSshNode).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalled();
  });

  test("a failed enrolment says so instead of pretending it worked", async () => {
    vi.mocked(api.enrollSshNode).mockRejectedValueOnce(
      new Error("that machine is presenting a different host key"));
    const onDone = vi.fn();
    render(<EnrollNodeCard {...props} onDone={onDone} />);
    fireEvent.click(screen.getByTestId("enroll-confirm"));
    await waitFor(() =>
      expect(screen.getByTestId("enroll-error")).toHaveTextContent(/different host key/));
    expect(onDone).not.toHaveBeenCalled();
  });
});
