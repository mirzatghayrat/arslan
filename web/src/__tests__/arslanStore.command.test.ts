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

    const pc = (useArslanStore.getState() as any).pendingCommand;
    expect(pc).not.toBeNull();
    expect(pc.callId).toBe("c1");
    expect(pc.pretty).toBe("git status");
    expect(pc.reason).toBe("r");
  });

  it("keeps the sandbox question and Arslan's reason (0.1.51 P3); ignores an unknown one", () => {
    const st = useArslanStore.getState();
    st.handleFrame({ type: "propose_run_command", call_id: "s1", pretty: "mv a ~/b",
                     sandbox: "outside", why: "move it to Pictures" } as any);
    let pc = (useArslanStore.getState() as any).pendingCommand;
    expect([pc.sandbox, pc.why]).toEqual(["outside", "move it to Pictures"]);
    st.handleFrame({ type: "propose_run_command", call_id: "s2", pretty: "mv a ~/b", sandbox: "retry" } as any);
    pc = (useArslanStore.getState() as any).pendingCommand;
    expect([pc.sandbox, pc.why]).toEqual(["retry", ""]);
    st.handleFrame({ type: "propose_run_command", call_id: "s3", pretty: "ls", sandbox: "sideways" } as any);
    pc = (useArslanStore.getState() as any).pendingCommand;
    expect(pc.sandbox).toBeUndefined();
  });

  it("missing reason stored as empty string", () => {
    useArslanStore.getState().handleFrame({
      type: "propose_run_command",
      call_id: "c2",
      pretty: "ls -la",
    } as any);

    const pc = (useArslanStore.getState() as any).pendingCommand;
    expect(pc.reason).toBe("");
  });

  it("clearPendingCommand resets to null", () => {
    useArslanStore.getState().handleFrame({
      type: "propose_run_command",
      call_id: "c3",
      pretty: "pwd",
    } as any);
    (useArslanStore.getState() as any).clearPendingCommand();
    expect((useArslanStore.getState() as any).pendingCommand).toBeNull();
  });

  it("pendingCommand starts as null", () => {
    expect((useArslanStore.getState() as any).pendingCommand).toBeNull();
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
