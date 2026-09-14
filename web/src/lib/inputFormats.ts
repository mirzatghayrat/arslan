import registry from "../../../server/resources/input_formats.json";

export const INPUT_FORMATS = registry;
export const INPUT_ACCEPT = [...registry.text, ...registry.document, ...registry.spreadsheet,
  ...registry.presentation, ...registry.video].map(extension => `.${extension}`).join(",") + ",image/*";
export function documentInputSupported(name: string): boolean {
  const extension = name.split(".").pop()?.toLowerCase() ?? "";
  return [...registry.text, ...registry.document, ...registry.spreadsheet, ...registry.presentation, ...registry.video].includes(extension);
}
export function inputKind(name: string): string | undefined {
  const extension = name.split(".").pop()?.toLowerCase() ?? "";
  return Object.entries(registry).find(([, value]) => Array.isArray(value) && value.includes(extension))?.[0];
}
