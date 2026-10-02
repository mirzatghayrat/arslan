/** 0.1.52 S1 (D1): Settings › Memory › "Remember me and use it in conversations". */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../components/EmbeddingSettings", () => ({ default: () => null }));
vi.mock("../components/settings/DeletionManifestExport", () => ({ default: () => null }));
vi.mock("../components/settings/CreateBackupButton", () => ({ default: () => null }));

import MemoryDataSection from "../components/settings/MemoryDataSection";
import { FIELD_HOMES } from "../components/settings/sectionRegistry";

afterEach(() => cleanup());

describe("Remember me and use it in conversations", () => {
  const base = { providerConfigs: [], embeddingConfigId: "", onEmbeddingConfigIdChange: vi.fn(),
    distillOnSessionEnd: false, onDistillChange: vi.fn(), retentionDays: 30, onRetentionDaysChange: vi.fn() };

  it("is on unless turned off and reports changes", () => {
    const onChange = vi.fn();
    const { rerender } = render(<MemoryDataSection {...base} onMemoryInConversationsChange={onChange} />);
    const toggle = screen.getByTestId("settings-memory-in-conversations") as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(false);
    rerender(<MemoryDataSection {...base} memoryInConversations={false} onMemoryInConversationsChange={onChange} />);
    expect((screen.getByTestId("settings-memory-in-conversations") as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText("settings.memoryInConversationsDesc")).toBeInTheDocument();
    expect(FIELD_HOMES["memory.in_conversations"]).toBe("memory");
  });
});
