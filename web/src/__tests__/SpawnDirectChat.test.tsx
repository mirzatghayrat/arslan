import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import SpawnDirectChat from "../components/SpawnDirectChat";
import type { Spawn } from "../types";

// Mock i18n so the component renders deterministically; do NOT mock SpawnAvatar
// (the whole point is to catch the missing SpawnAvatar import that white-screened).
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

// jsdom doesn't implement scrollIntoView (the component calls it in a mount effect).
beforeAll(() => {
  // @ts-expect-error jsdom shim
  Element.prototype.scrollIntoView = vi.fn();
});

const spawn: Spawn = {
  id: "1",
  name: "小美",
  domain: "content",
  description: "beauty blogger",
  status: "idle",
  avatarEmoji: "🤖",
  tools: [],
  skills: [],
  totalTasks: 0,
};

describe("SpawnDirectChat", () => {
  it("renders the spawn header without crashing (SpawnAvatar must be imported)", () => {
    render(
      <SpawnDirectChat
        spawn={spawn}
        chatHistory={[]}
        setChatHistory={() => {}}
        currentStyle="quartz"
      />,
    );
    expect(screen.getAllByText(/小美/).length).toBeGreaterThan(0);
  });
});
