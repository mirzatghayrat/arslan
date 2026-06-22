import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { LedgerRow } from "../components/LedgerRow";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

describe("LedgerRow", () => {
  it("non-member row calls onInvite with spawn id on click", async () => {
    const onInvite = vi.fn();
    const onKick = vi.fn();
    render(
      <LedgerRow
        spawn={{ id: 4, name: "领英智囊" }}
        isMember={false}
        onInvite={onInvite}
        onKick={onKick}
      />
    );
    await userEvent.click(screen.getByRole("button"));
    expect(onInvite).toHaveBeenCalledWith(4);
    expect(onKick).not.toHaveBeenCalled();
  });

  it("member row calls onKick with spawn id on click", async () => {
    const onInvite = vi.fn();
    const onKick = vi.fn();
    render(
      <LedgerRow
        spawn={{ id: 4, name: "领英智囊" }}
        isMember={true}
        onInvite={onInvite}
        onKick={onKick}
      />
    );
    await userEvent.click(screen.getByRole("button"));
    expect(onKick).toHaveBeenCalledWith(4);
    expect(onInvite).not.toHaveBeenCalled();
  });
});
