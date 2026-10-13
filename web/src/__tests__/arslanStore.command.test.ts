import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));

describe("propose_run_command frame", () => {
  it("sets pendingCommand with pretty + reason", () => {
    useArslanStore.getState().handleFrame({
      type: "propose_run_command",
      call_id: "c1",
      command: "git",
      argv: ["git", "status"],
      pretty: "git status",
      reason: "r",
    } as any);

    const pc = (useArslanStore.getState() as any).pendingCommands[0];
    expect(pc).toBeDefined();
    expect(pc.callId).toBe("c1");
    expect(pc.pretty).toBe("git status");
    expect(pc.reason).toBe("r");
  });

  it("keeps the sandbox question and Arslan's reason (0.1.51 P3); ignores an unknown one", () => {
    const st = useArslanStore.getState();
    const card = (id: string) => (useArslanStore.getState() as any).pendingCommands.find((c: any) => c.callId === id);
    st.handleFrame({ type: "propose_run_command", call_id: "s1", pretty: "mv a ~/b",
                     sandbox: "outside", why: "move it to Pictures" } as any);
    let pc = card("s1");
    expect([pc.sandbox, pc.why]).toEqual(["outside", "move it to Pictures"]);
    st.handleFrame({ type: "propose_run_command", call_id: "s2", pretty: "mv a ~/b", sandbox: "retry" } as any);
    pc = card("s2");
    expect([pc.sandbox, pc.why]).toEqual(["retry", ""]);
    st.handleFrame({ type: "propose_run_command", call_id: "s3", pretty: "ls", sandbox: "sideways" } as any);
    pc = card("s3");
    expect(pc.sandbox).toBeUndefined();
  });

  it("missing reason stored as empty string", () => {
    useArslanStore.getState().handleFrame({
      type: "propose_run_command",
      call_id: "c2",
      pretty: "ls -la",
    } as any);

    const pc = (useArslanStore.getState() as any).pendingCommands[0];
    expect(pc.reason).toBe("");
  });

  it("clearPendingCommand(id) removes that card and only it", () => {
    const h = useArslanStore.getState().handleFrame;
    h({ type: "propose_run_command", call_id: "c3", pretty: "pwd" } as any);
    h({ type: "propose_run_command", call_id: "c3b", pretty: "ls" } as any);
    (useArslanStore.getState() as any).clearPendingCommand("nope");
    expect((useArslanStore.getState() as any).pendingCommands.map((c: any) => c.callId)).toEqual(["c3", "c3b"]);
    (useArslanStore.getState() as any).clearPendingCommand("c3");
    expect((useArslanStore.getState() as any).pendingCommands.map((c: any) => c.callId)).toEqual(["c3b"]);
    (useArslanStore.getState() as any).clearPendingCommand("c3b");
    expect((useArslanStore.getState() as any).pendingCommands).toEqual([]);
  });

  it("a second command card waits behind the first and does not replace it; the same call id again is one card", () => {
    const h = useArslanStore.getState().handleFrame;
    h({ type: "propose_run_command", call_id: "c5", pretty: "git push" } as any);
    h({ type: "propose_run_command", call_id: "c6", pretty: "git pull" } as any);
    h({ type: "propose_run_command", call_id: "c5", pretty: "git push --force" } as any);       // sent again
    const cards = (useArslanStore.getState() as any).pendingCommands;
    expect(cards.map((c: any) => [c.callId, c.pretty])).toEqual([["c6", "git pull"], ["c5", "git push --force"]]);   // the newest arrival last
  });

  it("pendingCommands starts empty", () => {
    expect((useArslanStore.getState() as any).pendingCommands).toEqual([]);
  });

  it("clears thinking when the frame arrives", () => {
    useArslanStore.setState({ thinking: true } as any, false);
    useArslanStore.getState().handleFrame({
      type: "propose_run_command",
      call_id: "c4",
      pretty: "git status",
    } as any);
    expect(useArslanStore.getState().thinking).toBe(false);
  });
});
