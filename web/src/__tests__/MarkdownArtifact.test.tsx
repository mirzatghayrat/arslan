import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import "../i18n";
import MarkdownArtifact, { LONG_OUTPUT_THRESHOLD } from "../components/arslan/MarkdownArtifact";

const long = "# Report\n" + "lorem ipsum ".repeat(120); // > 800 chars

describe("MarkdownArtifact", () => {
  it("exports a configurable threshold of 800", () => {
    expect(LONG_OUTPUT_THRESHOLD).toBe(800);
  });

  it("collapses by default and expands on click", async () => {
    render(<MarkdownArtifact title="数据研究" content={long} downloadName="数据研究-11.md" />);
    expect(screen.getByRole("button", { name: /download/i })).toBeInTheDocument();
    const expand = screen.getByRole("button", { name: /expand|show more/i });
    await userEvent.click(expand);
    expect(screen.getByRole("button", { name: /collapse|show less/i })).toBeInTheDocument();
  });

  it("downloads a .md blob with the markdown type", async () => {
    const created: { type?: string } = {};
    const origCreate = URL.createObjectURL;
    const origRevoke = URL.revokeObjectURL;
    URL.createObjectURL = (blob: Blob) => { created.type = blob.type; return "blob:x"; };
    URL.revokeObjectURL = () => {};
    render(<MarkdownArtifact title="t" content={long} downloadName="数据研究-11.md" />);
    await userEvent.click(screen.getByRole("button", { name: /download/i }));
    expect(created.type).toContain("markdown");
    URL.createObjectURL = origCreate;
    URL.revokeObjectURL = origRevoke;
  });
});
