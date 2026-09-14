import { expect, it } from "vitest";
import { documentInputSupported, inputKind, INPUT_ACCEPT } from "../lib/inputFormats";
import { inputMessages } from "../locales/inputs";

it("uses the shared declared registry for every extended attachment format", () => {
  for (const extension of ["ts", "tsx", "json", "csv", "xlsx", "pptx", "mp4", "webm", "docx", "pdf", "svg"]) {
    expect(documentInputSupported(`file.${extension}`)).toBe(true);
    expect(INPUT_ACCEPT).toContain(`.${extension}`);
  }
  expect(inputKind("file.MP4")).toBe("video");
  expect(documentInputSupported("file.exe")).toBe(false);
  expect(documentInputSupported("file.xlsm")).toBe(false);
});

it("every input disclosure and error exists in six languages", () => {
  const keys = Object.keys(inputMessages.en).sort();
  expect(Object.keys(inputMessages).sort()).toEqual(["de", "en", "es", "fr", "ja", "zh"]);
  for (const messages of Object.values(inputMessages)) expect(Object.keys(messages).sort()).toEqual(keys);
});
