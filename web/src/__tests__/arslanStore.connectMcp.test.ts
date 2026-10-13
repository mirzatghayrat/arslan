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

    const pc = (useArslanStore.getState() as any).pendingConnectMcps[0];
    expect(pc).toBeDefined();
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

    const pc = (useArslanStore.getState() as any).pendingConnectMcps[0];
    expect(pc.requiresPath).toBe(true);
    expect(pc.pathPlaceholder).toBe("/absolute/path/to/expose");
  });

  it("clearPendingConnectMcp(id) removes that card and only it", () => {
    const frame = (id: string) => ({
      type: "propose_connect_mcp", call_id: id, key: "memory", label: "Memory",
      transport: "stdio", command: "npx", argv: [], url: null, env_keys: [],
      prerequisites: "", requires_path: false, path_placeholder: null,
    } as any);
    useArslanStore.getState().handleFrame(frame("c3"));
    useArslanStore.getState().handleFrame(frame("c3b"));
    (useArslanStore.getState() as any).clearPendingConnectMcp("c3");
    expect((useArslanStore.getState() as any).pendingConnectMcps.map((c: any) => c.callId)).toEqual(["c3b"]);
    (useArslanStore.getState() as any).clearPendingConnectMcp("c3b");
    expect((useArslanStore.getState() as any).pendingConnectMcps).toEqual([]);
  });

  it("pendingConnectMcps starts empty", () => {
    expect((useArslanStore.getState() as any).pendingConnectMcps).toEqual([]);
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
  it("clears the connect card that connected the server and appends an honest tier-aware chat note", () => {
    useArslanStore.setState({
      pendingConnectMcps: [{ callId: "c1", appliedServerId: 7 }, { callId: "c2" }] as any,
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
    expect(state.pendingConnectMcps.map((c: any) => c.callId)).toEqual(["c2"]);       // the card that connected it; not the other
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
