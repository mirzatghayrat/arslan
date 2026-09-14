import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { professionalMethodsApi } from "../../api/professionalMethods";
import { methodMessages } from "../../locales/methods";
import ProfessionalMethods from "./ProfessionalMethods";
import TaskWorkers from "./TaskWorkers";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const method = { key: "research", revision: 1, name: "Research", instructions: "Check primary sources." };

it("edits a new method version only after save, preserving drafts after an error", async () => {
  vi.spyOn(professionalMethodsApi, "list").mockResolvedValue([method]);
  const revise = vi.spyOn(professionalMethodsApi, "revise").mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ ...method, revision: 2, name: "My research" });
  render(<ProfessionalMethods />);
  fireEvent.click(await screen.findByRole("button", { name: "methods.viewEdit" }));
  fireEvent.change(screen.getByLabelText("methods.name"), { target: { value: "My research" } });
  expect(revise).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "methods.saveVersion" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("companion.failure");
  expect(screen.getByLabelText("methods.name")).toHaveValue("My research");
  fireEvent.click(screen.getByRole("button", { name: "methods.saveVersion" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.getByText("My research")).toBeInTheDocument();
  expect(revise).toHaveBeenLastCalledWith(method, "My research", "Check primary sources.");
});

it("shows worker results as unverified and does not execute embedded markup", () => {
  const open = vi.fn();
  const { container } = render(<TaskWorkers workers={[{
    id: "worker", method: "research", method_revision: 1, objective: "Check fixture", status: "completed", run_id: 9,
    result: { status: "completed", result: "<script>unsafe()</script>", artifacts: [], evidence: [], remaining_work: [] },
  }]} onOpenRun={open} />);
  expect(container.querySelector("details")).not.toHaveAttribute("open");
  fireEvent.click(screen.getByText("methods.collaboration"));
  expect(screen.getByText("methods.completed")).toBeInTheDocument();
  expect(container.querySelector("script")).toBeNull();
  expect(screen.getByText("<script>unsafe()</script>")).toBeInTheDocument();
  fireEvent.click(screen.getByText("methods.openResult"));
  expect(open).toHaveBeenCalledWith(9);
});

it("provides matching professional-method copy in all six interface languages", () => {
  const keys = Object.keys(methodMessages.en).sort();
  expect(Object.keys(methodMessages).sort()).toEqual(["de", "en", "es", "fr", "ja", "zh"]);
  for (const messages of Object.values(methodMessages)) {
    expect(Object.keys(messages).sort()).toEqual(keys);
    expect(Object.values(messages).every(value => value.trim())).toBe(true);
  }
});
