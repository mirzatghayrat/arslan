import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import KnowledgeSunburst from "./KnowledgeSunburst";
import type { TreeNode } from "../../hooks/useKnowledgeTree";

const tree: TreeNode = {
  id: "root", name: "YOU", kind: "root", cat: "collection", value: 12,
  children: [
    { id: "cat:collection", name: "共享库", kind: "category", cat: "collection", value: 12, children: [
      { id: "coll:1", name: "A", kind: "collection", cat: "collection", value: 12, children: [
        { id: "src:coll:1:x", name: "x", kind: "source", cat: "collection", value: 12 },
      ] },
    ] },
  ],
};

describe("KnowledgeSunburst", () => {
  it("renders one <path> per node and a static center total", () => {
    const { container, getByText } = render(<KnowledgeSunburst tree={tree} focusedId={null} onFocus={() => {}} />);
    const paths = container.querySelectorAll("path[data-node]");
    expect(paths.length).toBe(3);
    expect(getByText("12")).toBeInTheDocument();
  });

  it("calls onFocus with node id on hover and null on leave", () => {
    const onFocus = vi.fn();
    const { container } = render(<KnowledgeSunburst tree={tree} focusedId={null} onFocus={onFocus} />);
    const seg = container.querySelector('path[data-node="coll:1"]')!;
    seg.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
    expect(onFocus).toHaveBeenCalledWith("coll:1");
    seg.dispatchEvent(new MouseEvent("mouseleave", { bubbles: true }));
    expect(onFocus).toHaveBeenCalledWith(null);
  });

  it("marks focus-family segments with data-focus", () => {
    const { container } = render(<KnowledgeSunburst tree={tree} focusedId="coll:1" onFocus={() => {}} />);
    expect(container.querySelector('path[data-node="src:coll:1:x"]')!.getAttribute("data-focus")).toBe("1");
    expect(container.querySelector('path[data-node="cat:collection"]')!.getAttribute("data-focus")).toBe("1");
  });

  it("colors group segments by hueKey and source leaves by fileType hue", () => {
    const tree = { id:"root", name:"YOU", kind:"root", cat:"collection", value:6, children:[
      { id:"cat:collection", name:"共享库", kind:"category", cat:"collection", value:6, children:[
        { id:"coll:1", name:"A", kind:"collection", cat:"collection", hueKey:"A", value:6, children:[
          { id:"s1", name:"条款.pdf", kind:"source", cat:"collection", fileType:"pdf", hueKey:"ft:pdf", value:6 }]}]}]} as any;
    const { container } = render(<KnowledgeSunburst tree={tree} focusedId={null} onFocus={()=>{}} />);
    const src = container.querySelector('path[data-node="s1"]')!;
    expect((src as HTMLElement).style.fill).toContain("var(--hue-");
  });

  it("brightens outward toward white (not toward surface) and has no dark stroke", () => {
    const tree = { id:"root", name:"YOU", kind:"root", cat:"collection", value:6, children:[
      { id:"cat:collection", name:"共享库", kind:"category", cat:"collection", value:6, children:[
        { id:"coll:1", name:"A", kind:"collection", cat:"collection", hueKey:"A", value:6, children:[
          { id:"s1", name:"条款.pdf", kind:"source", cat:"collection", fileType:"pdf", hueKey:"ft:pdf", value:6 }]}]}]} as any;
    const { container } = render(<KnowledgeSunburst tree={tree} focusedId={null} onFocus={()=>{}} />);
    const src = container.querySelector('path[data-node="s1"]') as HTMLElement;
    expect(src.style.fill).toContain("white");
    expect(src.style.fill).not.toContain("--surface");
    expect(src.style.stroke || "").not.toContain("--foreground");
  });
});
