import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import InviteConfirmCard from "../components/InviteConfirmCard";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

// Lightweight i18n mock: interpolate {{name}}/{{reason}} so assertions can match
// the rendered heading text.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, vars?: Record<string, unknown>) => {
      if (k === "invite_card.heading" && vars) {
        return `Pull ${vars.name} in because ${vars.reason}?`;
      }
      if (k === "invite_card.confirm") return "Confirm";
      if (k === "invite_card.cancel") return "Cancel";
      if (k === "invite_card.accept") return "Accept";
      if (k === "invite_card.dismiss") return "Dismiss";
      return k;
    },
  }),
}));

describe("InviteConfirmCard", () => {
  it("renders the reason and the spawn name", () => {
    render(
      <InviteConfirmCard
        spawnId={7}
        spawnName="Mermer"
        reason="needs a translator"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText(/needs a translator/)).toBeTruthy();
    expect(screen.getByText(/Mermer/)).toBeTruthy();
  });

  it("falls back to #id when no spawnName is given", () => {
    render(
      <InviteConfirmCard
        spawnId={42}
        spawnName={undefined}
        reason="r"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText(/#42/)).toBeTruthy();
  });

  it("calls onConfirm(spawnId) when 确认 is clicked", () => {
    const onConfirm = vi.fn();
    render(
      <InviteConfirmCard
        spawnId={7}
        spawnName="Mermer"
        reason="r"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("invite-confirm"));
    expect(onConfirm).toHaveBeenCalledWith(7);
  });

  it("calls onCancel when 取消 is clicked", () => {
    const onCancel = vi.fn();
    render(
      <InviteConfirmCard
        spawnId={7}
        spawnName="Mermer"
        reason="r"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByTestId("invite-cancel"));
    expect(onCancel).toHaveBeenCalled();
  });

  it("renders Accept / Dismiss labels and the inline card test id", () => {
    render(
      <InviteConfirmCard
        spawnId={7}
        spawnName="Mermer"
        reason="needs a translator"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByTestId("invite-confirm-card")).toBeTruthy();
    expect(screen.getByText("Accept")).toBeTruthy();
    expect(screen.getByText("Dismiss")).toBeTruthy();
  });
});

describe("arslanStore — propose_invite", () => {
  it("sets pendingInvite on a propose_invite frame and clears it via action", () => {
    useArslanStore.setState(initialArslanState(), true);
    expect(useArslanStore.getState().pendingInvite).toBeNull();
    useArslanStore.getState().handleFrame({
      type: "propose_invite",
      spawn_id: 9,
      reason: "needs design help",
    } as never);
    expect(useArslanStore.getState().pendingInvite).toEqual({
      spawnId: 9,
      reason: "needs design help",
    });
    useArslanStore.getState().clearPendingInvite();
    expect(useArslanStore.getState().pendingInvite).toBeNull();
  });
});
