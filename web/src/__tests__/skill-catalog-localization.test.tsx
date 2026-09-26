import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import { skillCatalogMessages, skillCategoryMessages } from "../locales/skillCatalog";
import { useCapabilityLabel, useRegistryStore } from "../stores/registryStore";
import { api } from "../api/client";
import CapabilityCatalog from "../components/CapabilityCatalog";
import RegistryPicker from "../components/RegistryPicker";

vi.mock("../api/client", () => ({ api: { getRegistry: vi.fn(), listSpawns: vi.fn(async () => []) } }));
beforeEach(() => {
  vi.mocked(api.getRegistry).mockResolvedValue({ toolsets: [], skills: [
    ...Object.keys(skillCatalogMessages.en).map(key => ({ key, name: key, description: `Source ${key}`,
      name_key: `catalogUI.skills.${key}.name`, description_key: `catalogUI.skills.${key}.description`,
      category: "creative", tier: "safe", status: "registered", assignable: true })),
    { key: "custom", name: "My unchanged title", description: "My unchanged explanation", category: "My category", tier: "safe", status: "registered", assignable: true },
  ] });
  useRegistryStore.setState({ names: {}, nameKeys: {}, loaded: false, loading: false });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); void i18n.changeLanguage("en"); });

it.each(SUPPORTED_LANGUAGES)("renders and searches every builtin in %s without changing IDs", async language => {
  await i18n.changeLanguage(language);
  render(<CapabilityCatalog kind="skills" />);
  const copy = skillCatalogMessages[language];
  expect(await screen.findByText(copy["skill-creator"].name)).toBeInTheDocument();
  for (const value of Object.values(copy)) {
    expect(screen.getByText(value.name)).toBeInTheDocument();
    expect(screen.getByText(value.description)).toBeInTheDocument();
  }
  expect(screen.getByText("My unchanged title")).toBeInTheDocument();
  expect(screen.getByText("My unchanged explanation")).toBeInTheDocument();
  expect(screen.getByText("My category (1)")).toBeInTheDocument();
  expect(screen.getByText(`${skillCategoryMessages[language].creative} (55)`)).toBeInTheDocument();
  const search = screen.getByRole("textbox");
  fireEvent.change(search, { target: { value: copy["domain-modeling"].description } });
  expect(screen.getByText(copy["domain-modeling"].name)).toBeInTheDocument();
  expect(screen.queryByText(copy["skill-creator"].name)).not.toBeInTheDocument();
  fireEvent.change(search, { target: { value: "domain-modeling" } });
  expect(screen.getByText(copy["domain-modeling"].name)).toBeInTheDocument();
});

it.each(SUPPORTED_LANGUAGES)("picker uses %s text but passes the stable skill key", async language => {
  await i18n.changeLanguage(language);
  const picked = vi.fn();
  render(<RegistryPicker kind="skill" selected={["skill-creator"]} onPick={picked} onClose={vi.fn()} />);
  expect(await screen.findByText(skillCatalogMessages[language]["domain-modeling"].name)).toBeInTheDocument();
  expect(screen.getByTestId("pick-skill-skill-creator")).toBeDisabled();
  fireEvent.click(screen.getByTestId("pick-skill-domain-modeling"));
  expect(picked).toHaveBeenCalledWith("skill", "domain-modeling");
});

function EquippedLabel() {
  const label = useCapabilityLabel();
  return <span>{label("domain-modeling")}</span>;
}

it("equipped labels update in place after a language change", async () => {
  await i18n.changeLanguage("en");
  await useRegistryStore.getState().loadRegistry();
  render(<EquippedLabel />);
  expect(screen.getByText(skillCatalogMessages.en["domain-modeling"].name)).toBeInTheDocument();
  await act(async () => { await i18n.changeLanguage("zh"); });
  expect(screen.getByText(skillCatalogMessages.zh["domain-modeling"].name)).toBeInTheDocument();
  expect(api.getRegistry).toHaveBeenCalledTimes(1);
});
