/** v0.1.64 CAP4a-1: the import panel imports the commit its listing read, never whatever HEAD is by then. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import * as discovery from "../api/discovery";
import SkillImportPanel from "../components/SkillImportPanel";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the import panel", () => {
  it("imports the skill at the commit the listing was read at", async () => {
    vi.spyOn(discovery, "scanSkills").mockResolvedValue({
      repo: { full_name: "acme/skills", html_url: "https://github.com/acme/skills", license: "MIT", stars: 1 },
      license_ok: true, license_note: null, commit: "0123456789abcdef0123456789abcdef01234567",
      skills: [{ path: "skills/weekly/SKILL.md", name: "Weekly", description: "d", scripts: [], importable: true, reason: null }],
    });
    const imported = vi.spyOn(discovery, "importSkill").mockResolvedValue({} as never);
    const { container } = render(<SkillImportPanel />);
    fireEvent.change(container.querySelector("input")!, { target: { value: "acme/skills" } });
    fireEvent.click(screen.getByText("capabilities.import.scan"));
    fireEvent.click(await screen.findByText("capabilities.import.import"));
    await vi.waitFor(() => expect(imported).toHaveBeenCalled());
    expect(imported).toHaveBeenCalledWith("acme/skills@0123456789abcdef0123456789abcdef01234567", "skills/weekly/SKILL.md");
  });
});
