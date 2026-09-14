import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { companionMessages } from "../../locales/companion";
import { companionApi, type ConversationContext, type MemoryEntry, type Project } from "../../api/companion";
import { api } from "../../api/client";
import { persistThreads, ACTIVE_THREAD_KEY, THREADS_KEY, restoreThreads } from "../../lib/sessionPersistence";
import { useArslanStore, initialArslanState } from "../../stores/arslanStore";
import { initialMemoryView, MEMORY_VIEW_KEY } from "./MemorySection";
import MemoryEditor from "./MemoryEditor";
import MemoryList from "./MemoryList";
import ProjectsSection from "./ProjectsSection";
import ConversationControls from "./ConversationControls";

vi.mock("./Materials", () => ({ default: () => <div>materials</div> }));
vi.mock("../brain/BrainSection", () => ({ default: () => <div>graph</div> }));

const project: Project = { id: "p-1", name: "Local project", kind: "software", summary: "Build a local tool", workspace_ref: null,
  app_binding: null, collection_ids: [], status: "active", version: 2, updated_at: "2026-09-14T00:00:00Z" };
const context: ConversationContext = { conversation_id: "new", version: 0, project_id: null, no_memory: false,
  no_learning: false, temporary: false, cloud_memory_allowed: false, allow_sensitive: false };

beforeEach(() => { localStorage.clear(); vi.spyOn(companionApi, "projects").mockResolvedValue([project]); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("companion messages", () => {
  it("has nonempty matching keys and interpolation across all six languages", () => {
    const keys = Object.keys(companionMessages.en).sort();
    expect(Object.keys(companionMessages)).toHaveLength(6);
    for (const messages of Object.values(companionMessages)) {
      expect(Object.keys(messages).sort()).toEqual(keys);
      for (const key of keys) {
        const text = messages[key as keyof typeof messages];
        expect(text.trim()).not.toBe("");
        expect(text.match(/\{\{[^}]+\}\}/g) ?? []).toEqual(companionMessages.en[key as keyof typeof messages].match(/\{\{[^}]+\}\}/g) ?? []);
      }
    }
  });
});

describe("memory controls", () => {
  it("loads older memories and preserves the loaded page when the request fails", async () => {
    const entry = { content: "First page", kind: "preference", status: "active", scope: { kind: "global", id: null },
      sensitivity: "normal", use_policy: "local_only", sources: [], updated_at: "2026-09-14T00:00:00Z" };
    const memories = vi.spyOn(companionApi, "memories")
      .mockResolvedValueOnce(Array.from({ length: 100 }, (_, i) => ({ ...entry, id: String(i) }) as MemoryEntry))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce([{ ...entry, id: "older", content: "Older memory" } as MemoryEntry]);
    vi.spyOn(companionApi, "proposals").mockResolvedValue([]);
    render(<MemoryList />);
    fireEvent.click(await screen.findByText("companion.loadMore"));
    expect(await screen.findByRole("alert")).toHaveTextContent("brain.read_failed");
    expect(screen.getAllByText("First page")).toHaveLength(100);
    fireEvent.click(screen.getByText("companion.loadMore"));
    expect(await screen.findByText("Older memory")).toBeVisible();
    expect(memories.mock.calls).toEqual([[], [100], [100]]);
    expect(screen.queryByText("companion.loadMore")).not.toBeInTheDocument();
  });
  it("renders withheld legacy credential content without crashing or offering edit", async () => {
    vi.spyOn(companionApi, "memories").mockResolvedValue([{ id: "restricted", content: null, kind: "preference", status: "quarantined",
      scope: { kind: "global", id: null }, sensitivity: "secret", use_policy: "never", sources: [], updated_at: "2026-09-14T00:00:00Z" } as unknown as MemoryEntry]);
    vi.spyOn(companionApi, "proposals").mockResolvedValue([]);
    render(<MemoryList />);
    expect(await screen.findByText("companion.credentialError")).toBeVisible();
    expect(screen.getByText("companion.edit")).toBeDisabled();
  });
  it("keeps the graph default for existing users and remembers their explicit view", () => {
    expect(initialMemoryView(true)).toBe("graph");
    expect(initialMemoryView(false)).toBe("about");
    localStorage.setItem(MEMORY_VIEW_KEY, "materials");
    expect(initialMemoryView(true)).toBe("materials");
  });
  it("requires a separate acknowledgement for sensitive memory and defaults to local only", async () => {
    const create = vi.spyOn(companionApi, "createMemory").mockResolvedValue({} as MemoryEntry);
    const saved = vi.fn();
    render(<MemoryEditor projects={[]} onClose={() => {}} onSaved={saved} />);
    fireEvent.change(screen.getByLabelText("companion.content"), { target: { value: "Private preference" } });
    fireEvent.click(screen.getByLabelText("companion.sensitive"));
    expect(screen.getByText("companion.save")).toBeDisabled();
    fireEvent.click(screen.getByLabelText("companion.sensitiveAck"));
    fireEvent.click(screen.getByText("companion.save"));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(create.mock.calls[0][0]).toMatchObject({ content: "Private preference", sensitivity: "sensitive", sensitive_acknowledged: true, use_policy: "local_only" });
  });
  it("retains typed memory content after a failed save", async () => {
    vi.spyOn(companionApi, "createMemory").mockRejectedValue(new Error("offline"));
    render(<MemoryEditor projects={[]} onClose={() => {}} onSaved={() => {}} />);
    fireEvent.change(screen.getByLabelText("companion.content"), { target: { value: "Keep this draft" } });
    fireEvent.click(screen.getByText("companion.save"));
    expect(await screen.findByRole("alert")).toHaveTextContent("companion.failure");
    expect(screen.getByLabelText("companion.content")).toHaveValue("Keep this draft");
  });
});

