// S3-M4 Task 4 — Diagnostics scheduled-tasks card.
// list badges/paused reason · fire-now (+409 running) · pause/resume toggle ·
// create-form validation (client cron mirror, interval preset payload) ·
// history expand + RunReplay link · i18n keys exist.
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, o?: Record<string, unknown>) =>
      o && typeof o === "object" && "v" in o ? `${k}:${String(o.v)}` : k,
  }),
}));
vi.mock("../api/client", () => {
  class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }
  return {
    ApiError,
    api: {
      listScheduledTasks: vi.fn(),
      createScheduledTask: vi.fn(),
      updateScheduledTask: vi.fn(),
      deleteScheduledTask: vi.fn(),
      pauseScheduledTask: vi.fn(),
      resumeScheduledTask: vi.fn(),
      fireScheduledTaskNow: vi.fn(),
      getScheduledTaskRuns: vi.fn(),
      listSpawns: vi.fn(),
    },
  };
});

import ScheduledTasksCard, { cronLooksValid } from "../components/ScheduledTasksCard";
import { api, ApiError } from "../api/client";
import en from "../locales/en.json";
import zh from "../locales/zh.json";

const IN_30_MIN = new Date(Date.now() + 30 * 60000).toISOString();

const TASKS = [
  {
    id: 1, name: "Morning research", prompt: "research X", spawn_id: 7,
    spawn_name: "Researcher", conversation_id: null,
    schedule_kind: "interval", interval_s: 1800, cron: null, enabled: true,
    last_fired_at: "2026-07-12T06:00:00", next_due_at: IN_30_MIN,
    consecutive_failures: 0, paused_reason: null,
    created_at: "2026-07-10T00:00:00", last_outcome: "ok",
  },
  {
    id: 2, name: "Nightly digest", prompt: "digest", spawn_id: 8,
    spawn_name: "Writer", conversation_id: "conv-9",
    schedule_kind: "cron", interval_s: null, cron: "0 8 * * *", enabled: false,
    last_fired_at: null, next_due_at: null,
    consecutive_failures: 3, paused_reason: "连续失败 3 次，自动暂停",
    created_at: "2026-07-10T00:00:00", last_outcome: "error",
  },
  {
    id: 3, name: "Fresh task", prompt: "hello", spawn_id: 7,
    spawn_name: "Researcher", conversation_id: null,
    schedule_kind: "interval", interval_s: 3600, cron: null, enabled: true,
    last_fired_at: null, next_due_at: IN_30_MIN,
    consecutive_failures: 0, paused_reason: null,
    created_at: "2026-07-10T00:00:00", last_outcome: null,
  },
];

const SPAWNS = [
  { id: 7, name: "Researcher", domain: "research", capabilities: [], template_used: null, generation_level: 1, created_at: "", updated_at: "" },
  { id: 8, name: "Writer", domain: "writing", capabilities: [], template_used: null, generation_level: 1, created_at: "", updated_at: "" },
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listScheduledTasks).mockResolvedValue(TASKS as never);
  vi.mocked(api.listSpawns).mockResolvedValue(SPAWNS as never);
  vi.mocked(api.getScheduledTaskRuns).mockResolvedValue([] as never);
});

describe("ScheduledTasksCard — list", () => {
  it("renders rows: cadence, outcome badges, paused-reason tooltip, — for none", async () => {
    render(<ScheduledTasksCard />);
    expect(await screen.findByText("Morning research")).toBeTruthy();
    const rows = screen.getAllByTestId("sched-row");
    expect(rows).toHaveLength(3);

    // interval task → humanized "every 30m"; ok badge; relative next-due.
    expect(rows[0].textContent).toContain("scheduled.every:30m");
    expect(rows[0].textContent).toContain("scheduled.due_in");
    // cron task → raw string + local-time hint (I5).
    expect(rows[1].textContent).toContain("0 8 * * *");
    expect(rows[1].textContent).toContain("scheduled.localTime");

    const badges = screen.getAllByTestId("sched-badge");
    expect(badges[0].textContent).toBe("scheduled.outcome.ok");
    expect(badges[1].textContent).toBe("scheduled.outcome.paused");
    expect(badges[1].getAttribute("title")).toBe("连续失败 3 次，自动暂停");
    // last_outcome=null = no runs yet OR in flight — honest "—", never a status.
    expect(badges[2].textContent).toBe("—");
  });
});

