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