describe("project controls", () => {
  it("stores an explicit App version and shows the account-access gate", async () => {
    vi.spyOn(api, "listCollections").mockResolvedValue([]);
    const save = vi.spyOn(companionApi, "editProject").mockResolvedValue(project);
    render(<ProjectsSection onStart={async () => {}} />);
    fireEvent.click(await screen.findByText("companion.edit"));
    fireEvent.change(screen.getByLabelText("companion.appId"), { target: { value: "123" } });
    fireEvent.change(screen.getByLabelText("companion.bundleId"), { target: { value: "com.example.app" } });
    fireEvent.change(screen.getByLabelText("companion.appVersionId"), { target: { value: "version-1" } });
    fireEvent.change(screen.getByLabelText("companion.appPlatform"), { target: { value: "IOS" } });
    expect(screen.getByText("companion.ascDisabled")).toBeVisible();
    fireEvent.click(screen.getByText("companion.save"));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1].app_binding).toMatchObject({ app_id: "123", bundle_id: "com.example.app", version_id: "version-1", platform: "IOS" });
  });
  it("starts the chosen active project and includes archived projects in its query", async () => {
    const start = vi.fn().mockResolvedValue(undefined);
    render(<ProjectsSection onStart={start} />);
    fireEvent.click(await screen.findByText("companion.startTask"));
    await waitFor(() => expect(start).toHaveBeenCalledWith(project));
    expect(companionApi.projects).toHaveBeenCalledWith(true);
  });
  it("creates a project with user-chosen collection identifiers", async () => {
    vi.spyOn(api, "listCollections").mockResolvedValue([{ id: 7, name: "Documents", chunks: 1, sources: 1, spawn_ids: [] }]);
    const create = vi.spyOn(companionApi, "createProject").mockResolvedValue(project);
    render(<ProjectsSection onStart={async () => {}} />);
    fireEvent.click(screen.getByText("companion.addProject"));
    fireEvent.change(screen.getByLabelText("companion.name"), { target: { value: "New project" } });
    fireEvent.click(await screen.findByLabelText("Documents"));
    fireEvent.click(screen.getByText("companion.save"));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][0]).toMatchObject({ name: "New project", collection_ids: [7], app_binding: null });
  });
});

describe("temporary conversation", () => {
  it("never persists temporary title, history, id or active selection", () => {
    persistThreads([{ id: "regular", title: "Regular" }, { id: "private-id", title: "private title", temporary: true, history: ["private body"] }], "private-id");
    expect(localStorage.getItem(THREADS_KEY)).not.toContain("private");
    expect(localStorage.getItem(ACTIVE_THREAD_KEY)).toBe("regular");
    expect(restoreThreads().threads).toHaveLength(1);
  });
  it("keeps its cancellation id while live but never shows a replay link afterwards", () => {
    useArslanStore.setState(initialArslanState(), true);
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "arslan", run_id: -1 });
    expect(useArslanStore.getState().activeRunId).toBe(-1);
    useArslanStore.getState().handleFrame({ type: "stream_chunk", content: "Ephemeral answer" });
    useArslanStore.getState().handleFrame({ type: "stream_end", message_id: null, run_id: -1, temporary: true });
    expect(useArslanStore.getState().items.at(-1)?.runId).toBeNull();
    expect(useArslanStore.getState().activeRunId).toBeNull();
  });
  it("saves all temporary privacy flags together and reports confirmed state only", async () => {
    vi.spyOn(companionApi, "context").mockResolvedValue(context);
    const next = { ...context, temporary: true, no_memory: true, no_learning: true, version: 1 };
    const save = vi.spyOn(companionApi, "saveContext").mockResolvedValue(next);
    const changed = vi.fn();
    render(<ConversationControls conversationId="new" empty running={false} onChanged={changed} />);
    await waitFor(() => expect(screen.getByText("companion.conversationSettings")).not.toBeDisabled());
    fireEvent.click(screen.getByText("companion.conversationSettings"));
    fireEvent.click(screen.getByLabelText("companion.temporary"));
    fireEvent.click(screen.getByText("companion.save"));
    await waitFor(() => expect(changed).toHaveBeenLastCalledWith(next));
    expect(save.mock.calls[0][1]).toMatchObject({ temporary: true, no_memory: true, no_learning: true, cloud_memory_allowed: false, allow_sensitive: false });
  });
  it("does not offer temporary mode for an existing transcript", async () => {
    vi.spyOn(companionApi, "context").mockResolvedValue(context);
    render(<ConversationControls conversationId="new" empty={false} running={false} onChanged={() => {}} />);
    await waitFor(() => expect(screen.getByText("companion.conversationSettings")).not.toBeDisabled());
    fireEvent.click(screen.getByText("companion.conversationSettings"));
    expect(screen.getByLabelText("companion.temporary")).toBeDisabled();
  });
});
