/**
 * skill-health.test.tsx — PC-5 per-skill health UI in the capability catalog.
 *
 * Mirrors RailMcpList's 体检 pattern: a health dot per skill row (muted until checked) +
 * a Stethoscope probe button that calls POST /registry/skills/{key}/health and expands a
 * panel with storage/scripts/references + the honest reasons the backend returns.
 *
 * Verifies the three states the endpoint can honestly report:
 *   ok            → success dot, script runnable
 *   sandbox-unavailable → warning dot + honest "sandbox unavailable" reason (NOT a false ok)
 *   degraded      → danger dot, missing storage file surfaced
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CapabilityCatalog from "../components/CapabilityCatalog";
import type { SkillHealth } from "../api/client.types";

// i18n passthrough — t() returns the key so assertions are locale-independent.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

vi.mock("../api/client", () => ({
  api: { getRegistry: vi.fn(), listSpawns: vi.fn(), updateEquipment: vi.fn(), checkSkillHealth: vi.fn() },
}));
import { api } from "../api/client";
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const CATALOG = {
  toolsets: [],
  skills: [
    { key: "runner", name: "Runner", category: "content", description: "d", tier: "safe", status: "registered", assignable: true, compatibility: "full" },
  ],
};

const OK_HEALTH: SkillHealth = {
  key: "runner", status: "ok", ok: true, sandbox_available: true, sandbox_backend: "seatbelt",
  compatibility: "full",
  storage: { ok: true, body_present: true, declared_scripts: ["entry.py"], declared_references: [],
             disk_scripts: ["entry.py"], disk_references: [], missing: [], orphaned: [] },
  scripts: [{ name: "entry.py", runnable: true, reason: "ok (sandbox backend=seatbelt)" }],
  references: [],
};

const SANDBOX_UNAVAIL_HEALTH: SkillHealth = {
  key: "runner", status: "degraded", ok: false, sandbox_available: false, sandbox_backend: "null",
  compatibility: "full",
  storage: { ok: true, body_present: true, declared_scripts: ["entry.py"], declared_references: [],
             disk_scripts: ["entry.py"], disk_references: [], missing: [], orphaned: [] },
  scripts: [{ name: "entry.py", runnable: false, reason: "sandbox unavailable (no isolation backend backend=null)" }],
  references: [],
};

const DEGRADED_HEALTH: SkillHealth = {
  key: "runner", status: "degraded", ok: false, sandbox_available: true, sandbox_backend: "seatbelt",
  compatibility: "partial",
  storage: { ok: false, body_present: true, declared_scripts: ["ghost.py"], declared_references: [],
             disk_scripts: [], disk_references: [], missing: ["ghost.py"], orphaned: [] },
  scripts: [],
  references: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  m.getRegistry.mockResolvedValue(CATALOG);
  m.listSpawns.mockResolvedValue([]);
});

describe("CapabilityCatalog — PC-5 skill health", () => {
  it("dot starts muted (unchecked) with the honest 'not checked' tooltip", async () => {
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Runner");
    const dot = screen.getByTestId("skill-health-dot-runner");
    expect(dot.className).toContain("bg-subtle-foreground");
    expect(dot.getAttribute("title")).toBe("capabilities.skill_health.unknown");
  });

  it("probe → ok: success dot + panel shows a runnable script", async () => {
    m.checkSkillHealth.mockResolvedValueOnce(OK_HEALTH);
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Runner");
    fireEvent.click(screen.getByTestId("skill-health-check-runner"));
    await waitFor(() => {
      expect(m.checkSkillHealth).toHaveBeenCalledWith("runner");
      expect(screen.getByTestId("skill-health-dot-runner").className).toContain("bg-success");
    });
    const panel = screen.getByTestId("skill-health-panel-runner");
    expect(panel).toBeInTheDocument();
    expect(panel.textContent).toContain("entry.py");
    // no sandbox warning when the backend is available
    expect(screen.queryByTestId("skill-health-sandbox-warning")).toBeNull();
  });

  it("probe → sandbox unavailable: warning dot + honest reason, never a false 'runnable'", async () => {
    m.checkSkillHealth.mockResolvedValueOnce(SANDBOX_UNAVAIL_HEALTH);
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Runner");
    fireEvent.click(screen.getByTestId("skill-health-check-runner"));
    await waitFor(() => {
      expect(screen.getByTestId("skill-health-dot-runner").className).toContain("bg-warning");
    });
    expect(screen.getByTestId("skill-health-dot-runner").getAttribute("title"))
      .toBe("capabilities.skill_health.sandbox_unavailable");
    // the honest reason is surfaced in the panel
    const panel = screen.getByTestId("skill-health-panel-runner");
    expect(panel.textContent).toContain("sandbox unavailable");
    expect(screen.getByTestId("skill-health-sandbox-warning")).toBeInTheDocument();
  });

  it("probe → degraded storage: danger dot + missing file surfaced", async () => {
    m.checkSkillHealth.mockResolvedValueOnce(DEGRADED_HEALTH);
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Runner");
    fireEvent.click(screen.getByTestId("skill-health-check-runner"));
    await waitFor(() => {
      expect(screen.getByTestId("skill-health-dot-runner").className).toContain("bg-danger");
    });
    const panel = screen.getByTestId("skill-health-panel-runner");
    expect(panel.textContent).toContain("capabilities.skill_health.missing");
    expect(panel.textContent).toContain("ghost.py");
  });

  it("second click toggles the panel closed without re-probing", async () => {
    m.checkSkillHealth.mockResolvedValueOnce(OK_HEALTH);
    render(<CapabilityCatalog kind="skills" />);
    await screen.findByText("Runner");
    fireEvent.click(screen.getByTestId("skill-health-check-runner"));
    await screen.findByTestId("skill-health-panel-runner");
    fireEvent.click(screen.getByTestId("skill-health-check-runner"));  // collapse
    expect(screen.queryByTestId("skill-health-panel-runner")).toBeNull();
    expect(m.checkSkillHealth).toHaveBeenCalledTimes(1);               // no re-probe
  });
});
