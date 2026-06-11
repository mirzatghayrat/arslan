import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import "../i18n";
import EscalationBanner from "../components/arslan/EscalationBanner";
import type { EscalationInfo } from "../types";

const base: EscalationInfo = {
  spawnId: 7,
  spawnName: "Scout",
  kind: "capability",
  need: "discord access",
  status: "resolving",
};

describe("EscalationBanner", () => {
  it("shows the need and a resolving line while resolving", () => {
    render(<EscalationBanner info={base} />);
    expect(screen.getByText(/discord access/)).toBeInTheDocument();
    expect(screen.getByText(/Arslan is resolving/)).toBeInTheDocument();
  });

  it("resolved with detail: how-text visible, detail hidden until Details clicked", async () => {
    render(
      <EscalationBanner
        info={{ ...base, status: "resolved", how: "granted", detail: "discord toolset, 3 turns" }}
      />,
    );
    expect(screen.getByText(/Arslan granted a capability/)).toBeInTheDocument();
    expect(screen.queryByText(/discord toolset, 3 turns/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Details/ }));
    expect(screen.getByText(/discord toolset, 3 turns/)).toBeInTheDocument();
  });

  it("refused shows the why text", () => {
    render(
      <EscalationBanner info={{ ...base, kind: "data", status: "refused", why: "action, not a need" }} />,
    );
    expect(screen.getByText(/action, not a need/)).toBeInTheDocument();
  });
});