describe("ScheduledTasksCard — fire-now", () => {
  it("calls the api and shows the running state after 202", async () => {
    vi.mocked(api.fireScheduledTaskNow).mockResolvedValue({ status: "accepted", task_id: 1 } as never);
    render(<ScheduledTasksCard />);
    await screen.findByText("Morning research");
    fireEvent.click(screen.getByTestId("sched-fire-1"));
    await waitFor(() => expect(api.fireScheduledTaskNow).toHaveBeenCalledWith(1));
    const btn = await screen.findByTestId("sched-fire-1");
    expect(btn.textContent).toContain("scheduled.running");
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the running state on 409 (already running)", async () => {
    vi.mocked(api.fireScheduledTaskNow).mockRejectedValue(new ApiError("already running", 409));
    render(<ScheduledTasksCard />);
    await screen.findByText("Fresh task");
    fireEvent.click(screen.getByTestId("sched-fire-3"));
    await waitFor(() => {
      const btn = screen.getByTestId("sched-fire-3") as HTMLButtonElement;
      expect(btn.textContent).toContain("scheduled.running");
      expect(btn.disabled).toBe(true);
    });
  });
});

describe("ScheduledTasksCard — pause/resume", () => {
  it("toggles pause → resume → pause via the api", async () => {
    vi.mocked(api.pauseScheduledTask).mockResolvedValue({ ...TASKS[0], enabled: false, next_due_at: null } as never);
    vi.mocked(api.resumeScheduledTask).mockResolvedValue({ ...TASKS[0], enabled: true } as never);
    render(<ScheduledTasksCard />);
    await screen.findByText("Morning research");

    fireEvent.click(screen.getByTestId("sched-pause-1"));
    await waitFor(() => expect(api.pauseScheduledTask).toHaveBeenCalledWith(1));
    fireEvent.click(await screen.findByTestId("sched-resume-1"));
    await waitFor(() => expect(api.resumeScheduledTask).toHaveBeenCalledWith(1));
    expect(await screen.findByTestId("sched-pause-1")).toBeTruthy();
  });
});

describe("ScheduledTasksCard — delete", () => {
  it("asks for confirmation, then deletes", async () => {
    vi.mocked(api.deleteScheduledTask).mockResolvedValue({ ok: true } as never);
    render(<ScheduledTasksCard />);
    await screen.findByText("Morning research");
    fireEvent.click(screen.getByTestId("sched-delete-1"));
    expect(api.deleteScheduledTask).not.toHaveBeenCalled();
    expect(screen.getByText("scheduled.delete_confirm")).toBeTruthy();
    fireEvent.click(screen.getByTestId("sched-delete-confirm-1"));
    await waitFor(() => expect(api.deleteScheduledTask).toHaveBeenCalledWith(1));
    await waitFor(() => expect(screen.queryByText("Morning research")).toBeNull());
  });
});

