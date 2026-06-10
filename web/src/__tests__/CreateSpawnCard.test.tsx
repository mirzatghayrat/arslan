import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import "../i18n";
import CreateSpawnCard from "../components/arslan/CreateSpawnCard";

const draft = {
  name: "beauty-guru",
  domain: "content-creator.xiaohongshu",
  capabilities: ["content-generation", "info-gathering"],
  persona_role: "senior skincare content creator",
  persona_tone: "data-driven",
  reason: "Recurring xiaohongshu content work",
};

it("renders without crashing when the LLM returns capabilities as a string (not an array)", () => {
  // Repro of the white-screen crash: DeepSeek returned capabilities as a comma-joined
  // string, and `capabilities.join(...)` threw a render-time TypeError.
  const malformed = {
    name: "数据洞察者",
    domain: "data-analysis.internet",
    capabilities: "互联网数据采集,数据分析与可视化,撰写数据分析报告" as unknown as string[],
  };
  render(
    <MemoryRouter>
      <CreateSpawnCard
        draft={malformed}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
        onRefine={vi.fn()}
        onRouteToExisting={vi.fn()}
      />
    </MemoryRouter>,
  );
  // the comma-joined string is split and shown as a normal capabilities list
  expect(screen.getByText(/互联网数据采集, 数据分析与可视化/)).toBeInTheDocument();
});

function renderCard(props: Partial<React.ComponentProps<typeof CreateSpawnCard>> = {}) {
  return render(
    <MemoryRouter>
      <CreateSpawnCard
        draft={draft}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
        onRefine={vi.fn()}
        onRouteToExisting={vi.fn()}
        {...props}
      />
    </MemoryRouter>,
  );
}

describe("CreateSpawnCard", () => {
  it("shows the drafted spawn name and domain", () => {
    renderCard();
    expect(screen.getByText(/beauty-guru/)).toBeInTheDocument();
    expect(screen.getByText(/content-creator\.xiaohongshu/)).toBeInTheDocument();
  });

  it("calls onCreate with the draft when Create is clicked", async () => {
    const onCreate = vi.fn();
    renderCard({ onCreate });
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));
    expect(onCreate).toHaveBeenCalledWith(draft, undefined);
  });

  it("calls onDismiss when Dismiss is clicked", async () => {
    const onDismiss = vi.fn();
    renderCard({ onDismiss });
    await userEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(onDismiss).toHaveBeenCalled();
  });

  it("shows an overlap warning and offers Route to existing", async () => {
    const onRoute = vi.fn();
    render(
      <MemoryRouter>
        <CreateSpawnCard draft={draft} overlaps={{ spawn_id: 3, name: "GuGu", axes: ["fundamental vs technical"] }}
          onCreate={vi.fn()} onDismiss={vi.fn()} onRefine={vi.fn()} onRouteToExisting={onRoute} />
      </MemoryRouter>,
    );
    expect(screen.getAllByText(/GuGu/).length).toBeGreaterThanOrEqual(1);
    await userEvent.click(screen.getByRole("button", { name: /route to/i }));
    expect(onRoute).toHaveBeenCalledWith(3);
  });

  it("Tweak reveals an inline input and calls onRefine", async () => {
    const onRefine = vi.fn();
    render(
      <MemoryRouter>
        <CreateSpawnCard draft={draft} onCreate={vi.fn()} onDismiss={vi.fn()} onRefine={onRefine} onRouteToExisting={vi.fn()} />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /tweak/i }));
    const input = screen.getByPlaceholderText(/refine/i);
    await userEvent.type(input, "more data-driven{enter}");
    expect(onRefine).toHaveBeenCalledWith("more data-driven");
  });

  it("Create passes differentiation when overlap present and user creates anyway", async () => {
    const onCreate = vi.fn();
    render(
      <MemoryRouter>
        <CreateSpawnCard draft={draft} overlaps={{ spawn_id: 3, name: "GuGu", axes: ["fundamental vs technical"] }}
          onCreate={onCreate} onDismiss={vi.fn()} onRefine={vi.fn()} onRouteToExisting={vi.fn()} />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /create new/i }));
    const diff = screen.getByPlaceholderText(/differ/i);
    await userEvent.type(diff, "technical analysis focus");
    await userEvent.click(screen.getByRole("button", { name: /^create$/i }));
    expect(onCreate).toHaveBeenCalledWith(draft, "technical analysis focus");
  });
});
