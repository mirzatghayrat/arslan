import { render, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";

// Mock echarts so the test asserts the wrapper's contract (SVG renderer +
// setOption with the given option) without needing a real canvas/SVG backend.
const setOption = vi.fn();
const resize = vi.fn();
const dispose = vi.fn();
const init = vi.fn((..._args: unknown[]) => ({ setOption, resize, dispose }));
const registerTheme = vi.fn();

vi.mock("echarts", () => ({
  init: (...args: unknown[]) => init(...args),
  registerTheme: (...args: unknown[]) => registerTheme(...args),
}));

import EChart from "../components/EChart";

afterEach(() => {
  cleanup();
  setOption.mockClear();
  init.mockClear();
  dispose.mockClear();
});

describe("EChart", () => {
  it("registers the arslan theme, inits with the SVG renderer, and applies the option", () => {
    const option = { series: [{ type: "bar", data: [1, 2, 3] }] };
    render(<EChart option={option} className="tool-chart" />);

    expect(registerTheme).toHaveBeenCalledWith("arslan", expect.any(Object));
    // init(el, themeName, { renderer: "svg" })
    expect(init).toHaveBeenCalledTimes(1);
    const initArgs = init.mock.calls[0] as unknown[];
    expect(initArgs[1]).toBe("arslan");
    expect(initArgs[2]).toMatchObject({ renderer: "svg" });
    // setOption receives the exact option object.
    expect(setOption).toHaveBeenCalled();
    const setOptionArgs = setOption.mock.calls[0] as unknown[];
    expect(setOptionArgs[0]).toBe(option);
  });

  it("disposes the chart on unmount", () => {
    const { unmount } = render(<EChart option={{ series: [] }} />);
    unmount();
    expect(dispose).toHaveBeenCalledTimes(1);
  });
});
