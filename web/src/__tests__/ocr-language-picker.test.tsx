/**
 * OcrLanguagePicker — a bounded picker over what the HOST can recognise.
 *
 * The two behaviours asserted hardest are the two that a later "simplification"
 * would most plausibly remove, because both look like restrictions for no
 * reason unless you know the measurement behind them:
 *
 *   - the ceiling. Recognition degrades as the request widens, and CJK goes
 *     first. An uncapped picker would let someone wreck the capability while
 *     believing they were improving it.
 *   - the honest empty state. A host without recognition is told so, rather
 *     than shown controls that would do nothing.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

const listOcrLanguages = vi.fn();
vi.mock("../api/client", () => ({ api: { listOcrLanguages: () => listOcrLanguages() } }));

import OcrLanguagePicker from "../components/settings/OcrLanguagePicker";

const HOST = {
  available: ["en-US", "zh-Hans", "ja-JP", "de-DE"],
  max_selectable: 3,
  platform_supported: true,
};

beforeEach(() => {
  listOcrLanguages.mockReset();
  listOcrLanguages.mockResolvedValue(HOST);
});

it("offers exactly what the host reports, not a list of its own", async () => {
  render(<OcrLanguagePicker value="" onChange={() => {}} />);
  await waitFor(() => expect(screen.getByText("en-US")).toBeTruthy());
  // Discriminating: a hardcoded list would still show en-US. It would NOT
  // match a host that reports something unexpected.
  listOcrLanguages.mockResolvedValue({ ...HOST, available: ["xx-XX"] });
  render(<OcrLanguagePicker value="" onChange={() => {}} />);
  await waitFor(() => expect(screen.getByText("xx-XX")).toBeTruthy());
});

it("says unset follows the interface language", async () => {
  render(<OcrLanguagePicker value="" onChange={() => {}} />);
  await waitFor(() =>
    expect(screen.getByText("settings.ocrLanguagesFollowsUi")).toBeTruthy());
});

it("stops accepting languages at the cap", async () => {
  const onChange = vi.fn();
  render(<OcrLanguagePicker value="en-US,zh-Hans,ja-JP" onChange={onChange} />);
  await waitFor(() => expect(screen.getByText("de-DE")).toBeTruthy());

  const fourth = screen.getByText("de-DE") as HTMLButtonElement;
  expect(fourth.disabled).toBe(true);
  fireEvent.click(fourth);
  expect(onChange).not.toHaveBeenCalled();
});

it("lets a selected language be turned off even at the cap", async () => {
  // Otherwise the cap becomes a trap: three chosen and no way to change them.
  const onChange = vi.fn();
  render(<OcrLanguagePicker value="en-US,zh-Hans,ja-JP" onChange={onChange} />);
  await waitFor(() => expect(screen.getByText("zh-Hans")).toBeTruthy());

  fireEvent.click(screen.getByText("zh-Hans"));
  expect(onChange).toHaveBeenCalledWith("en-US,ja-JP");
});

it("tells a host without recognition instead of offering empty choices", async () => {
  listOcrLanguages.mockResolvedValue(
    { available: [], max_selectable: 3, platform_supported: false });
  render(<OcrLanguagePicker value="" onChange={() => {}} />);
  await waitFor(() =>
    expect(screen.getByText("settings.ocrLanguagesUnavailable")).toBeTruthy());
});

it("survives an endpoint that is not there at all", async () => {
  // A missing method used to throw during render and take the whole Settings
  // screen with it — one unavailable endpoint costing every other setting.
  listOcrLanguages.mockImplementation(() => { throw new TypeError("not a function"); });
  render(<OcrLanguagePicker value="" onChange={() => {}} />);
  await waitFor(() =>
    expect(screen.getByText("settings.ocrLanguagesUnavailable")).toBeTruthy());
});

// ---------------------------------------------------------------------------
// The rule itself, apart from the affordance. Mutation showed the inline
// version was unreachable: the disabled button meant no click could exercise
// it, so removing the cap from the handler changed nothing observable.
// ---------------------------------------------------------------------------
import { nextSelection } from "../components/settings/OcrLanguagePicker";

describe("nextSelection", () => {
  it("adds below the cap", () => {
    expect(nextSelection(["en-US"], "zh-Hans", 3)).toEqual(["en-US", "zh-Hans"]);
  });

  it("refuses to add at the cap", () => {
    const at = ["en-US", "zh-Hans", "ja-JP"];
    expect(nextSelection(at, "de-DE", 3)).toEqual(at);
  });

  it("always allows removal, even at the cap", () => {
    expect(nextSelection(["en-US", "zh-Hans", "ja-JP"], "zh-Hans", 3))
      .toEqual(["en-US", "ja-JP"]);
  });
});
