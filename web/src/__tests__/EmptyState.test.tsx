/** The shared empty-state component (gate item ②). */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Cpu } from "lucide-react";

import EmptyState, { EmptyStateAction } from "../components/EmptyState";

describe("EmptyState", () => {
  it("renders the title, the body and the action together", () => {
    const onClick = vi.fn();
    render(
      <EmptyState
        icon={Cpu}
        title="No spawns yet"
        body="Spawns are the specialists Arslan hands work to."
        action={<EmptyStateAction onClick={onClick}>Create a spawn</EmptyStateAction>}
      />,
    );
    expect(screen.getByText("No spawns yet")).toBeTruthy();
    expect(screen.getByText(/specialists Arslan hands work to/)).toBeTruthy();
    fireEvent.click(screen.getByTestId("empty-state-action"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  // Both sizes, because they are separate render paths. The first version of
  // this test only exercised "panel", and a mutation that dropped the `body &&`
  // guard from the INLINE branch stayed green — inline is the one used by the
  // sidebar, the evolution inbox and the filtered catalogs, i.e. most of them.
  it.each(["panel", "inline"] as const)(
    "omits the body and the action when not given (%s)",
    (size) => {
      render(<EmptyState title="Only a title" testId="bare" size={size} />);
      const el = screen.getByTestId("bare");
      // Only the title element; no empty <p> left behind for a missing body.
      expect(el.querySelectorAll("p").length).toBe(size === "inline" ? 1 : 0);
      expect(el.textContent).toBe("Only a title");
      expect(screen.queryByTestId("empty-state-action")).toBeNull();
    },
  );

  it("inline is a different shape from panel, not just different text", () => {
    // The two sizes exist because a full h-64 dashed box inside a sidebar list
    // is worse than the one-liner it replaced. If they rendered identically the
    // size prop would be decoration.
    const { unmount } = render(<EmptyState title="x" testId="p" size="panel" />);
    const panel = screen.getByTestId("p").className;
    unmount();
    render(<EmptyState title="x" testId="i" size="inline" />);
    const inline = screen.getByTestId("i").className;
    expect(panel).toContain("border-dashed");
    expect(inline).not.toContain("border-dashed");
  });

  it("the danger tone changes the styling, so an offline state is not read as an empty one", () => {
    const { unmount } = render(<EmptyState title="x" testId="n" />);
    const neutral = screen.getByTestId("n").className;
    unmount();
    render(<EmptyState title="x" testId="d" tone="danger" />);
    expect(screen.getByTestId("d").className).not.toBe(neutral);
    expect(screen.getByTestId("d").className).toContain("danger");
  });
});
