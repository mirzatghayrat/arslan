/**
 * tool-activity-card.test.tsx — finished-message tool cards are no longer a JSON wall
 * (user feedback: `Standard Executor tool render_deck: OK` + raw args). The headline is
 * the same natural language as LiveActivity (shared lib/toolHumanize), the outcome is
 * plain words, and the raw args/result JSON hides behind a collapsed 详情 toggle.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import ToolActivityCard from "../components/ToolActivityCard";
import type { ToolActivity } from "../types";

// t mock with naive {{var}} interpolation (same pattern as live-activity.test).
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, o?: Record<string, unknown>) => {
      const zh: Record<string, string> = {
        "activity.search": "搜索 {{q}}",
        "activity.deck": "生成 PPT",
        "activity.deck_fail": "PPT 生成遇到问题",
        "activity.n_results": "{{count}} 条结果",
        "activity.deck_done": "已生成 PPTX · {{slides}} 页",
        "activity.details": "详情",
        "activity.args": "输入",
        "activity.result": "结果",
      };
      let s = zh[k] ?? k;
      for (const [key, v] of Object.entries(o ?? {})) s = s.replace(`{{${key}}}`, String(v));
      return s;
    },
  }),
}));

const searchActivity: ToolActivity = {
  id: "m1-tool-0",
  toolName: "web_search",
  emoji: "🔧",
  status: "completed",
  stepStatus: "ok",
  action: '{"query":"OKX 永续合约"}',
  outputSummary: "5 results",
  collapsed: false,
};

describe("ToolActivityCard", () => {
  it("shows a humanized headline + plain-words outcome, NOT the raw JSON", () => {
    render(<ToolActivityCard activity={searchActivity} />);
    // Same wording as the live view (shared toolHumanize) + plain outcome.
    expect(screen.getByText("搜索 「OKX 永续合约」")).toBeTruthy();
    expect(screen.getByText(/5 条结果/)).toBeTruthy();
    // The raw args JSON is NOT visible by default.
    expect(screen.queryByText(/"query"/)).toBeNull();
    expect(screen.queryByText(/Standard Executor/)).toBeNull();
  });

  it("reveals the raw args/result only after toggling 详情", () => {
    render(<ToolActivityCard activity={searchActivity} />);
    fireEvent.click(screen.getByText("详情"));
    expect(screen.getByText('{"query":"OKX 永续合约"}')).toBeTruthy();
    expect(screen.getByText("5 results")).toBeTruthy(); // raw result string, in the details pane
    // Toggle back → hidden again.
    fireEvent.click(screen.getByText("详情"));
    expect(screen.queryByText(/"query"/)).toBeNull();
  });

  it("render_deck success shows ✓ wording with slide count from the pptx artifact", () => {
    const activity: ToolActivity = {
      id: "m2-tool-0",
      toolName: "render_deck",
      emoji: "🔧",
      status: "completed",
      stepStatus: "ok",
      action: '{"slides":[]}',
      outputSummary: "ok",
      collapsed: false,
      artifactPptx: { filename: "okx.pptx", bytesB64: "UEsDBA==", slides: 14 },
    };
    render(<ToolActivityCard activity={activity} />);
    expect(screen.getByText("生成 PPT")).toBeTruthy();
    expect(screen.getByText(/已生成 PPTX · 14 页/)).toBeTruthy();
  });

  it("error step gets the calm fail line and no fabricated outcome", () => {
    const activity: ToolActivity = {
      id: "m3-tool-0",
      toolName: "render_deck",
      emoji: "🔧",
      status: "completed",
      stepStatus: "error",
      action: '{"slides":[]}',
      outputSummary: "python-pptx not installed",
      collapsed: false,
    };
    render(<ToolActivityCard activity={activity} />);
    expect(screen.getByText("PPT 生成遇到问题")).toBeTruthy();
    // internal error text stays behind 详情
    expect(screen.queryByText(/python-pptx/)).toBeNull();
  });
});
