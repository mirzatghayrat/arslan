import { expect, it } from "vitest";
import { attachmentImages, attachmentImageBudgetExceeded, type Attachment } from "../components/ComposerAttach";

const image = { name: "frame", mime_type: "image/png", data: "abc" };
const item = (count: number): Attachment => ({ name: "video", text: "metadata", chars: 8, truncated: false, images: Array(count).fill(image) });

it("counts still images and sampled video frames together", () => {
  const attachments = [item(3), item(3), item(3)];
  expect(attachmentImages(attachments)).toHaveLength(9);
  expect(attachmentImageBudgetExceeded(attachments)).toBe(false);
  expect(attachmentImageBudgetExceeded([...attachments, { ...item(0), image }])).toBe(true);
});

it("bounds the total encoded payload rather than each image separately", () => {
  expect(attachmentImageBudgetExceeded([{ ...item(0), image: { ...image, data: "x".repeat(12 * 1024 * 1024 + 1) } }])).toBe(true);
  expect(attachmentImageBudgetExceeded([])).toBe(false);
});
