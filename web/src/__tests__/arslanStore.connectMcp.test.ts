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

  // 0.1.61 §A4 (PR 2b, fix round 2, F3): the follow-up is fanned out to every window on the conversation, and only the window that connected
  // the server marked its card. The server now names the proposal's card (the confirm's call_id, echoed), so every window closes its own copy.
  const followup = (extra: Record<string, unknown> = {}) => ({ type: "mcp_connect_followup", server_id: 7, tool_count: 4, safe_count: 3,
    restricted_count: 1, assignable: true, ...extra }) as any;
  const pending = () => (useArslanStore.getState() as any).pendingConnectMcps.map((c: any) => c.callId);

  it("closes the card its call_id names in a window that never connected it: nothing was marked there", () => {
    useArslanStore.setState({ pendingConnectMcps: [{ callId: "c1" }, { callId: "c2" }] as any } as any, false);
    useArslanStore.getState().handleFrame(followup({ call_id: "c1" }));
    expect(pending()).toEqual(["c2"]);
    const items = (useArslanStore.getState() as any).items;
    expect(items[items.length - 1].content).toMatch(/3 ready/);                       // and the honest note is still added
  });

  it("closes the card it names and only that one, whichever card was marked with the server", () => {
    useArslanStore.setState({ pendingConnectMcps: [{ callId: "c1", appliedServerId: 7 }, { callId: "c2" }] as any } as any, false);
    useArslanStore.getState().handleFrame(followup({ call_id: "c2" }));
    expect(pending()).toEqual(["c1"]);                                                // c1 has its own follow-up coming
  });

  it("names a card that is not here: closes nothing, and the note is still added", () => {
    useArslanStore.setState({ pendingConnectMcps: [{ callId: "c1" }], items: [] } as any, false);
    useArslanStore.getState().handleFrame(followup({ call_id: "zzz" }));
    expect(pending()).toEqual(["c1"]);
    expect((useArslanStore.getState() as any).items).toHaveLength(1);
  });

  it("a proposal sent again after its card was marked replaces the card and drops the mark, and the follow-up's id still closes it", () => {
    const propose = { type: "propose_connect_mcp", call_id: "c1", key: "memory", label: "Memory", transport: "stdio", command: "npx", argv: [],
      url: null, env_keys: [], prerequisites: "", requires_path: false, path_placeholder: null } as any;
    useArslanStore.getState().handleFrame(propose);
    useArslanStore.getState().markConnectApplied("c1", 7);
    useArslanStore.getState().handleFrame(propose);                                    // a replay: the same card, without the mark
    expect((useArslanStore.getState() as any).pendingConnectMcps[0]).not.toHaveProperty("appliedServerId");
    useArslanStore.getState().handleFrame(followup({ call_id: "c1" }));
    expect(pending()).toEqual([]);
  });

  it("a follow-up that names no card keeps the old rule: the card that recorded connecting that server closes, and no other", () => {
    useArslanStore.setState({ pendingConnectMcps: [{ callId: "c1" }, { callId: "c2", appliedServerId: 7 }, { callId: "c3", appliedServerId: 8 }] as any } as any, false);
    useArslanStore.getState().handleFrame(followup());
    expect(pending()).toEqual(["c1", "c3"]);
  });

  it("an empty call_id names no card: the follow-up is judged by its server, like one without an id", () => {
    useArslanStore.setState({ pendingConnectMcps: [{ callId: "c1" }, { callId: "c2", appliedServerId: 7 }] as any } as any, false);
    useArslanStore.getState().handleFrame(followup({ call_id: "" }));
    expect(pending()).toEqual(["c1"]);
  });

  it("a follow-up that names neither a card nor a server closes nothing: a card that has not connected anything has no server either", () => {
    useArslanStore.setState({ pendingConnectMcps: [{ callId: "c1" }, { callId: "c2", appliedServerId: 7 }] as any } as any, false);
    useArslanStore.getState().handleFrame({ type: "mcp_connect_followup", tool_count: 0, safe_count: 0, restricted_count: 0, assignable: false } as any);
    expect(pending()).toEqual(["c1", "c2"]);
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
