import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));

describe("propose_connect_mcp frame", () => {
  it("sets pendingConnectMcp from the frame, env_keys carrying names/metadata only", () => {
    useArslanStore.getState().handleFrame({
      type: "propose_connect_mcp",
      call_id: "c1",
      key: "github",
      label: "GitHub",
      transport: "stdio",
      command: "npx",
      argv: ["-y", "@modelcontextprotocol/server-github"],
      url: null,
      env_keys: [{
        name: "GITHUB_PERSONAL_ACCESS_TOKEN",
        description: "A GitHub PAT.",
        get_it_url: "https://github.com/settings/tokens",
        paid: false,
      }],
      prerequisites: "Needs a GitHub personal access token.",
      requires_path: false,
      path_placeholder: null,
    } as any);

    const pc = (useArslanStore.getState() as any).pendingConnectMcp;
    expect(pc).not.toBeNull();
    expect(pc.callId).toBe("c1");
    expect(pc.label).toBe("GitHub");
    expect(pc.argv).toEqual(["-y", "@modelcontextprotocol/server-github"]);
    expect(pc.envKeys).toEqual([{
      name: "GITHUB_PERSONAL_ACCESS_TOKEN",
      description: "A GitHub PAT.",
      get_it_url: "https://github.com/settings/tokens",
      paid: false,
    }]);
    // No value field anywhere on the stored slice — only names/metadata.
    expect(JSON.stringify(pc)).not.toMatch(/ghp_|"value"/);
    expect(pc.requiresPath).toBe(false);
    expect(pc.pathPlaceholder).toBeNull();
  });

  it("carries requires_path/path_placeholder through for local-path connectors", () => {
    useArslanStore.getState().handleFrame({
      type: "propose_connect_mcp",
      call_id: "c2",
      key: "filesystem",
      label: "Filesystem",
      transport: "stdio",
      command: "npx",
      argv: ["-y", "@modelcontextprotocol/server-filesystem"],
      url: null,
      env_keys: [],
      prerequisites: "",
      requires_path: true,
      path_placeholder: "/absolute/path/to/expose",
    } as any);

    const pc = (useArslanStore.getState() as any).pendingConnectMcp;
    expect(pc.requiresPath).toBe(true);
    expect(pc.pathPlaceholder).toBe("/absolute/path/to/expose");
  });

  it("clearPendingConnectMcp resets to null", () => {
    useArslanStore.getState().handleFrame({
      type: "propose_connect_mcp", call_id: "c3", key: "memory", label: "Memory",
      transport: "stdio", command: "npx", argv: [], url: null, env_keys: [],
      prerequisites: "", requires_path: false, path_placeholder: null,
    } as any);
    (useArslanStore.getState() as any).clearPendingConnectMcp();
    expect((useArslanStore.getState() as any).pendingConnectMcp).toBeNull();
  });

  it("pendingConnectMcp starts as null", () => {
    expect((useArslanStore.getState() as any).pendingConnectMcp).toBeNull();
  });

  it("clears thinking when the frame arrives", () => {
    useArslanStore.setState({ thinking: true } as any, false);
    useArslanStore.getState().handleFrame({
      type: "propose_connect_mcp", call_id: "c4", key: "memory", label: "Memory",
      transport: "stdio", command: "npx", argv: [], url: null, env_keys: [],
      prerequisites: "", requires_path: false, path_placeholder: null,
    } as any);
    expect(useArslanStore.getState().thinking).toBe(false);
  });
});

describe("mcp_connect_followup frame", () => {
  it("clears pendingConnectMcp and appends an honest tier-aware chat note", () => {
    useArslanStore.setState({
      pendingConnectMcp: { callId: "c1" } as any,
    } as any, false);

    useArslanStore.getState().handleFrame({
      type: "mcp_connect_followup",
      server_id: 7,
      tool_count: 4,
      safe_count: 3,
      restricted_count: 1,
      assignable: true,
    } as any);

    const state = useArslanStore.getState() as any;
    expect(state.pendingConnectMcp).toBeNull();
    const note = state.items[state.items.length - 1];
    expect(note.kind).toBe("system");
    expect(note.role).toBe("arslan");
    expect(note.content).toMatch(/3 ready/);
    expect(note.content).toMatch(/1 restricted/);
  });

  it("all-restricted (assignable=false) note points at Settings, not 'ready'", () => {
    useArslanStore.getState().handleFrame({
      type: "mcp_connect_followup",
      server_id: 8,
      tool_count: 2,
      safe_count: 0,
      restricted_count: 2,
      assignable: false,
    } as any);

    const state = useArslanStore.getState() as any;
    const note = state.items[state.items.length - 1];
    expect(note.content).toMatch(/Settings/);
    expect(note.content).not.toMatch(/ready/);
  });
});
