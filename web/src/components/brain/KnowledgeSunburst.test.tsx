import { render, fireEvent } from "@testing-library/react";
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
  it("renders one <path> per node and the center circle", () => {
    const { container } = render(<KnowledgeSunburst tree={tree} focusedId={null} onFocus={() => {}} />);
    const paths = container.querySelectorAll("path[data-node]");
    expect(paths.length).toBe(3);
    expect(container.querySelector('[data-center="1"]')).not.toBeNull();
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

  it("marks focus-family segments with data-dim=0 (not dimmed)", () => {
    const { container } = render(<KnowledgeSunburst tree={tree} focusedId="coll:1" onFocus={() => {}} />);
    expect(container.querySelector('path[data-node="src:coll:1:x"]')!.getAttribute("data-dim")).toBe("0");
    expect(container.querySelector('path[data-node="cat:collection"]')!.getAttribute("data-dim")).toBe("0");
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

  it("dims non-focused segments and keeps the focused family full opacity", () => {
    const tree = { id:"root", name:"YOU", kind:"root", cat:"collection", value:2, children:[
      { id:"cat:pref", name:"偏好", kind:"category", cat:"pref", value:2, children:[
        { id:"g1", name:"任务需求", kind:"category", cat:"pref", hueKey:"任务需求", value:1, children:[
          { id:"pref:1", name:"A", kind:"pref", cat:"pref", value:1 }]},
        { id:"g2", name:"沟通偏好", kind:"category", cat:"pref", hueKey:"沟通偏好", value:1, children:[
          { id:"pref:2", name:"B", kind:"pref", cat:"pref", value:1 }]}]}]} as any;
    const { container, rerender } = render(<KnowledgeSunburst tree={tree} focusedId={null} onFocus={()=>{}} />);
    const op = (sel: string) => Number((container.querySelector(sel) as HTMLElement).style.opacity || "1");
    expect(op('path[data-node="pref:1"]')).toBe(1);
    rerender(<KnowledgeSunburst tree={tree} focusedId={"g1"} onFocus={()=>{}} />);
    expect(op('path[data-node="pref:1"]')).toBe(1);      // in focused family (child of g1)
    expect(op('path[data-node="pref:2"]')).toBeLessThan(1); // outside → dimmed
  });

  it("drills into a clicked node and back out via center", () => {
    const tree = { id:"root", name:"YOU", kind:"root", cat:"collection", value:2, children:[
      { id:"cat:pref", name:"偏好", kind:"category", cat:"pref", value:2, children:[
        { id:"g1", name:"任务需求", kind:"category", cat:"pref", hueKey:"任务需求", value:1, children:[
          { id:"pref:1", name:"A", kind:"pref", cat:"pref", value:1 }]},
        { id:"g2", name:"沟通偏好", kind:"category", cat:"pref", hueKey:"沟通偏好", value:1, children:[
          { id:"pref:2", name:"B", kind:"pref", cat:"pref", value:1 }]}]}]} as any;
    const { container } = render(<KnowledgeSunburst tree={tree} focusedId={null} onFocus={()=>{}} />);
    fireEvent.click(container.querySelector('path[data-node="g1"]') as HTMLElement);
    expect(container.querySelector('path[data-node="pref:2"]')).toBeNull();     // out of view
    expect(container.querySelector('path[data-node="pref:1"]')).not.toBeNull(); // in view
    fireEvent.click(container.querySelector('[data-breadcrumb="root"]') as HTMLElement);
    expect(container.querySelector('path[data-node="pref:2"]')).not.toBeNull(); // back
  });

  it("has no center stats text and the center core drills up", () => {
    const tree = { id:"root", name:"YOU", kind:"root", cat:"collection", value:2, children:[
      { id:"cat:pref", name:"偏好", kind:"category", cat:"pref", value:2, children:[
        { id:"g1", name:"任务需求", kind:"category", cat:"pref", hueKey:"任务需求", value:1, children:[
          { id:"pref:1", name:"A", kind:"pref", cat:"pref", value:1 }]},
        { id:"g2", name:"沟通偏好", kind:"category", cat:"pref", hueKey:"沟通偏好", value:1, children:[
          { id:"pref:2", name:"B", kind:"pref", cat:"pref", value:1 }]}]}]} as any;
    const { container, queryByText } = render(<KnowledgeSunburst tree={tree} focusedId={null} onFocus={()=>{}} />);
    expect(queryByText("整个第二大脑")).toBeNull();
    fireEvent.click(container.querySelector('path[data-node="g1"]') as HTMLElement);
    expect(container.querySelector('path[data-node="pref:2"]')).toBeNull();
    fireEvent.click(container.querySelector('[data-center="1"]') as HTMLElement);
    expect(container.querySelector('path[data-node="pref:2"]')).not.toBeNull();
  });
});
