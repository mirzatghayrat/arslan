import { expect, it } from "vitest";
import { documentInputSupported, inputKind, INPUT_ACCEPT } from "../lib/inputFormats";
import { inputMessages } from "../locales/inputs";
import registry from "../lib/input_formats.json";

it("uses the shared declared registry for every extended attachment format", () => {
  for (const extension of ["ts", "tsx", "json", "csv", "xlsx", "pptx", "mp4", "webm", "docx", "pdf", "svg"]) {
    expect(documentInputSupported(`file.${extension}`)).toBe(true);
    expect(INPUT_ACCEPT).toContain(`.${extension}`);
  }
  expect(inputKind("file.MP4")).toBe("video");
  expect(documentInputSupported("file.exe")).toBe(false);
  expect(documentInputSupported("file.xlsm")).toBe(false);
  const nonImages = [...registry.text, ...registry.document, ...registry.spreadsheet, ...registry.presentation, ...registry.video];
  expect(INPUT_ACCEPT.split(",")).toEqual([...nonImages.map(ext => `.${ext}`), "image/*"]);
  for (const [category, values] of Object.entries(registry)) {
    if (Array.isArray(values)) for (const extension of values) expect(inputKind(`file.${extension.toUpperCase()}`)).toBe(category);
  }
});

it("every input disclosure and error exists in six languages", () => {
  const keys = Object.keys(inputMessages.en).sort();
  expect(Object.keys(inputMessages).sort()).toEqual(["de", "en", "es", "fr", "ja", "zh"]);
  for (const messages of Object.values(inputMessages)) expect(Object.keys(messages).sort()).toEqual(keys);
});
