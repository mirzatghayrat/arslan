/** Turn an image File into the neutral block payload the server expects.
 *
 * WHY DOWNSCALE AT ALL — three independent reasons, any one sufficient:
 *   1. The packaged sidecar's uvicorn caps a WebSocket frame at 16 MiB
 *      (ws_max_size default), the composer accepts files up to 30 MiB, and
 *      base64 inflates by 4/3. A phone photo sent raw would simply blow the
 *      connection — and a dropped socket looks exactly like the "Interrupted"
 *      watchdog bug we just spent a release fixing.
 *   2. Every provider downscales server-side anyway (Anthropic's long edge is
 *      ~1568px), so the extra bytes buy no additional detail — only cost.
 *   3. Image tokens cannot be attributed in our ledger (spec §0.7), so the
 *      cheapest honest thing is to not send waste in the first place.
 */

/** Provider-aligned long edge. Larger buys nothing; smaller starts losing text
 * legibility in screenshots, which is the main thing users feed us. */
export const MAX_EDGE = 1568;

/** Refuse rather than send a frame the socket cannot carry. 12 MiB of base64
 * leaves headroom under the 16 MiB frame cap for the rest of the message. */
export const MAX_PAYLOAD_BYTES = 12 * 1024 * 1024;

export type ImagePayload = { name: string; mime_type: string; data: string };

/** Pure: the size an image should be resampled to. Extracted from the canvas
 * work so the arithmetic is testable without a DOM. */
export function computeTargetSize(
  width: number,
  height: number,
  maxEdge: number = MAX_EDGE,
): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= maxEdge || longest === 0) return { width, height };
  const scale = maxEdge / longest;
  // round, never floor: flooring a 1568.4 edge to 1568 is fine, but flooring a
  // 1.4px thumbnail dimension to 1 would distort tiny images.
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/** Pure: base64 length → decoded byte count, for the size guard. */
export function base64Bytes(b64: string): number {
  const padding = b64.endsWith("==") ? 2 : b64.endsWith("=") ? 1 : 0;
  return Math.max(0, (b64.length * 3) / 4 - padding);
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("unreadable image")); };
    img.src = url;
  });
}

/** File → payload, downscaling when needed. Throws when the result still would
 * not fit, because silently sending a frame that kills the socket is worse. */
export async function fileToImagePayload(file: File): Promise<ImagePayload> {
  const img = await loadImage(file);
  const target = computeTargetSize(img.naturalWidth, img.naturalHeight);
  const canvas = document.createElement("canvas");
  canvas.width = target.width;
  canvas.height = target.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas unavailable");
  ctx.drawImage(img, 0, 0, target.width, target.height);
  // JPEG for photos would lose screenshot text crispness; PNG keeps it and the
  // downscale already bounds the size.
  const dataUrl = canvas.toDataURL("image/png");
  const data = dataUrl.slice(dataUrl.indexOf(",") + 1);
  if (base64Bytes(data) > MAX_PAYLOAD_BYTES) {
    throw new Error("image too large to send");
  }
  return { name: file.name, mime_type: "image/png", data };
}
