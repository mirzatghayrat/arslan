/**
 * MemoryDataSection — the "Memory & Data" settings section.
 *
 * Verifies the section is self-contained and hosts (per spec B1): the embedding
 * config (<EmbeddingSettings/>), the session-end distillation toggle, and the
 * run-debug retention-days input. Also asserts the retention control now uses the
 * NEW i18n keys (the hardcoded Chinese label/hint is gone) and that the toggle +
 * retention onChange callbacks fire. Behavior mirrors the pre-extraction inline
 * controls — no persistence change here (Task 6 owns save).
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// EmbeddingSettings calls api.embeddingStatus() in an effect on mount.
vi.mock("../api/client", () => ({
  api: {
    embeddingStatus: vi.fn().mockResolvedValue(null),
    reindexEmbeddings: vi.fn().mockResolvedValue({}),
    downloadEmbeddingModel: vi.fn().mockResolvedValue({}),
  },
  API_BASE: "",
}));

import MemoryDataSection from "../components/settings/MemoryDataSection";

type Props = React.ComponentProps<typeof MemoryDataSection>;

function setup(overrides: Partial<Props> = {}) {
  const props: Props = {
    providerConfigs: [],
    embeddingConfigId: "",
    onEmbeddingConfigIdChange: vi.fn(),
    distillOnSessionEnd: true,
    onDistillChange: vi.fn(),
    retentionDays: 30,
    onRetentionDaysChange: vi.fn(),
    ...overrides,
  };
  render(<MemoryDataSection {...props} />);
  return props;
}

describe("MemoryDataSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders EmbeddingSettings, the distill toggle, and the retention input", () => {
    setup();
    // EmbeddingSettings renders its own section heading key.
    expect(screen.getByText("settings.sectionEmbedding")).toBeInTheDocument();
    expect(document.getElementById("settings-distill-toggle")).not.toBeNull();
    expect(document.getElementById("settings-run-debug-retention-days")).not.toBeNull();
  });

  it("retention control uses the NEW i18n keys (no hardcoded Chinese)", () => {
    setup();
    expect(screen.getByText("settings.retentionLabel")).toBeInTheDocument();
    expect(screen.getByText("settings.retentionHint")).toBeInTheDocument();
    // The old hardcoded Chinese must be gone.
    expect(screen.queryByText("运行调试详情保留天数")).toBeNull();
    expect(
      screen.queryByText(/超过此天数的 run/),
    ).toBeNull();
  });

  it("fires onDistillChange when the toggle is flipped", () => {
    const props = setup({ distillOnSessionEnd: true });
    const toggle = document.getElementById("settings-distill-toggle") as HTMLInputElement;
    fireEvent.click(toggle);
    expect(props.onDistillChange).toHaveBeenCalledWith(false);
  });

  it("fires onRetentionDaysChange with a clamped value", () => {
    const props = setup();
    const input = document.getElementById("settings-run-debug-retention-days") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "7" } });
    expect(props.onRetentionDaysChange).toHaveBeenCalledWith(7);
    // Below-minimum / empty input clamps to 1 (behavior preserved).
    fireEvent.change(input, { target: { value: "0" } });
    expect(props.onRetentionDaysChange).toHaveBeenCalledWith(1);
  });
});