describe("ScheduledTasksCard — create form", () => {
  async function openFilledForm() {
    render(<ScheduledTasksCard />);
    await screen.findByText("Morning research");
    fireEvent.click(screen.getByTestId("sched-new"));
    // spawn select defaults to the first spawn once the list loads
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "spawn" }).textContent).toContain("Researcher"));
    fireEvent.change(screen.getByTestId("sched-form-name"), { target: { value: "My task" } });
    fireEvent.change(screen.getByTestId("sched-form-prompt"), { target: { value: "do things" } });
  }

  it("rejects an invalid cron client-side (server is authority, mirror is loose)", async () => {
    await openFilledForm();
    fireEvent.click(screen.getByTestId("sched-kind-cron"));
    fireEvent.change(screen.getByTestId("sched-form-cron"), { target: { value: "not a cron" } });
    fireEvent.click(screen.getByTestId("sched-form-submit"));
    expect(await screen.findByText("scheduled.form.cron_invalid")).toBeTruthy();
    expect(api.createScheduledTask).not.toHaveBeenCalled();
  });

  it("submits the interval preset payload (30m → 1800s)", async () => {
    vi.mocked(api.createScheduledTask).mockResolvedValue({ ...TASKS[0], id: 9, name: "My task" } as never);
    await openFilledForm();
    fireEvent.click(screen.getByRole("button", { name: "interval-preset" }));
    fireEvent.pointerDown(screen.getByRole("option", { name: "30m" }));
    fireEvent.click(screen.getByTestId("sched-form-submit"));
    await waitFor(() => expect(api.createScheduledTask).toHaveBeenCalledWith({
      name: "My task",
      prompt: "do things",
      spawn_id: 7,
      schedule_kind: "interval",
      interval_s: 1800,
      cron: null,
      conversation_id: null,
    }));
    // the created row is appended
    expect(await screen.findByText("My task")).toBeTruthy();
  });

  it("surfaces the server 422 detail on reject", async () => {
    vi.mocked(api.createScheduledTask).mockRejectedValue(
      new ApiError("interval_s 必须 >= 900 秒(15 分钟)", 422));
    await openFilledForm();
    fireEvent.click(screen.getByTestId("sched-form-submit"));
    expect(await screen.findByText("interval_s 必须 >= 900 秒(15 分钟)")).toBeTruthy();
  });
});

describe("ScheduledTasksCard — history expand", () => {
  it("expands to execution history with a RunReplay link", async () => {
    vi.mocked(api.getScheduledTaskRuns).mockResolvedValue([
      { id: 11, started_at: "2026-07-12T05:00:00", finished_at: "2026-07-12T05:01:00", outcome: "ok", run_id: 42, reason: null },
      { id: 10, started_at: "2026-07-11T05:00:00", finished_at: "2026-07-11T05:00:20", outcome: "error", run_id: null, reason: "boom" },
    ] as never);
    const onOpenRun = vi.fn();
    render(<ScheduledTasksCard onOpenRun={onOpenRun} />);
    await screen.findByText("Morning research");
    fireEvent.click(screen.getByTestId("sched-expand-1"));
    await waitFor(() => expect(api.getScheduledTaskRuns).toHaveBeenCalledWith(1));
    const history = await screen.findByTestId("sched-history");
    expect(history.textContent).toContain("scheduled.outcome.ok");
    expect(history.textContent).toContain("scheduled.outcome.error");
    expect(history.textContent).toContain("boom");
    fireEvent.click(screen.getByTestId("sched-replay-42"));
    expect(onOpenRun).toHaveBeenCalledWith(42);
  });
});

describe("cronLooksValid — loose client mirror of server parse_cron", () => {
  it("accepts server-grammar expressions", () => {
    for (const ok of ["* * * * *", "0 8 * * *", "*/15 * * * *", "0,30 9,18 * * 1,5", "5 4 1 1 0"]) {
      expect(cronLooksValid(ok), ok).toBe(true);
    }
  });
  it("rejects malformed expressions", () => {
    for (const bad of ["not a cron", "* * * *", "* * * * * *", "*/0 * * * *", "60 * * * *", "a,b * * * *", ""]) {
      expect(cronLooksValid(bad), bad).toBe(false);
    }
  });
});

describe("scheduled.* i18n keys", () => {
  it("exist in en and zh (parity test guards the other locales)", () => {
    for (const loc of [en, zh] as Array<Record<string, any>>) {
      expect(loc.scheduled.title).toBeTruthy();
      expect(loc.scheduled.running).toBeTruthy();
      expect(loc.scheduled.localTime).toBeTruthy();
      expect(loc.scheduled.outcome.paused).toBeTruthy();
      expect(loc.scheduled.form.cron_invalid).toBeTruthy();
      expect(loc.scheduled.history.replay).toBeTruthy();
    }
  });
});
