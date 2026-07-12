/**
 * SearchToolsSection — the "Search & Tools" settings section.
 *
 * Verifies the section is self-contained and renders the three controls that
 * belong here per spec B1 (Search & Tools = search provider + search key;
 * GitHub token): search-provider Select, masked search API key (+ eye toggle),
 * and the GitHub token (+ eye toggle). Also asserts the onChange callbacks fire
 * and the eye toggles flip the input type. Behavior mirrors the pre-extraction
 * inline controls — no persistence change here (Task 6 owns blur-save).
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import SearchToolsSection from "../components/settings/SearchToolsSection";

type Props = React.ComponentProps<typeof SearchToolsSection>;

function setup(overrides: Partial<Props> = {}) {
  const props: Props = {
    searchProvider: "tavily",
    searchProviders: ["tavily", "serpapi"],
    onSearchProviderChange: vi.fn(),
    searchKey: "tvly-secret",
    onSearchKeyChange: vi.fn(),
    githubToken: "ghp_secret",
    onGithubTokenChange: vi.fn(),
    ...overrides,
  };
  render(<SearchToolsSection {...props} />);
  return props;
}

describe("SearchToolsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the search provider Select, search key input, and GitHub token input", () => {
    setup();
    expect(document.getElementById("settings-search-provider")).not.toBeNull();
    expect(document.getElementById("settings-search-key")).not.toBeNull();
    expect(document.getElementById("settings-github-token")).not.toBeNull();
  });

  it("hosts the GitHub token in THIS section (Search & Tools grouping)", () => {
    const { container } = render(
      <SearchToolsSection
        searchProvider="tavily"
        searchProviders={["tavily"]}
        onSearchProviderChange={vi.fn()}
        searchKey=""
        onSearchKeyChange={vi.fn()}
        githubToken=""
        onGithubTokenChange={vi.fn()}
      />,
    );
    // The GitHub token control must live inside this section's subtree.
    expect(container.querySelector("#settings-github-token")).not.toBeNull();
  });

  it("fires onSearchProviderChange when a provider option is picked", async () => {
    const user = userEvent.setup();
    const props = setup();
    await user.click(document.getElementById("settings-search-provider") as HTMLButtonElement);
    const serp = screen
      .getAllByRole("option")
      .find((o) => /serpapi/i.test(o.textContent ?? ""));
    expect(serp).toBeTruthy();
    await user.click(serp as HTMLElement);
    expect(props.onSearchProviderChange).toHaveBeenCalledWith("serpapi");
  });

  it("fires onSearchKeyChange with the new value", () => {
    const props = setup();
    const input = document.getElementById("settings-search-key") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "tvly-new" } });
    expect(props.onSearchKeyChange).toHaveBeenCalledWith("tvly-new");
  });

  it("fires onGithubTokenChange with the new value", () => {
    const props = setup();
    const input = document.getElementById("settings-github-token") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "ghp_new" } });
    expect(props.onGithubTokenChange).toHaveBeenCalledWith("ghp_new");
  });

  it("search key is masked by default and the eye toggle reveals it", async () => {
    const user = userEvent.setup();
    setup();
    const input = document.getElementById("settings-search-key") as HTMLInputElement;
    expect(input.type).toBe("password");
    await user.click(document.getElementById("toggle-show-search-key") as HTMLButtonElement);
    expect(input.type).toBe("text");
    await user.click(document.getElementById("toggle-show-search-key") as HTMLButtonElement);
    expect(input.type).toBe("password");
  });

  it("github token is masked by default and its eye toggle reveals it", async () => {
    const user = userEvent.setup();
    setup();
    const input = document.getElementById("settings-github-token") as HTMLInputElement;
    expect(input.type).toBe("password");
    await user.click(document.getElementById("toggle-show-github-token") as HTMLButtonElement);
    expect(input.type).toBe("text");
  });
});
