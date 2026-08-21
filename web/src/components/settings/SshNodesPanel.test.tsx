import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, test, expect, vi, beforeEach } from "vitest";
import SshNodesPanel from "./SshNodesPanel";
import { api } from "../../api/client";
import "../../i18n";

vi.mock("../../api/client", () => ({
  api: { listSshNodes: vi.fn(), revokeSshNode: vi.fn(async () => ({ ok: true })) },
}));

const NODE = {
  id: 7, name: "studio", host: "192.168.1.8", user: "someone",
  fingerprints: ["256 SHA256:abc (ED25519)"],
  created_at: null, last_used_at: null,
};

describe("SshNodesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listSshNodes).mockResolvedValue({ nodes: [NODE], enabled: true });
  });

  test("lists an enrolled machine with its fingerprint", async () => {
    render(<SshNodesPanel />);
    expect(await screen.findByText("studio")).toBeInTheDocument();
    expect(screen.getByText("256 SHA256:abc (ED25519)")).toBeInTheDocument();
  });

  test("says that forgetting cannot reach into the other machine", async () => {
    // Not decoration. Someone who believes the key is gone when it is still in
    // that machine's authorized_keys is worse off than someone told to go
    // delete it — so the panel has to say which of the two happened.
    render(<SshNodesPanel />);
    await screen.findByText("studio");
    expect(screen.getByText(/cannot remove the key line/i)).toBeInTheDocument();
  });

  test("says that enrolling did not remove the approval step", async () => {
    render(<SshNodesPanel />);
    await screen.findByText("studio");
    expect(screen.getByText(/still need your approval every time/i)).toBeInTheDocument();
  });

  test("forgetting a machine calls revoke and refreshes", async () => {
    render(<SshNodesPanel />);
    await screen.findByText("studio");
    vi.mocked(api.listSshNodes).mockResolvedValue({ nodes: [], enabled: true });
    fireEvent.click(screen.getByTestId("ssh-node-revoke-7"));
    await waitFor(() => expect(api.revokeSshNode).toHaveBeenCalledWith(7));
    await waitFor(() => expect(screen.getByTestId("ssh-nodes-empty")).toBeInTheDocument());
  });

  test("an empty list reads as empty, not as broken", async () => {
    vi.mocked(api.listSshNodes).mockResolvedValue({ nodes: [], enabled: true });
    render(<SshNodesPanel />);
    expect(await screen.findByTestId("ssh-nodes-empty")).toBeInTheDocument();
  });
});
