/**
 * Dragging a panel divider must not select text on either side. Both dividers (the workbench's and the
 * work dock's) cancel the pointerdown's default (which is what starts a text selection), clear any
 * selection already there, and turn off user-select on the body for the drag. The body's own value comes
 * back on pointerup, on pointercancel, and when the panel closes or unmounts mid-drag.
 *
 * jsdom does not turn pointer moves into a text selection, so this cannot watch a selection grow. It
 * asserts the parts that stop one: the cancelled default, the cleared selection and the style.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { files, jobsApi } = vi.hoisted(() => ({
  files: { list: vi.fn(), read: vi.fn(), stat: vi.fn(), open: vi.fn(), reveal: vi.fn(), home: vi.fn(), conversationFiles: vi.fn() },
  jobsApi: { list: vi.fn(), stop: vi.fn() },
}));
vi.mock("../api/files", () => ({ filesApi: files }));
vi.mock("../api/tasks", () => ({ backgroundJobsApi: jobsApi }));
vi.mock("../components/BrowserReader", () => ({ default: () => <div data-testid="browser-reader" /> }));
vi.mock("../components/ArtifactPreview", () => ({ default: () => null }));

import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { useWorkbench } from "../stores/workbenchStore";
import Workbench from "../components/workbench/Workbench";
import WorkDock from "../components/WorkDock";

// jsdom has no pointer capture; a per-element set is enough for the handlers' has/release checks.
const captured = new WeakMap<Element, Set<number>>();
const proto = HTMLElement.prototype as unknown as Record<string, unknown>;

const dock = (open: boolean) => <><p>Conversation text</p>
  <WorkDock open={open} onOpen={vi.fn()} onClose={vi.fn()} conversationId="c1" taskId={null} temporary={false} /></>;
// Each mount returns the view and a way to close the panel while it stays mounted.
const mounts = {
  workbench: () => {
    useWorkbench.getState().show("files");
    const view = render(<><p>Conversation text</p><Workbench conversationId="c1" taskId={null} temporary={false} /></>);
    return { view, close: () => act(() => useWorkbench.getState().close()) };
  },
  "work dock": () => {
    const view = render(dock(true));
    return { view, close: () => view.rerender(dock(false)) };
  },
};

function selectConversationText() {
  const range = document.createRange();
  range.selectNodeContents(screen.getByText("Conversation text"));
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
  expect(selection.rangeCount).toBe(1);
}

beforeEach(() => {
  proto.setPointerCapture = function (this: Element, id: number) {
    const set = captured.get(this) ?? new Set<number>(); set.add(id); captured.set(this, set);
  };
  proto.hasPointerCapture = function (this: Element, id: number) { return captured.get(this)?.has(id) ?? false; };
  proto.releasePointerCapture = function (this: Element, id: number) { captured.get(this)?.delete(id); };
  document.body.style.userSelect = "text";
  useArslanStore.setState(initialArslanState(), true);
  useWorkbench.setState({ open: false, tab: "files", reader: null, folder: null });
  files.home.mockResolvedValue({ path: "~/Arslan", project: null });
  files.conversationFiles.mockResolvedValue({ files: [] });
  files.list.mockResolvedValue({ path: "~/Arslan", root: "~/Arslan", crumbs: [{ name: "Arslan", path: "~/Arslan" }], total: 0, more: false, entries: [] });
  jobsApi.list.mockResolvedValue({ jobs: [] });
  try { localStorage.clear(); } catch { /* storage off */ }
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  delete proto.setPointerCapture; delete proto.hasPointerCapture; delete proto.releasePointerCapture;
  window.getSelection()?.removeAllRanges();
  document.body.style.userSelect = "";
});

describe.each(Object.entries(mounts))("the %s divider", (_name, mount) => {
  it("a drag cancels the default, leaves no selection and restores user-select on pointerup", () => {
    mount();
    const divider = screen.getByRole("separator");
    selectConversationText();
    // fireEvent returns false when a handler called preventDefault.
    expect(fireEvent.pointerDown(divider, { pointerId: 1, clientX: 600 })).toBe(false);
    expect(window.getSelection()!.rangeCount).toBe(0);
    expect(document.body.style.userSelect).toBe("none");
    fireEvent.pointerMove(divider, { pointerId: 1, clientX: 560 });
    fireEvent.pointerMove(divider, { pointerId: 1, clientX: 520 });
    expect(document.body.style.userSelect).toBe("none");
    fireEvent.pointerUp(divider, { pointerId: 1, clientX: 520 });
    expect(window.getSelection()!.rangeCount).toBe(0);
    expect(document.body.style.userSelect).toBe("text");
  });

  it("restores user-select after a pointercancel", () => {
    mount();
    const divider = screen.getByRole("separator");
    fireEvent.pointerDown(divider, { pointerId: 2, clientX: 600 });
    fireEvent.pointerMove(divider, { pointerId: 2, clientX: 560 });
    expect(document.body.style.userSelect).toBe("none");
    fireEvent.pointerCancel(divider, { pointerId: 2 });
    expect(document.body.style.userSelect).toBe("text");
  });

  it("restores user-select when the panel unmounts mid-drag", () => {
    const { view } = mount();
    fireEvent.pointerDown(screen.getByRole("separator"), { pointerId: 3, clientX: 600 });
    expect(document.body.style.userSelect).toBe("none");
    view.unmount();
    expect(document.body.style.userSelect).toBe("text");
  });

  it("restores user-select when the panel closes mid-drag", () => {
    const { close } = mount();
    fireEvent.pointerDown(screen.getByRole("separator"), { pointerId: 4, clientX: 600 });
    expect(document.body.style.userSelect).toBe("none");
    close();
    expect(screen.queryByRole("separator")).toBeNull();
    expect(document.body.style.userSelect).toBe("text");
  });
});
