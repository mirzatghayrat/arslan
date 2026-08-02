/**
 * Toggling back to the main thread must not destroy the sandbox conversation.
 *
 * Reported: type a task into a spawn's sandbox, click the spawn's name at the
 * top to go back to the main chat, and everything typed there is gone. The user
 * is right about the rule too — a sandbox should only be cleared by CONFIRM &
 * MERGE or DISCARD, because those are the two decisions that mean "I am done
 * with it".
 *
 * The cause is not a missing feature; it contradicts this file's own design.
 * OrchestratorChat's comment says every open session stays MOUNTED with its
 * socket alive and only the active one is visible — that is the entire reason
 * SandboxPanel takes a `hidden` prop. But the header chip called
 * `closeSandbox`, which removes the session from `openSandboxes`, unmounting
 * the panel and taking its `messages` state with it.
 *
 * So the chip was destroying a session where it should have been switching
 * panes.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import SandboxPanel from "../components/SandboxPanel";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

vi.mock("../hooks/useWebSocket", () => ({
  useWebSocket: () => ({ send: vi.fn(), setLastMessageId: vi.fn() }),
}));

// jsdom implements no layout, so the panel's auto-scroll would throw.
Element.prototype.scrollIntoView = vi.fn();

const spawn = { id: "7", name: "Research Analyst", domain: "research" } as never;

function renderPanel(hidden: boolean) {
  return render(
    <SandboxPanel
      spawn={spawn}
      sessionId="sbx-7-0-1"
      seed={null}
      conversationId="thread-1"
      hidden={hidden}
      onClose={vi.fn()}
      onMerged={vi.fn()}
    />,
  );
}

describe("a hidden sandbox keeps its conversation", () => {
  it("hiding the panel does not clear what was typed into it", () => {
    const { rerender, container } = renderPanel(false);

    const input = container.querySelector("input, textarea") as HTMLElement;
    expect(input, "no composer found in the sandbox").toBeTruthy();
    fireEvent.change(input, { target: { value: "draft a brief on SEA payments" } });
    expect((input as HTMLInputElement).value).toContain("SEA payments");

    // Switch to the main thread and back — the panel stays MOUNTED, just hidden.
    rerender(
      <SandboxPanel spawn={spawn} sessionId="sbx-7-0-1" seed={null}
        conversationId="thread-1" hidden onClose={vi.fn()} onMerged={vi.fn()} />,
    );
    rerender(
      <SandboxPanel spawn={spawn} sessionId="sbx-7-0-1" seed={null}
        conversationId="thread-1" hidden={false} onClose={vi.fn()} onMerged={vi.fn()} />,
    );

    const after = container.querySelector("input, textarea") as HTMLInputElement;
    expect(after.value, "the sandbox lost its draft when hidden").toContain("SEA payments");
  });

  it("hidden means invisible, not unmounted", () => {
    // Discriminating: a panel that returned `null` when hidden would satisfy
    // "the user cannot see it" and lose every bit of state — which is exactly
    // the bug, one level down.
    const { container } = renderPanel(true);
    expect(container.firstChild, "hidden panel unmounted itself").not.toBeNull();
    expect((container.firstChild as HTMLElement).className).toContain("hidden");
  });
});

describe("only an explicit decision closes a sandbox", () => {
  it("the header chip switches panes instead of closing", () => {
    // 🔴 Searched the WHOLE file. The first version sliced 4000 chars from
    // `const closeSandbox` (line ~252) and asserted against that — the chip is
    // at ~420, outside the window, so the test passed against the buggy code.
    // A test that cannot see what it claims to check is not a test.
    const src = readFileSync(resolve(SRC, "components/OrchestratorChat.tsx"), "utf8");
    expect(src).not.toMatch(/activeSandboxSpawnId === spawn\.id\) \{\s*closeSandbox\(spawn\.id\);/);
  });

  it("Confirm & Merge and Discard still close it", () => {
    // The other half: if switching stopped closing AND these stopped closing,
    // a sandbox could never be dismissed at all.
    const src = readFileSync(resolve(SRC, "components/OrchestratorChat.tsx"), "utf8");
    expect(src).toMatch(/onClose=\{\(\) => closeSandbox\(spawn\.id\)\}/);
    expect(src).toMatch(/onMerged=\{[\s\S]{0,900}?closeSandbox\(spawn\.id\)/);
  });
});
