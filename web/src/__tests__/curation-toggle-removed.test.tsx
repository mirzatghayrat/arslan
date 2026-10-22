/**
 * C8-3 (v0.1.63): the curation loop is gone, and so is its switch in Settings ›
 * Background. Old stored values stay in the database, unread.
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../components/settings/ProactiveDiagnosisCap", () => ({ default: () => null }));

import AutomationSection from "../components/settings/AutomationSection";
import { FIELD_HOMES } from "../components/settings/sectionRegistry";
import { toBackendSettingsPatch } from "../api/adapters";

describe("curation toggle", () => {
  it("is not in the Background section any more", () => {
    render(<AutomationSection heartbeatEnabled={false} heartbeatChecklist="" />);
    expect(document.getElementById("settings-curation-toggle")).toBeNull();
    expect(screen.queryByText("settings.labelCuration")).toBeNull();
    // Positive control: the section still renders its other switches.
    expect(screen.getByTestId("heartbeat-toggle")).toBeTruthy();
  });

  it("has no settings home and no wire key", () => {
    expect(FIELD_HOMES["curation.enabled"]).toBeUndefined();
    expect(toBackendSettingsPatch({ curationEnabled: true } as never)).toEqual({});
  });
});
