/**
 * 0.1.58 §6: any model of any provider — in the composer (this conversation, or the default for
 * new ones) and in 模型分工 (per role, one model of a config). The picker searches every
 * catalog, keeps ★ favourites, shows context / price / abilities, and disables a model the role
 * cannot use with the reason.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { client, conv } = vi.hoisted(() => ({
  client: { fetchProviderModels: vi.fn(), updateProviderConfig: vi.fn() },
  conv: { get: vi.fn(), set: vi.fn(), clear: vi.fn() },
}));
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), ...client }));
vi.mock("../api/conversationModel", () => ({ conversationModelApi: conv }));

import type { ModelInfo, ProviderConfig } from "../api/client.types";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import ModelPicker, { fmtContext, fmtPrice, loadFavourites, unusableWhy } from "../components/models/ModelPicker";
import ConversationModelChip, { _resetChipCatalogs } from "../components/models/ConversationModelChip";
import RolePicker from "../components/models/RolePicker";
import ModelRolesSection from "../components/settings/ModelRolesSection";

const cfg = (id: number, provider: string, model: string, extra: Partial<ProviderConfig> = {}) =>
  ({ id, label: provider, provider, model, is_primary: id === 1, ...extra }) as ProviderConfig;
const configs = [cfg(1, "deepseek", "deepseek-chat"), cfg(2, "openrouter", "openai/gpt-4o-mini")];
const m = (id: string, extra: Partial<ModelInfo> = {}) =>
  ({ id, display_name: null, context_window: 128000, capabilities: ["tools"], source: "api", ...extra }) as ModelInfo;
const CATALOGS: Record<number, ModelInfo[]> = {
  1: [m("deepseek-chat", { context_window: 64000 })],
  2: [m("openai/gpt-4o-mini"), m("anthropic/claude-sonnet-4.5", { display_name: "Claude Sonnet 4.5", context_window: 1_000_000,
    capabilities: ["tools", "vision"], price_in: 3, price_out: 15 }),
    m("meta/llama-free", { price_in: 0, price_out: 0 }), m("old/no-tools", { capabilities: [] })],
};
const label = (c: ProviderConfig) => c.provider;

beforeEach(() => {
  localStorage.clear();
  _resetChipCatalogs();
  useArslanStore.setState(initialArslanState(), true);
  client.fetchProviderModels.mockImplementation(async (id: number) => ({ models: CATALOGS[id] ?? [] }));
  client.updateProviderConfig.mockResolvedValue({});
  conv.get.mockResolvedValue({ choice: null });
  conv.set.mockImplementation(async (_c: string, id: number, model: string) => ({ choice: { config_id: id, model } }));
  conv.clear.mockResolvedValue({ choice: null });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("what a row says", () => {
  it("context, price per million, and why a role cannot use it", () => {
    expect(fmtContext(1_000_000)).toBe("1M");
    expect(fmtContext(128000)).toBe("128K");
    expect(fmtContext(null)).toBe("");
    expect(fmtPrice({ price_in: 3, price_out: 15 })).toBe("$3 / $15");
    expect(fmtPrice({ price_in: 0.05, price_out: 0 })).toBe("$0.05 / $0");
    expect(fmtPrice({ price_in: null, price_out: 1 } as never)).toBe("");
    const t = (k: string) => k;
    expect(unusableWhy(m("x", { capabilities: [] }), "tools", t)).toBe("models.noTools");
    expect(unusableWhy(m("x"), "vision", t)).toBe("models.noVision");
    expect(unusableWhy(m("x", { capabilities: ["tools", "vision"] }), "vision", t)).toBeNull();
    // A provider that does not say what its models do never blocks one.
    expect(unusableWhy(m("x", { capabilities: [], source: "fallback" } as never), "tools", t)).toBeNull();
    expect(unusableWhy(m("x", { capabilities: [] }), null, t)).toBeNull();
  });
});

describe("the picker", () => {
  it("opens a provider's whole catalog; a model without tools is disabled with the reason", async () => {
    const onPick = vi.fn();
    render(<ModelPicker configs={configs} current={{ configId: 1, model: "deepseek-chat" }} need="tools" onPick={onPick} label={label} />);
    fireEvent.click(screen.getByTestId("model-all-2"));
    const row = await screen.findByTestId("model-row-2-anthropic/claude-sonnet-4.5");
    expect(row.textContent).toContain("Claude Sonnet 4.5");
    expect(row.textContent).toContain("1M · $3 / $15");
    expect(within(screen.getByTestId("model-row-2-meta/llama-free")).getByText("models.free")).toBeTruthy();
    const dead = screen.getByTestId("model-row-2-old/no-tools");
    expect(within(dead).getByTestId("model-why").textContent).toBe("models.noTools");
    fireEvent.click(within(dead).getAllByRole("button")[0]);
    expect(onPick).not.toHaveBeenCalled();
    fireEvent.click(within(row).getAllByRole("button")[0]);
    expect(onPick).toHaveBeenCalledWith({ configId: 2, model: "anthropic/claude-sonnet-4.5" });
  });

  it("a search looks through every provider's catalog", async () => {
    render(<ModelPicker configs={configs} current={null} need={null} onPick={() => {}} label={label} />);
    fireEvent.change(screen.getByTestId("model-search"), { target: { value: "sonnet" } });
    expect(await screen.findByTestId("model-row-2-anthropic/claude-sonnet-4.5")).toBeTruthy();
    expect(client.fetchProviderModels).toHaveBeenCalledWith(1);
    expect(client.fetchProviderModels).toHaveBeenCalledWith(2);
    expect(screen.queryByTestId("model-row-1-deepseek-chat")).toBeNull();
    expect(screen.queryByTestId("model-provider-1")).toBeNull();
    fireEvent.change(screen.getByTestId("model-search"), { target: { value: "nothing-like-this" } });
    expect(await screen.findByText("models.noMatch")).toBeTruthy();
  });

  it("★ puts a model on top and remembers it", async () => {
    const { unmount } = render(<ModelPicker configs={configs} current={null} need={null} onPick={() => {}} label={label} />);
    fireEvent.click(screen.getByTestId("model-all-2"));
    const row = await screen.findByTestId("model-row-2-anthropic/claude-sonnet-4.5");
    fireEvent.click(within(row).getByRole("button", { name: "models.star" }));
    expect(loadFavourites()).toEqual(["2::anthropic/claude-sonnet-4.5"]);
    unmount();
    render(<ModelPicker configs={configs} current={null} need={null} onPick={() => {}} label={label} />);
    const first = screen.getByTestId("model-picker").querySelector("[data-testid^='model-row-']");
    expect(first?.getAttribute("data-testid")).toBe("model-row-2-anthropic/claude-sonnet-4.5");
    // A favourite of a provider that was removed is not shown.
    cleanup();
    render(<ModelPicker configs={[configs[0]]} current={null} need={null} onPick={() => {}} label={label} />);
    expect(screen.queryByTestId("model-row-2-anthropic/claude-sonnet-4.5")).toBeNull();
  });

  it("a provider whose last test failed says so", () => {
    render(<ModelPicker configs={[cfg(1, "deepseek", "deepseek-chat", { last_health: "failed", last_health_detail: "Key rejected" })]}
      current={null} need={null} onPick={() => {}} label={label} />);
    expect(screen.getByTestId("model-provider-failed-1").textContent).toBe("Key rejected");
  });
});

describe("the model under the composer", () => {
  const onSetDefault = vi.fn();
  const chip = (id = "c1") => render(<ConversationModelChip conversationId={id} configs={configs} llmProviders={[]} onSetDefault={onSetDefault} />);

  it("shows the default; picking another model sets it for this conversation only", async () => {
    chip();
    expect(screen.getByTestId("model-chip").textContent).toContain("deepseek · deepseek-chat");
    fireEvent.click(screen.getByTestId("model-chip"));
    fireEvent.click(screen.getByTestId("model-all-2"));
    const row = await screen.findByTestId("model-row-2-anthropic/claude-sonnet-4.5");
    await act(async () => { fireEvent.click(within(row).getAllByRole("button")[0]); });
    expect(conv.set).toHaveBeenCalledWith("c1", 2, "anthropic/claude-sonnet-4.5");
    expect(screen.getByTestId("model-chip").textContent).toContain("openrouter · anthropic/claude-sonnet-4.5");
    expect(client.updateProviderConfig).not.toHaveBeenCalled();
    expect(onSetDefault).not.toHaveBeenCalled();
  });

  it("loads the conversation's own choice, and picking the default again clears it", async () => {
    conv.get.mockResolvedValue({ choice: { config_id: 2, model: "x/chosen" } });
    chip();
    await waitFor(() => expect(screen.getByTestId("model-chip").textContent).toContain("x/chosen"));
    fireEvent.click(screen.getByTestId("model-chip"));
    await act(async () => { fireEvent.click(screen.getByTestId("model-use-default")); });
    expect(conv.clear).toHaveBeenCalledWith("c1");
    expect(conv.set).not.toHaveBeenCalled();
    expect(screen.getByTestId("model-chip").textContent).toContain("deepseek-chat");
  });

  it("a choice whose provider was removed shows the default", async () => {
    conv.get.mockResolvedValue({ choice: { config_id: 99, model: "gone" } });
    chip();
    await act(async () => {});
    expect(screen.getByTestId("model-chip").textContent).toContain("deepseek-chat");
  });

  it("设为默认 sets that config's model and makes it primary, then the conversation follows the default", async () => {
    conv.get.mockResolvedValue({ choice: { config_id: 2, model: "anthropic/claude-sonnet-4.5" } });
    chip();
    await waitFor(() => expect(screen.getByTestId("model-chip").textContent).toContain("claude-sonnet"));
    fireEvent.click(screen.getByTestId("model-chip"));
    await act(async () => { fireEvent.click(screen.getByTestId("model-set-default")); });
    expect(client.updateProviderConfig).toHaveBeenCalledWith(2, { model: "anthropic/claude-sonnet-4.5" });
    expect(onSetDefault).toHaveBeenCalledWith(2);
    expect(conv.clear).toHaveBeenCalledWith("c1");
  });

  it("设为默认 on a config's own model does not rewrite the config", async () => {
    conv.get.mockResolvedValue({ choice: { config_id: 2, model: "openai/gpt-4o-mini" } });
    chip();
    await waitFor(() => expect(screen.getByTestId("model-chip").textContent).toContain("gpt-4o-mini"));
    fireEvent.click(screen.getByTestId("model-chip"));
    await act(async () => { fireEvent.click(screen.getByTestId("model-set-default")); });
    expect(client.updateProviderConfig).not.toHaveBeenCalled();
    expect(onSetDefault).toHaveBeenCalledWith(2);
  });

  it("the ring is the last call's input against the model's context window", async () => {
    useArslanStore.setState({ items: [{ kind: "message", id: "a", role: "arslan", text: "hi", usage: { last_input: 48000 } }] } as never);
    chip();
    expect((await screen.findByTestId("context-ring")).textContent).toBe("75%");   // 48K of deepseek-chat's 64K
  });

  it("no ring before any call; a failed provider shows a red dot and its reason", async () => {
    render(<ConversationModelChip conversationId="c1" llmProviders={[]} onSetDefault={onSetDefault}
      configs={[cfg(1, "deepseek", "deepseek-chat", { last_health: "failed", last_health_detail: "Key rejected" })]} />);
    await act(async () => {});
    expect(screen.queryByTestId("context-ring")).toBeNull();
    expect(screen.getByTestId("model-chip-dot").getAttribute("data-status")).toBe("failed");
    expect(screen.getByTestId("model-chip").getAttribute("title")).toBe("Key rejected");
  });

  it("switching conversations loads that conversation's choice", async () => {
    conv.get.mockImplementation(async (id: string) => ({ choice: id === "c2" ? { config_id: 2, model: "x/two" } : null }));
    const { rerender } = chip("c1");
    await act(async () => {});
    expect(screen.getByTestId("model-chip").textContent).toContain("deepseek-chat");
    rerender(<ConversationModelChip conversationId="c2" configs={configs} llmProviders={[]} onSetDefault={onSetDefault} />);
    await waitFor(() => expect(screen.getByTestId("model-chip").textContent).toContain("x/two"));
  });
});

describe("模型分工", () => {
  it("the main row picks any model of any provider", async () => {
    const onMainChange = vi.fn();
    render(<ModelRolesSection values={{}} onChange={() => {}} providerConfigs={configs} strategy="single" onMainChange={onMainChange} />);
    expect(screen.getByTestId("settings-slot-main").textContent).toContain("deepseek · deepseek-chat");
    fireEvent.click(screen.getByTestId("settings-slot-main"));
    fireEvent.click(screen.getByTestId("model-all-2"));
    const row = await screen.findByTestId("model-row-2-anthropic/claude-sonnet-4.5");
    fireEvent.click(within(row).getAllByRole("button")[0]);
    expect(onMainChange).toHaveBeenCalledWith(2, "anthropic/claude-sonnet-4.5");
  });

  it("a slot saves its config and, when it is not the config's own, the model", async () => {
    const onChange = vi.fn();
    render(<ModelRolesSection values={{}} onChange={onChange} providerConfigs={configs} strategy="single" />);
    fireEvent.click(screen.getByTestId("settings-slot-title"));
    fireEvent.click(screen.getByTestId("model-all-2"));
    const row = await screen.findByTestId("model-row-2-meta/llama-free");
    fireEvent.click(within(row).getAllByRole("button")[0]);
    expect(onChange).toHaveBeenCalledWith("titleConfigId", "2");
    expect(onChange).toHaveBeenCalledWith("titleModel", "meta/llama-free");
    onChange.mockClear();
    fireEvent.click(screen.getByTestId("settings-slot-title"));
    fireEvent.click(within(screen.getByTestId("model-row-2-openai/gpt-4o-mini")).getAllByRole("button")[0]);
    expect(onChange).toHaveBeenCalledWith("titleModel", "");                       // the config's own model
  });

  it("a slot shows the model it names, and 不单独设 clears both", () => {
    const onChange = vi.fn();
    render(<ModelRolesSection values={{ visionConfigId: "2", visionModel: "x/sees" }} onChange={onChange}
      providerConfigs={configs} strategy="single" />);
    expect(screen.getByTestId("settings-slot-vision").textContent).toContain("openrouter · x/sees");
    fireEvent.click(screen.getByTestId("settings-slot-vision"));
    fireEvent.click(screen.getByTestId("settings-slot-vision-unset"));
    expect(onChange).toHaveBeenCalledWith("visionConfigId", "");
    expect(onChange).toHaveBeenCalledWith("visionModel", "");
  });

  it("看图 disables a model that cannot see images", async () => {
    render(<RolePicker id="r" configs={configs} current={null} need="vision" onPick={() => {}} />);
    fireEvent.click(screen.getByTestId("r"));
    fireEvent.click(screen.getByTestId("model-all-2"));
    const row = await screen.findByTestId("model-row-2-meta/llama-free");
    expect(within(row).getByTestId("model-why").textContent).toBe("models.noVision");
    expect(within(screen.getByTestId("model-row-2-anthropic/claude-sonnet-4.5")).queryByTestId("model-why")).toBeNull();
  });
});
